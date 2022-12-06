#!/usr/bin/env python3
# Software License Agreement (BSD License)
#
# Copyright (c) 2017, DUKELEC, Inc.
# All rights reserved.
#
# Author: Duke Fong <d@d-l.io>

"""CDPNP GUI tool

"""

import sys, os, _thread
import struct, re
from time import sleep
import copy
import asyncio, aiohttp, websockets
import math
import numpy as np
from scipy.optimize import fsolve
from serial.tools import list_ports
from cd_ws import CDWebSocket, CDWebSocketNS
from web_serve import ws_ns, start_web

sys.path.append(os.path.join(os.path.dirname(__file__), 'pycdnet'))

from cdnet.utils.log import *
from cdnet.utils.cd_args import CdArgs
from cdnet.dev.cdbus_serial import CDBusSerial
from cdnet.dev.cdbus_bridge import CDBusBridge
from cdnet.dispatch import *

from pnp_cv import pnp_cv_init, cv_dat, cur_path
from pnp_xyz import *

args = CdArgs()
dev_str = args.get("--dev", dft="ttyACM0")

if args.get("--help", "-h") != None:
    print(__doc__)
    exit()

if args.get("--verbose", "-v") != None:
    logger_init(logging.VERBOSE)
elif args.get("--debug", "-d") != None:
    logger_init(logging.DEBUG)
elif args.get("--info", "-i") != None:
    logger_init(logging.INFO)

logging.getLogger('websockets').setLevel(logging.WARNING)
logger = logging.getLogger(f'cdpnp')

dev = CDBusBridge(dev_str) if dev_str != 'None' else None
if dev:
    CDNetIntf(dev, mac=0x00)
    pnp_cv_init()
    xyz_init()

print('start...')


board_idx = 0
coeffs = []
fiducial_pcb = [ [0, 0], [1, 1] ]
fiducial_cam = [ [[0, 0], [10, 10]] ]

def equations(p):
    s, a, d_x, d_y = p
    F = np.empty((4))
    for i in range(2):
        F[i*2] = (fiducial_pcb[i][0] * math.cos(a) - fiducial_pcb[i][1] * math.sin(a)) * s + d_x - fiducial_cam[board_idx][i][0]
        F[i*2+1] = (fiducial_pcb[i][0] * math.sin(a) + fiducial_pcb[i][1] * math.cos(a)) * s + d_y - fiducial_cam[board_idx][i][1]
    return F

def pcb2xyz(p, pcb):
    s, a, d_x, d_y = p
    step_x = (pcb[0] * math.cos(a) - pcb[1] * math.sin(a)) * s + d_x
    step_y = (pcb[0] * math.sin(a) + pcb[1] * math.cos(a)) * s + d_y
    return step_x, step_y, math.degrees(math.atan2(math.sin(-a), math.cos(-a))) # return limited-range angle

def update_coeffs():
    global board_idx, coeffs
    coeffs = []
    for i in range(len(fiducial_cam)):
        board_idx = i
        coeff = fsolve(equations, (1, 1, 1, 1)) # ret: scale, angle, del_x, del_y
        print(f'coefficient #{i}:', coeff)
        print('equations(coeff):', equations(coeff))
        print('pcb2xyz:', pcb2xyz(coeff, (-6.3, 4.75)))
        coeffs.append(coeff)
    print('coeffs:', coeffs)


async def dev_service():
    global coeffs, fiducial_pcb, fiducial_cam
    
    sock = CDWebSocket(ws_ns, 'dev')
    while True:
        dat, src = await sock.recvfrom()
        logger.debug(f'dev ser: {dat}')
        
        if dat['action'] == 'get_motor_pos':
            logger.info('get_motor_pos')
            p = load_pos() if dev else [0, 0, 0, 0]
            await sock.sendto(p, src)
        
        elif dat['action'] == 'set_motor_pos':
            logger.info('set_motor_pos')
            if dev:
                goto_pos(dat['pos'], dat['wait'], dat['speed'])
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'set_pump':
            logger.info(f"set_pump {dat['val']}")
            if dev:
                set_pump(dat['val'])
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'set_camera':
            logger.info(f"set_camera {dat['val']}")
            if dev:
                rx = cd_reg_rw(f"80:00:2{cv_dat['dev']}", 0x0036, struct.pack("<B", 255 if dat['val'] else 0))
                print('set cam ret: ' + rx.hex())
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'set_camera_cfg':
            logger.info(f"set_camera_cfg dev: {dat['dev']}, detect: {dat['detect']}, light: {dat['light']}")
            cv_dat['dev'] = dat['dev']
            cv_dat['detect'] = dat['detect']
            rx = cd_reg_rw(f"80:00:22", 0x0040, struct.pack("<b", 1 if dat['light'] else 0))
            print('set cam_light ret: ' + rx.hex())
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'get_camera_cfg':
            logger.info('get_camera_cfg')
            rx1 = cd_reg_rw(f"80:00:2{cv_dat['dev']}", 0x0036, read=1) if dev else bytes([0x80, 0x00])
            print('get_camera_cfg ret: ' + rx1.hex())
            rx2 = cd_reg_rw(f"80:00:22", 0x0040, read=1) if dev else bytes([0x80, 0x00])
            print('get_camera_light ret: ' + rx2.hex())
            await sock.sendto({'enable': rx1[1], 'dev': cv_dat['dev'], 'detect': cv_dat['detect'], 'light': rx2[1]}, src)
        
        elif dat['action'] == 'update_camera_bg':
            logger.info(f"update_camera_bg...")
            cv_dat['bg_capture'] = True
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'remove_camera_bg':
            logger.info(f"remove_camera_bg...")
            cv_dat['bg_img'] = None
            if os.path.exists(f'{cur_path}/tmp/bg_invert.png'):
                os.remove(f'{cur_path}/tmp/bg_invert.png')
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'update_coeffs':
            logger.info(f"update_coeffs")
            fiducial_pcb = dat['pcb']
            fiducial_cam = dat['cam']
            update_coeffs()
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'pcb2xyz':
            logger.info(f"pcb2xyz")
            p_xy = pcb2xyz(coeffs[dat['idx']], (dat['x'], dat['y']))
            await sock.sendto(p_xy, src)
        
        elif dat['action'] == 'get_cv_cur':
            logger.info(f"get_cv_cur")
            await sock.sendto(cv_dat['cur'], src)
        
        elif dat['action'] == 'wait_stop':
            logger.info(f"wait_stop")
            if dev:
                wait_stop()
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'enable_force':
            logger.info(f"enable_force")
            if dev:
                enable_force()
            await sock.sendto('succeeded', src)
        
        else:
            await sock.sendto('err: dev: unknown cmd', src)


async def open_brower():
    proc = await asyncio.create_subprocess_shell('/opt/google/chrome/chrome --app=http://localhost:8900')
    await proc.communicate()
    #proc = await asyncio.create_subprocess_shell('chromium --app=http://localhost:8900')
    #await proc.communicate()
    logger.info('open brower done.')


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    loop.create_task(start_web())
    loop.create_task(dev_service())
    logger.info('Please open url: http://localhost:8900')
    loop.run_forever()

