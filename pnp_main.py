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
import json5
import asyncio, aiohttp, websockets
import math
import numpy as np
from scipy.optimize import fsolve
from serial.tools import list_ports
from cd_ws import CDWebSocket, CDWebSocketNS
from web_serve import ws_ns, start_web

try:
    import readline
except:
    from pyreadline import Readline
    readline = Readline()

sys.path.append(os.path.join(os.path.dirname(__file__), 'pycdnet'))

from cdnet.utils.log import *
from cdnet.utils.cd_args import CdArgs
from cdnet.dev.cdbus_serial import CDBusSerial
from cdnet.dev.cdbus_bridge import CDBusBridge
from cdnet.dispatch import *

from pnp_cv import pnp_cv_init, cv_dat
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

csa = {
    'async_loop': None,
    'dev': None,    # serial device
    'net': 0x00,    # local net
    'mac': 0x00,    # local mac
    'proxy': None,  # cdbus frame proxy socket
    'cfgs': []      # config list
}

dev = CDBusBridge(dev_str)
CDNetIntf(dev, mac=0x00)

pnp_cv_init()
xyz_init()
print('start...')

# 10mm / 275 pixel
DIV_MM2PIXEL = 10/275


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
    return step_x, step_y

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


cur_pos = load_pos()
cv_cur_r = 0
cur_pump = 0


def cam_comp_ws():
    print('camera goto components workspace')
    cur_pos[0], cur_pos[1], cur_pos[2], cur_pos[3] = work_dft_pos[0], work_dft_pos[1], work_dft_pos[2] + (pcb_base_z - comp_base_z), 0
    goto_pos(cur_pos, wait=True)
    cur_pos[0], cur_pos[1], cur_pos[2], cur_pos[3] = work_dft_pos[0], work_dft_pos[1], work_dft_pos[2], 0
    goto_pos(cur_pos, wait=True)

def cam_comp_snap():
    global cv_cur_r
    for i in range(3):
        print(f'camera snap to component {i}:', cv_dat['cur'])
        if cv_dat['cur']:
            dx = (cv_dat['cur'][0] - 480/2) * DIV_MM2PIXEL
            dy = (cv_dat['cur'][1] - 640/2) * DIV_MM2PIXEL
            print('cv dx dy', dx, dy)
            cur_pos[0] += dx
            cur_pos[1] += dy
            cur_pos[3] = 0 #cv_dat['cur'][2]
            cv_cur_r = cv_dat['cur'][2]
            goto_pos(cur_pos, wait=True)
        sleep(0.2)
    if cv_dat['cur']:
        return 0
    return -1

def pickup_comp():
    global cur_pump
    print('pickup focused comp')
    cur_pos[0] += grab_ofs[0]
    cur_pos[1] += grab_ofs[1]
    goto_pos(cur_pos, wait=True)
    if down_put:
        sleep(1)
        cur_pos[2] = comp_base_z + get_comp_height(cur_comp)
        enable_force()
        goto_pos(cur_pos, wait=True, s_speed=200)
        sleep(0.5)
        set_pump(1)
        cur_pump = 1
        sleep(0.5)
        cur_pos[2] = work_dft_pos[2] + (pcb_base_z - comp_base_z) + get_comp_height(cur_comp)
        goto_pos(cur_pos, wait=True, s_speed=1000)
        cur_pos[3] = -cv_cur_r
        goto_pos(cur_pos, wait=True)

def putdown_comp(p_x, p_y, p_a):
    global cur_pump
    print('putdown comp to pcb')
    cur_pos[0] = p_x + grab_ofs[0]
    cur_pos[1] = p_y + grab_ofs[1]
    cur_pos[2] = work_dft_pos[2] + (pcb_base_z - comp_base_z) + get_comp_height(cur_comp)
    cur_pos[3] = p_a - cv_cur_r
    goto_pos(cur_pos, wait=True)
    while pause:
        sleep(0.1)
    if not redo and down_put:
        sleep(1)
        cur_pos[2] = pcb_base_z + get_comp_height(cur_comp)
        enable_force()
        goto_pos(cur_pos, wait=True, s_speed=200)
        sleep(0.5)
        set_pump(0)
        cur_pump = 0
        cur_pos[2] = work_dft_pos[2] + (pcb_base_z - comp_base_z)
        goto_pos(cur_pos, wait=True)




def work_thread():
    global cur_comp, pause, redo, skip, fast_to, board_idx
    print('show components...')
    for footprint in pos:
        cur_comp = footprint
        for comp_val in pos[footprint]:
            count = 0
            print(f'\n-> {footprint} -> {comp_val}, {len(pos[footprint][comp_val])} / board, paused')
            if not fast_to:
                pause = True
            while pause:
                sleep(0.1)
            for comp in pos[footprint][comp_val]:
                count += 1
                for i in range(len(fiducial_cam)):
                    board_idx = i
                    while True:
                        redo = False
                        skip = False
                        print(f'--- board #{i}, {comp}, {count}/{len(pos[footprint][comp_val])}')
                        if comp[0] == fast_to:
                            fast_to = None
                        if fast_to:
                            break
                        p_x, p_y = pcb2xyz(coeffs[i], (float(comp[3]), float(comp[4]) * -1))
                        p_a = float(comp[5])
                        if comp[6] == 'bottom':
                            p_a = 180 - p_a
                        elif p_a > 180:
                            p_a = - (360 - p_a)
                        
                        if skip:
                            break
                        print(f'goto: ({p_x:.3f}, {p_y:.3f})')
                        if cur_pos[2] < work_dft_pos[2] + (pcb_base_z - comp_base_z):
                            cur_pos[2] = work_dft_pos[2] + (pcb_base_z - comp_base_z)
                            goto_pos(cur_pos, wait=True)
                        cur_pos[0], cur_pos[1], cur_pos[2] = p_x, p_y, work_dft_pos[2] + (pcb_base_z - comp_base_z)
                        goto_pos(cur_pos)
                        if skip:
                            break
                        wait_stop()
                        sleep(1)
                        if skip:
                            break
                        while pause:
                            sleep(0.1)
                        if redo:
                            continue
                        
                        cam_comp_ws()
                        if skip:
                            break
                        sleep(1)
                        while pause:
                            sleep(0.1)
                        if redo:
                            continue
                        
                        if cam_comp_snap() < 0:
                            print('snap empty, wait')
                            pause = True
                        if skip:
                            break
                        sleep(1)
                        while pause:
                            sleep(0.1)
                        if redo:
                            continue
                        
                        pickup_comp()
                        if not down_put:
                            print('pickup wait')
                            pause = True
                        if skip:
                            break
                        sleep(1)
                        while pause:
                            sleep(0.1)
                        if redo:
                            continue
                        if not down_put:
                            cur_pos[2] = work_dft_pos[2] + (pcb_base_z - comp_base_z) + get_comp_height(cur_comp)
                            goto_pos(cur_pos, wait=True)
                        
                        putdown_comp(p_x, p_y, p_a)
                        if skip:
                            break
                        if not down_put:
                            print('putdown wait')
                            pause = True
                        sleep(1)
                        while pause:
                            sleep(0.1)
                        if redo:
                            continue
                        if not down_put:
                            cur_pos[2] = work_dft_pos[2] + (pcb_base_z - comp_base_z)
                            goto_pos(cur_pos, wait=True)
                        break
    
    print('')
    print('all finished...\n')


#_thread.start_new_thread(work_thread, ())
#pos_set()

#print('exit...')

async def dev_service():
    global coeffs, fiducial_pcb, fiducial_cam
    
    sock = CDWebSocket(ws_ns, 'dev')
    while True:
        dat, src = await sock.recvfrom()
        logger.debug(f'dev ser: {dat}')
        
        if dat['action'] == 'get_motor_pos':
            logger.info('get_motor_pos')
            p = load_pos()
            await sock.sendto(p, src)
        
        elif dat['action'] == 'get_init_home':
            logger.info('get_init_home')
            await sock.sendto(xyz['init_home'], src)
        
        elif dat['action'] == 'set_motor_pos':
            logger.info('set_motor_pos')
            goto_pos(dat['pos'], dat['wait'])
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'set_home':
            logger.info('set_home')
            set_home()
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'set_pump':
            logger.info(f"set_pump {dat['val']}")
            set_pump(dat['val'])
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'set_camera':
            logger.info(f"set_camera {dat['val']}")
            rx = cd_reg_rw('80:00:10', 0x0036, struct.pack("<B", 255 if dat['val'] else 0))
            print('set cam ret: ' + rx.hex())
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'limit_angle':
            logger.info(f"limit_angle {dat['val']}")
            cv_dat['limit_angle'] = dat['val']
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
            wait_stop()
            await sock.sendto('succeeded', src)
        
        elif dat['action'] == 'enable_force':
            logger.info(f"enable_force")
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
    start_web(None)
    csa['proxy'] = CDWebSocket(ws_ns, 'proxy')
    csa['async_loop'] = asyncio.get_event_loop();
    asyncio.get_event_loop().create_task(dev_service())
    logger.info('Please open url: http://localhost:8900')
    asyncio.get_event_loop().run_forever()

