#!/usr/bin/env python3
# Software License Agreement (BSD License)
#
# Copyright (c) 2017, DUKELEC, Inc.
# All rights reserved.
#
# Author: Duke Fong <d@d-l.io>

"""CDPNP GUI tool

"""

import sys, os, _thread, tty, termios
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
prj = args.get("--prj", "-p")

if args.get("--help", "-h") != None or prj == None:
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

K_ESC = 27
K_RET = 10

K_UP = 65
K_DOWN = 66
K_LEFT = 68
K_RIGHT = 67
K_PAGEUP = 53
K_PAGEDOWN = 54
K_R = 114
k_SHF_R = 82
K_P = 112
K_H = 104

K_W = 119
K_S = 115
K_ARROW_L = 44 # <
K_ARROW_R = 46 # >
K_SHF_S = 83   # save component z
K_SHF_P = 80   # save pcb z
K_L = 108      # limit angle
K_M = 109      # enable monitor
K_SHF_M = 77   # disable monitor
K_D = 100      # toggle down put
K_N = 110      # skip
K_0 = 48
K_INC = 61 # +
K_DEC = 45 # -
K_SPACE = 32

def getkey():
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())
    try:
        while True:
            b = os.read(sys.stdin.fileno(), 3)
            k = b[2] if len(b) == 3 else b[0]
            return k
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)


pnp_cv_init()
xyz_init()


print('start...')

# 10mm / 275 pixel
DIV_MM2PIXEL = 10/275

comp_height = {
    '0402': 0.2,
    '0402C_BIG': 0.4
}
fast_to = None # e.g.: 'U12'

# not include component height
comp_base_z = -89.3
pcb_base_z = -86.3 # may override by prj cfg

work_dft_pos = [50, 165, -85.5] # default work position
grab_ofs = [-33.900, -7.000]    # grab offset to camera

#fiducial_pcb = [ [0.625, 22.175], [23.7, 4.75] ]
#fiducial_cam = [ [[105.423, 177.636], [128.672, 160.511]] ]
board_idx = 0

# update configs from prj file
with open(f'prj/{prj}.py') as prj_file:
    prj_txt = prj_file.read()
    exec(prj_txt)

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


pos = {}

import csv
with open(f'prj/{prj}.csv', newline='') as csvfile:
    spamreader = csv.reader(csvfile, delimiter=',', quotechar='"')
    for row in spamreader:
        if row[0] == 'Ref':
            continue
        
        if row[2] in pos:
            if row[1] in pos[row[2]]:
                pos[row[2]][row[1]].append(row)
            else:
                pos[row[2]][row[1]] = [row]
        else:
            pos[row[2]] = {}
            pos[row[2]][row[1]] = [row]


#print(pos)

del_pow = 2 # + - by key
#cur_pos = [0, 0, 0, 0] # x, y, z, r
cur_pos = load_pos()
aux_pos = [0, 0, 0, 0]
cv_cur_r = 0
cur_pump = 0
down_put = True
pause = False
redo = False
skip = False

cur_comp = None

def get_comp_height(comp=None):
    if not comp or comp not in comp_height:
        print(f'comp_height: default 0.2 ({comp})')
        return 0.2
    print(f'comp_height: {comp}: {comp_height[comp]}')
    return comp_height[comp]


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


def pos_set():
    global del_pow, aux_pos, cur_pump, comp_base_z, pcb_base_z, down_put, pause, redo, skip, cur_pos
    while True:
        k = getkey()
        print(k)
        if k == K_ESC:
            return 0
        
        if k == K_DOWN:
            cur_pos[1] += pow(10, del_pow)/100
        elif k == K_UP:
            cur_pos[1] -= pow(10, del_pow)/100
        elif k == K_LEFT:
            cur_pos[0] -= pow(10, del_pow)/100
        elif k == K_RIGHT:
            cur_pos[0] += pow(10, del_pow)/100
        elif k == K_PAGEDOWN:
            cur_pos[2] -= pow(10, del_pow)/100
        elif k == K_PAGEUP:
            cur_pos[2] += pow(10, del_pow)/100
        elif k == K_R:
            cur_pos[3] += pow(10, del_pow)/10
        elif k == k_SHF_R:
            cur_pos[3] -= pow(10, del_pow)/10
        
        if k == K_W:
            cam_comp_ws()
        
        if k == K_H:
            print('set home')
            set_home()
            cur_pos = [0, 0, 0, 0]
        
        if k == K_S:
            cam_comp_snap()
        
        if k == K_SHF_S:
            comp_base_z = cur_pos[2]
            print('set comp_base_z', comp_base_z)
        if k == K_SHF_P:
            pcb_base_z = cur_pos[2]
            print('set pcb_base_z', pcb_base_z)
        if k == K_L:
            print('limit angle', not cv_dat['limit_angle'])
            cv_dat['limit_angle'] = not cv_dat['limit_angle']
            continue
        if k == K_D:
            print('set down_put:', not down_put)
            down_put = not down_put
            continue
        
        if k == K_ARROW_L:
            pickup_comp()
        if k == K_ARROW_R:
            print('set redo')
            redo = True
            pause = False
            continue
        if k == K_N:
            print('set skip')
            skip = True
            continue
        
        if k == K_INC or k == K_DEC:
            del_pow += (1 if k == K_INC else -1)
            del_pow = max(0, min(del_pow, 4))
            print(f'del_pow: {del_pow}')
        
        if k == K_0:
            print('update aux_pos!')
            aux_pos = [cur_pos[0], cur_pos[1], cur_pos[2], cur_pos[3]]
        if k >= K_0 + 1 and k <= 8:
            board = (k - 1 - K_0) / 2
            sub = (k - 1 - K_0) % 2
            print(f'goto board #{board} p{sub}')
            cur_pos[0] = fiducial_cam[board][sub][0]
            cur_pos[1] = fiducial_cam[board][sub][1]
            cur_pos[2] = work_dft_pos[2] + (pcb_base_z - comp_base_z)
            cur_pos[3] = 0
        
        if k == K_SHF_M or k == K_M:
            cur_cam = 255 if k == K_M else 0
            print('set cam...', cur_cam)
            rx = cd_reg_rw('80:00:10', 0x0036, struct.pack("<B", cur_cam))
            print('set cam ret: ' + rx.hex())
        
        if k == K_P:
            cur_pump = int(not cur_pump)
            print('cur_pump:', cur_pump)
            set_pump(cur_pump)
        
        if k == K_SPACE:
            pause = not pause
            print('toggle pause, pause =', pause)
            continue
        
        print(f'goto: {cur_pos[0]:.3f}, {cur_pos[1]:.3f}, {cur_pos[2]:.3f}, {cur_pos[3]:.3f}')
        print(f'delt: {cur_pos[0]-aux_pos[0]:.3f}, {cur_pos[1]-aux_pos[1]:.3f}, {cur_pos[2]-aux_pos[2]:.3f}, {cur_pos[3]-aux_pos[3]:.3f}')
        goto_pos(cur_pos)


print('free run...')
pos_set()

coeffs = []
for i in range(len(fiducial_cam)):
    board_idx = i
    coeff = fsolve(equations, (1, 1, 1, 1)) # ret: scale, angle, del_x, del_y
    print(f'coefficient #{i}:', coeff)
    print('equations(coeff):', equations(coeff))
    print('pcb2xyz:', pcb2xyz(coeff, (-6.3, 4.75)))
    coeffs.append(coeff)


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
    #asyncio.get_event_loop().create_task(file_service())
    #asyncio.get_event_loop().create_task(dev_service())
    #asyncio.get_event_loop().create_task(cdbus_proxy_service())
    #asyncio.get_event_loop().create_task(open_brower())
    logger.info('Please open url: http://localhost:8900')
    asyncio.get_event_loop().run_forever()

