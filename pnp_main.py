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
from cd_ws import CDWebSocket, CDWebSocketNS
from web_serve import ws_ns, start_web

sys.path.append(os.path.join(os.path.dirname(__file__), 'pycdnet'))

from cdnet.utils.log import *
from cdnet.utils.cd_args import CdArgs
from cdnet.utils.serial_get_port import *
from cdnet.dev.cdbus_serial import CDBusSerial
from cdnet.dispatch import *

from pnp_cv import pnp_cv_start, cv_dat, cur_path
from pnp_xyz import *

args = CdArgs()
dev_str = args.get("--dev", dft=":5740")

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

if dev_str == ':5740':
    if get_port('2E3C:5740'):
        dev_str = '2E3C:5740' # bridge hw v6
    elif get_port('0483:5740'):
        dev_str = '0483:5740' # bridge hw v5
    else:
        logger.error(f'cdbus bridge not found, serial ports:')
        dump_ports()
        exit()

# baudrate ignored for cdbus bridge
dev = CDBusSerial(dev_str) if dev_str != 'None' else None
if dev:
    CDNetIntf(dev, mac=0x00)
    xyz_init()

print('start...')


coeff = None
fiducial_pcb = [ [0, 0], [1, 1] ]
fiducial_cam = [ [0, 0], [10, 10] ]

def equations(p):
    s, a, d_x, d_y = p
    F = np.empty((4))
    for i in range(2):
        F[i*2] = (fiducial_pcb[i][0] * math.cos(a) - fiducial_pcb[i][1] * math.sin(a)) * s + d_x - fiducial_cam[i][0]
        F[i*2+1] = (fiducial_pcb[i][0] * math.sin(a) + fiducial_pcb[i][1] * math.cos(a)) * s + d_y - fiducial_cam[i][1]
    return F

def pcb2xyz(p, pcb):
    s, a, d_x, d_y = p
    step_x = (pcb[0] * math.cos(a) - pcb[1] * math.sin(a)) * s + d_x
    step_y = (pcb[0] * math.sin(a) + pcb[1] * math.cos(a)) * s + d_y
    return step_x, step_y, math.degrees(math.atan2(math.sin(-a), math.cos(-a))) # return limited-range angle

def update_coeff():
    global coeff
    coeff = fsolve(equations, (1, 1, 1, 1)) # ret: scale, angle, del_x, del_y
    #print(f'coefficient:', coeff)
    #print('equations(coeff):', equations(coeff))
    #print('coeff:', coeff)


async def dev_service():
    global coeff, fiducial_pcb, fiducial_cam
    
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
        
        elif dat['action'] == 'get_pump_hw_ver':
            logger.info(f"get_pump_hw_ver: {xyz['pump_hw_ver']}")
            await sock.sendto(xyz['pump_hw_ver'], src)
        
        elif dat['action'] == 'get_pump_pressure':
            logger.info(f"get_pump_pressure")
            pressure = 0.0
            if dev:
                pressure = get_pump_pressure()
            await sock.sendto(pressure, src)
        
        elif dat['action'] == 'set_pump':
            logger.info(f"set_pump {dat['val']}")
            if dev:
                set_pump(dat['val'])
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'set_camera':
            logger.info(f"set_camera {dat['val']}")
            if dev:
                rx = cd_reg_rw(f"80:00:2{cv_dat['dev']}", 0x005f, struct.pack("<B", 255 if dat['val'] else 0))
                print('set cam ret: ' + rx.hex())
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'set_camera_cfg':
            logger.info(f"set_camera_cfg dev: {dat['dev']}, detect: {dat['detect']}, light: {dat['light1']}_{dat['light2']}, expos: {dat['expos']}")
            cv_dat['dev'] = dat['dev']
            cv_dat['detect'] = dat['detect']
            rx = cd_reg_rw(f"80:00:21", 0x0069, struct.pack("<b", 1 if dat['light1'] else 0))
            print('set cam_light1 ret: ' + rx.hex())
            rx = cd_reg_rw(f"80:00:22", 0x0069, struct.pack("<b", 1 if dat['light2'] else 0))
            print('set cam_light2 ret: ' + rx.hex())
            rx = cd_reg_rw(f"80:00:2{cv_dat['dev']}", 0x0044, struct.pack("<H", dat['expos']))
            print('set exposure ret: ' + rx.hex())
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'get_camera_cfg':
            logger.info('get_camera_cfg')
            rx0 = cd_reg_rw(f"80:00:2{cv_dat['dev']}", 0x005f, read=1) if dev else bytes([0x80, 0x00])
            print('get_camera_cfg ret: ' + rx0.hex())
            rx1 = cd_reg_rw(f"80:00:21", 0x0069, read=1) if dev else bytes([0x80, 0x00])
            print('get_camera_light1 ret: ' + rx1.hex())
            rx2 = cd_reg_rw(f"80:00:22", 0x0069, read=1) if dev else bytes([0x80, 0x00])
            print('get_camera_light2 ret: ' + rx2.hex())
            await sock.sendto({'enable': rx0[1], 'dev': cv_dat['dev'], 'detect': cv_dat['detect'], 'light1': rx1[1], 'light2': rx2[1]}, src)
        
        elif dat['action'] == 'set_vision_cfg':
            logger.info(f"set_vision_cfg nozzle_thresh: {dat['nozzle_thresh']}, debug: {dat['debug']}")
            cv_dat['nozzle_thresh'] = dat['nozzle_thresh']
            cv_dat['debug'] = dat['debug']
            await sock.sendto('succeeded', src)
        
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
        
        elif dat['action'] == 'pcb2xyz':
            logger.info(f"pcb2xyz")
            fiducial_pcb = dat['pcb']
            fiducial_cam = dat['cam']
            update_coeff()
            p_xy = pcb2xyz(coeff, (dat['x'], dat['y']))
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


def start_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(start_web())
    loop.create_task(dev_service())
    #csa['async_loop'].create_task(open_brower())
    logger.info('Please open url: http://localhost:8900')
    loop.run_forever()

if dev:
    _thread.start_new_thread(start_loop, ())
    pnp_cv_start() # make cv gui in foreground thread (for macos)
else:
    start_loop()

