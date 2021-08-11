#!/usr/bin/env python3
# Software License Agreement (BSD License)
#
# Copyright (c) 2017, DUKELEC, Inc.
# All rights reserved.
#
# Author: Duke Fong <d@d-l.io>

"""CDNET debug tool

This tool use CDBUS Bridge by default, communicate with any node on the RS485 bus.
<- 
"""

import sys, tty, os, termios
import struct
from time import sleep
import _thread
import re
import math
import numpy as np
from scipy.optimize import fsolve
try:
    import readline
except:
    from pyreadline import Readline
    readline = Readline()

sys.path.append(os.path.join(os.path.dirname(__file__), './pycdnet'))

from cdnet.utils.log import *
from cdnet.utils.cd_args import CdArgs
from cdnet.dev.cdbus_serial import CDBusSerial
from cdnet.dev.cdbus_bridge import CDBusBridge
from cdnet.dispatch import *

from pnp_xyz import *
from pnp_cv import pnp_cv_init, cv_dat

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


pnp_cv_init(False)
xyz_init()


print('start...')

# 10mm / 275 pixel
DIV_MM2PIXEL = 10/275

# not include component height
pcb_base_z = -84.8-0.2 # may override by prj cfg

work_dft_pos = [226.845, 186.651, -82]  # default work position
grab_ofs = [-33.13, -36.80]           # grab offset to camera

#fiducial_pcb = [ [7, -7], [55, -7] ]
#fiducial_cam = [ [235.615, 182.641], [283.515, 182.941] ]

pos = []

# update configs from prj file
with open(f'prj/{prj}.py') as prj_file:
    prj_txt = prj_file.read()
    exec(prj_txt)

fiducial_xyz = [[fiducial_cam[0][0]+grab_ofs[0], fiducial_cam[0][1]+grab_ofs[1]],
                [fiducial_cam[1][0]+grab_ofs[0], fiducial_cam[1][1]+grab_ofs[1]]]


def equations(p):
    s, a, d_x, d_y = p
    F = np.empty((4))
    for i in range(2):
        F[i*2] = (fiducial_pcb[i][0] * math.cos(a) - fiducial_pcb[i][1] * math.sin(a)) * s + d_x - fiducial_xyz[i][0]
        F[i*2+1] = (fiducial_pcb[i][0] * math.sin(a) + fiducial_pcb[i][1] * math.cos(a)) * s + d_y - fiducial_xyz[i][1]
    return F

def pcb2xyz(p, pcb):
    s, a, d_x, d_y = p
    step_x = (pcb[0] * math.cos(a) - pcb[1] * math.sin(a)) * s + d_x
    step_y = (pcb[0] * math.sin(a) + pcb[1] * math.cos(a)) * s + d_y
    return step_x, step_y

coeff = fsolve(equations, (1, 1, 1, 1)) # ret: scale, angle, del_x, del_y
print('coefficient:', coeff)
print('equations(coeff):', equations(coeff))
print('pcb2xyz:', pcb2xyz(coeff, (-6.3, 4.75)))


del_pow = 2 # + - by key
#cur_pos = [0, 0, 0, 0] # x, y, z, r
cur_pos = load_pos()
aux_pos = [0, 0, 0, 0]
pause = False

def pos_set():
    global del_pow, cur_pos, aux_pos, pcb_base_z, pause, cur_pos
    while True:
        k = getkey()
        print(k)
        if k == K_ESC:
            return 0
        if k == K_RET:
            return 1
        
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
            print('goto workspace')
            cur_pos[0], cur_pos[1], cur_pos[2], cur_pos[3] = work_dft_pos[0], work_dft_pos[1], work_dft_pos[2], 0
        
        if k == K_H:
            print('set home')
            set_home()
            cur_pos = [0, 0, 0, 0]
        
        if k == K_S:
            print('snap to cv_dat', cv_dat['cur'])
            if cv_dat['cur']:
                dx = (cv_dat['cur'][0] - 480/2) * DIV_MM2PIXEL
                dy = (cv_dat['cur'][1] - 640/2) * DIV_MM2PIXEL
                print('cv dx dy', dx, dy)
                cur_pos[0] += dx
                cur_pos[1] += dy
                cur_pos[3] = cv_dat['cur'][2]
        
        if k == K_SHF_P:
            pcb_base_z = cur_pos[2]
            print('set pcb_base_z', pcb_base_z)
        
        
        if k == K_INC or k == K_DEC:
            del_pow += (1 if k == K_INC else -1)
            del_pow = max(0, min(del_pow, 4))
            print(f'del_pow: {del_pow}')
        
        if k == K_0:
            print('update aux_pos!')
            aux_pos = [cur_pos[0], cur_pos[1], cur_pos[2], cur_pos[3]]
        
        if k == K_0 + 1:
            print('goto p1')
            cur_pos[0] = fiducial_cam[0][0]
            cur_pos[1] = fiducial_cam[0][1]
            cur_pos[2] = work_dft_pos[2]
            cur_pos[3] = 0
        if k == K_0 + 2:
            print('goto p2')
            cur_pos[0] = fiducial_cam[1][0]
            cur_pos[1] = fiducial_cam[1][1]
            cur_pos[2] = work_dft_pos[2]
            cur_pos[3] = 0
        
        if k == K_SHF_M or k == K_M:
            cur_cam = 255 if k == K_M else 0
            print('set cam...', cur_cam)
            rx = cd_reg_rw('80:00:10', 0x0036, struct.pack("<B", cur_cam))
            print('set cam ret: ' + rx.hex())
        
        if k == K_SPACE:
            pause = not pause
            print('toggle pause, pause =', pause)
            continue
        
        print(f'goto: {cur_pos[0]:.3f}, {cur_pos[1]:.3f}, {cur_pos[2]:.3f}, {cur_pos[3]:.3f}')
        print(f'delt: {cur_pos[0]-aux_pos[0]:.3f}, {cur_pos[1]-aux_pos[1]:.3f}, {cur_pos[2]-aux_pos[2]:.3f}, {cur_pos[3]-aux_pos[3]:.3f}')
        goto_pos(cur_pos)


print('free run...')
pos_set()


def work_thread():
    global pause, fast_to
    while True:
        p_x, p_y = pcb2xyz(coeff, (pos[0][0], pos[0][1]))
        cur_pos[0], cur_pos[1], cur_pos[2] = p_x-0.4, p_y, pcb_base_z + 3
        goto_pos(cur_pos, wait=True)
        pause = True
        while pause:
            sleep(0.5)
        
        print('start cut...')
        for p in pos:
            print(f'--- {p}')
            if fast_to > 0:
                fast_to -= 1
                pause = True
                continue
            p_x, p_y = pcb2xyz(coeff, (p[0], p[1]))
            
            print(f'goto left top')
            cur_pos[0], cur_pos[1], cur_pos[2] = p_x, p_y, pcb_base_z + 3
            goto_pos(cur_pos, wait=True)
            while pause:
                sleep(0.5)
            
            print(f'goto left down')
            cur_pos[0], cur_pos[1], cur_pos[2] = p_x, p_y, pcb_base_z
            goto_pos(cur_pos, wait=True, s_speed=25000)
            while pause:
                sleep(0.5)
            
            print(f'goto right down')
            cur_pos[0], cur_pos[1], cur_pos[2] = p_x+cut_len_x, p_y+cut_len_y, pcb_base_z
            goto_pos(cur_pos, wait=True, s_speed=500)
            while pause:
                sleep(0.5)
            
            print(f'goto right up')
            cur_pos[0], cur_pos[1], cur_pos[2] = p_x+cut_len_x, p_y+cut_len_y, pcb_base_z + 3
            goto_pos(cur_pos, wait=True)
            while pause:
                sleep(0.5)
        
        print('end cut...')

_thread.start_new_thread(work_thread, ())
pos_set()

print('exit...')

