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
import urllib.request
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


xyz_init()

print('start...')

# not include component height
pcb_base_z = -102

work_dft_pos = [45, 20, -50]  # default work position
mb_width = 160
mb_line = 6
mb_speed = 10000 # 7000000us/200mm => 35000 us/mm

# 1inch = 25.4mm
# 600dot/inch => 600dot/25.4mm => 23.622 dot/mm
# 35000 us / 23.622 dot => 1481.666 us/dot
#
# space=-200&pos_cali=0&buzzer=1&strength=20&period_us=1482
# http://192.168.88.1/cgi-bin/cmd?cmd=set_conf&conf=space%3D-200%26pos_cali%3D0%26buzzer%3D1%26strength%3D20%26period_us%3D1482

# http://192.168.88.1/cgi-bin/cmd?cmd=get_conf


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
            for i in range(4): # skip 5
                print(f'motor set home: #{i+1}')
                sock.sendto(b'\x20'+struct.pack("<H", 0x00b1) + struct.pack("<B", 1), (f'80:00:0{i+1}', 0x5))
                rx = sock.recvfrom(timeout=1)
                print('motor set home: ' + rx[0].hex(), rx[1])
            for i in range(4):
                cur_pos[i] = 0
        
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
        p_x, p_y = work_dft_pos[0], work_dft_pos[1]
        cur_pos[0], cur_pos[1], cur_pos[2] = p_x, p_y, pcb_base_z + 0 # +3
        goto_pos(cur_pos, wait=True)
        pause = True
        while pause:
            sleep(0.5)
        
        print('start cut...')
        print(f'reload configs:')
        print(urllib.request.urlopen("http://192.168.88.1/cgi-bin/cmd?cmd=simulate&key=0").read())
        print(f'reset data index to 0:')
        print(urllib.request.urlopen("http://192.168.88.1/cgi-bin/cmd?cmd=simulate&key=3").read())
        
        for p in range(mb_line):
            print(f'--- {p}')
            p_x, p_y = work_dft_pos[0], work_dft_pos[1]
            p_y += 14.3 * p
            
            print(f'goto left top')
            cur_pos[0], cur_pos[1], cur_pos[2] = p_x, p_y, pcb_base_z + 3
            goto_pos(cur_pos, wait=True)
            while pause:
                sleep(0.5)
            
            print(f'goto left down')
            cur_pos[0], cur_pos[1], cur_pos[2] = p_x, p_y, pcb_base_z
            goto_pos(cur_pos, wait=True)
            while pause:
                sleep(0.5)
            
            print(f'long press:')
            print(urllib.request.urlopen("http://192.168.88.1/cgi-bin/cmd?cmd=get_info").read())
            print(urllib.request.urlopen("http://192.168.88.1/cgi-bin/cmd?cmd=simulate&key=2").read())
            sleep(2)
            
            print(f'short press:')
            print(urllib.request.urlopen("http://192.168.88.1/cgi-bin/cmd?cmd=get_info").read())
            print(urllib.request.urlopen("http://192.168.88.1/cgi-bin/cmd?cmd=simulate&key=1").read())
            sleep(1)
            
            print(f'start print:')
            print(urllib.request.urlopen("http://192.168.88.1/cgi-bin/cmd?cmd=get_info").read())
            print(urllib.request.urlopen("http://192.168.88.1/cgi-bin/cmd?cmd=simulate&key=1").read())
            
            print(f'goto right down')
            cur_pos[0], cur_pos[1], cur_pos[2] = p_x+mb_width, p_y, pcb_base_z
            goto_pos(cur_pos, wait=True, s_speed=mb_speed) # speed!
            while pause:
                sleep(0.5)
            
            print(f'goto right up')
            cur_pos[0], cur_pos[1], cur_pos[2] = p_x+mb_width, p_y, pcb_base_z + 3
            goto_pos(cur_pos, wait=True)
            while pause:
                sleep(0.5)
        
        print('end cut...')

_thread.start_new_thread(work_thread, ())
pos_set()

print('exit...')

