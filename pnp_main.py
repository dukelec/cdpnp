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

from pnp_cv import pnp_cv_init, cv_dat

args = CdArgs()
dev_str = args.get("--dev", dft="ttyACM0")
#pos = int(args.get("--pos", dft="0"), 0)

x = args.get("--x")
y = args.get("--y")
z = args.get("--z")
r = args.get("--r")

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
sock = CDNetSocket(('', 0xcdcd))
sock_dbg = CDNetSocket(('', 9))

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


def dbg_echo():
    while True:
        rx = sock_dbg.recvfrom()
        #print('\x1b[0;37m  ' + re.sub(br'[^\x20-\x7e]',br'.', rx[0][5:-1]).decode() + '\x1b[0m')
        print('\x1b[0;37m  ' + re.sub(br'[^\x20-\x7e]',br'.', rx[0]).decode() + '\x1b[0m')

_thread.start_new_thread(dbg_echo, ())
pnp_cv_init()


print('start...')


# 10mm / 275 pixel
DIV_MM2PIXEL = 10/275

# 4mm / (50 * 16 (md: 2)) = 0.005mm per micro step
# 360' / (50 * 16 (md: 2)) = 0.45' per micro step
DIV_MM2STEP = 0.005
DIV_DEG2STEP = 0.45

work_dft_pos = [50, 150, -80] # default work position
grab_ofs = [-33.77, -6.71]  # grab offset to camera

fiducial_pcb = [
    [-26.375, 21.35],   # point 0 (main)
    [-6.3, 4.75],       # point 1 (calc angle)
]

fiducial_xyz = [
    [102.64, 167.83],   # point 0 (main)
    [123.02, 151.59],   # point 1 (calc angle)
]

dlt_pcb = [fiducial_pcb[1][0]-fiducial_pcb[0][0], fiducial_pcb[1][1]-fiducial_pcb[0][1]]
dlt_xyz = [fiducial_xyz[1][0]-fiducial_xyz[0][0], fiducial_xyz[1][1]-fiducial_xyz[0][1]]
print(f'pcb dlt: {dlt_pcb[0]}, {dlt_pcb[1]}', math.sqrt(pow(dlt_pcb[0], 2) + pow(dlt_pcb[1], 2)))
print(f'xyz dlt: {dlt_xyz[0]}, {dlt_xyz[1]}', math.sqrt(pow(dlt_xyz[0], 2) + pow(dlt_xyz[1], 2)))

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

coeff =  fsolve(equations, (1, 1, 1, 1)) # ret: scale, angle, del_x, del_y
print('coefficient:', coeff)
print('equations(coeff):', equations(coeff))
print('pcb2xyz:', pcb2xyz(coeff, (-6.3, 4.75)))


pos = {}

import csv
with open('pos.csv', newline='') as csvfile:
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

def set_pump(val):
    pump = 2 if val != 0 else 1
    print('set pump...', pump)
    sock.sendto(b'\x20'+struct.pack("<H", 0x0036) + struct.pack("<B", pump), ('80:00:11', 0x5))
    rx = sock.recvfrom(timeout=1)
    print('set pump ret: ' + rx[0].hex(), rx[1])
    if pump == 1:
        sleep(0.5)
        pump = 0
        print('set pump...', pump)
        sock.sendto(b'\x20'+struct.pack("<H", 0x0036) + struct.pack("<B", pump), ('80:00:11', 0x5))
        rx = sock.recvfrom(timeout=1)
        print('set pump ret: ' + rx[0].hex(), rx[1])


def motor_enable():
    for i in range(5):
        print(f'motor enable: #{i+1}')
        sock.sendto(b'\x20'+struct.pack("<H", 0x00d6) + struct.pack("<B", 1), (f'80:00:0{i+1}', 0x5))
        rx = sock.recvfrom(timeout=1)
        print('motor enable ret: ' + rx[0].hex(), rx[1])


def goto_pos(pos, wait=False, s_speed=20000):
    retry_cnt = 0
    done_flag = [0, 0, 0, 0, 0]
    b_speed = struct.pack("<i", s_speed)
    while True:
        if not done_flag[0]:
            sock.sendto(b'\x20'+struct.pack("<i", round(pos[0]/DIV_MM2STEP))+b_speed, ('80:00:03', 0x6))
        if (not done_flag[1]) or (not done_flag[2]):
            sock.sendto(b'\x20'+struct.pack("<i", round(pos[1]/DIV_MM2STEP))+b_speed, ('80:00:e0', 0x6))
        if not done_flag[2]:
            sock.sendto(b'\x20'+struct.pack("<i", round(pos[2]*-1/DIV_MM2STEP))+b_speed, ('80:00:04', 0x6))
        if not done_flag[3]:
            sock.sendto(b'\x20'+struct.pack("<i", round(pos[3]/DIV_DEG2STEP))+b_speed, ('80:00:05', 0x6))
        
        for i in range(5 - (done_flag[0] + done_flag[1] + done_flag[2] + done_flag[3] + done_flag[4])):
            dat, src = sock.recvfrom(timeout=0.5)
            if src:
                if src[0] == '80:00:01':
                    done_flag[0] = 1
                if src[0] == '80:00:02':
                    done_flag[1] = 1
                if src[0] == '80:00:03':
                    done_flag[2] = 1
                if src[0] == '80:00:04':
                    done_flag[3] = 1
                if src[0] == '80:00:05':
                    done_flag[4] = 1
        if done_flag[0] and done_flag[1] and done_flag[2] and done_flag[3] and done_flag[4]:
            break
        print(f'error: retry_cnt: {retry_cnt}, done_flag: f{done_flag}')
        retry_cnt += 1
        if retry_cnt > 3:
            print(f'error: set retry > 3, done_flag: f{done_flag}')
            return -1
    
    if not wait:
        return 0
    
    retry_cnt = 0
    tgt = 1
    while True:
        sock.sendto(b'\x00'+struct.pack("<H", 0x00d7) + struct.pack("<B", 1), (f'80:00:0{tgt}', 0x5))
        dat, src = sock.recvfrom(timeout=0.5)
        if src == None:
            print(f'error: retry_cnt: {retry_cnt}')
            retry_cnt += 1
            if retry_cnt > 3:
                print('error: poll retry > 3')
                return -1
            continue
        retry_cnt = 0
        if dat[0] == 0x80 and dat[1] == 0:
            tgt += 1
            if tgt > 5:
                return 0
        sleep(0.1)


def load_pos():
    pos = [0, 0, 0, 0]
    
    print(f'motor read pos')
    
    sock.sendto(b'\x00'+struct.pack("<H", 0x00bc) + struct.pack("<B", 4), (f'80:00:03', 0x5))
    dat, src = sock.recvfrom(timeout=0.5)
    if dat and dat[0] == 0x80:
        pos[0] = struct.unpack("<i", dat[1:])[0] * DIV_MM2STEP
    
    sock.sendto(b'\x00'+struct.pack("<H", 0x00bc) + struct.pack("<B", 4), (f'80:00:01', 0x5))
    dat, src = sock.recvfrom(timeout=0.5)
    if dat and dat[0] == 0x80:
        pos[1] = struct.unpack("<i", dat[1:])[0] * DIV_MM2STEP
    
    sock.sendto(b'\x00'+struct.pack("<H", 0x00bc) + struct.pack("<B", 4), (f'80:00:04', 0x5))
    dat, src = sock.recvfrom(timeout=0.5)
    if dat and dat[0] == 0x80:
        pos[2] = struct.unpack("<i", dat[1:])[0] * DIV_MM2STEP * -1
    
    sock.sendto(b'\x00'+struct.pack("<H", 0x00bc) + struct.pack("<B", 4), (f'80:00:05', 0x5))
    dat, src = sock.recvfrom(timeout=0.5)
    if dat and dat[0] == 0x80:
        pos[3] = struct.unpack("<i", dat[1:])[0] * DIV_DEG2STEP
    
    return pos



motor_enable()


del_pow = 2 # + - by key
#cur_pos = [0, 0, 0, 0] # x, y, z, r
cur_pos = load_pos()
cur_cam = 0
cur_pump = 0

comp_top_z = -83.6
pcb_top_z = -83.2 # include component height

def pos_set():
    global del_pow, cur_pos, cur_cam, cur_pump, comp_top_z, pcb_top_z
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
            for i in range(5):
                print(f'motor set home: #{i+1}')
                sock.sendto(b'\x20'+struct.pack("<H", 0x00b1) + struct.pack("<B", 1), (f'80:00:0{i+1}', 0x5))
                rx = sock.recvfrom(timeout=1)
                print('motor set home: ' + rx[0].hex(), rx[1])
            for i in range(4):
                cur_pos[i] = 0
        
        if k == K_S:
            print('snap to cv_dat', len(cv_dat))
            if len(cv_dat):
                print('cv point', cv_dat[0])
                dx = (cv_dat[0][0] - 480/2) * DIV_MM2PIXEL
                dy = (cv_dat[0][1] - 640/2) * DIV_MM2PIXEL
                print('cv dx dy', dx, dy)
                cur_pos[0] += dx
                cur_pos[1] += dy
                cur_pos[3] = cv_dat[0][2] * -1
        
        if k == K_SHF_S:
            comp_top_z = cur_pos[2]
            print('set comp_top_z', comp_top_z)
        if k == K_SHF_P:
            pcb_top_z = cur_pos[2]
            print('set pcb_top_z', pcb_top_z)
        
        if k == K_ARROW_L:
            print('grap current comp')
            cur_pos[0] += grab_ofs[0]
            cur_pos[1] += grab_ofs[1]
            goto_pos(cur_pos, wait=True)
            sleep(1)
            cur_pos[2] = comp_top_z
            goto_pos(cur_pos, wait=True)
            sleep(1)
            set_pump(1)
            sleep(1)
            cur_pos[2] = work_dft_pos[2]
            goto_pos(cur_pos, wait=True)
            sleep(1)
            
        
        if k == K_INC or k == K_DEC:
            del_pow += (1 if k == K_INC else -1)
            del_pow = max(0, min(del_pow, 4))
            print(f'del_pow: {del_pow}')
        
        if k == K_SPACE:
            cur_cam = 255 if cur_cam == 0 else 0
            print('set cam...', cur_cam)
            sock.sendto(b'\x20'+struct.pack("<H", 0x0036) + struct.pack("<B", cur_cam), ('80:00:10', 0x5))
            rx = sock.recvfrom(timeout=1)
            print('set cam ret: ' + rx[0].hex(), rx[1])
        
        if k == K_P:
            cur_pump = int(not cur_pump)
            print('cur_pump:', cur_pump)
            set_pump(cur_pump)
        
        print(f'goto: {cur_pos[0]:.3f} {cur_pos[1]:.3f} {cur_pos[2]:.3f} {cur_pos[3]:.3f}')
        goto_pos(cur_pos)


print('cali grab offset, set camera pos...')
ret = pos_set()
if ret == 1:
    print('cali grab offset, set grab pos...')
    tmp = [cur_pos[0], cur_pos[1]]
    ret = pos_set()
    if ret == 1:
        grab_ofs[0] = cur_pos[0] - tmp[0]
        grab_ofs[1] = cur_pos[1] - tmp[1]
        print(f'cali grab offset done, ofs: {grab_ofs[0]:.3f}, {grab_ofs[1]:.3f}...')


print('show components...')
for comp in pos['0402']['100nF']:
    print(f'--- {comp}')
    p_x, p_y = pcb2xyz(coeff, (float(comp[3]), float(comp[4]) * -1))
    print(f'goto: ({p_x:.3f}, {p_y:.3f})')
    cur_pos[0], cur_pos[1], cur_pos[2] = p_x, p_y, work_dft_pos[2]
    goto_pos(cur_pos)
    pos_set()
    
    print('goto workspace')
    cur_pos[0], cur_pos[1], cur_pos[2], cur_pos[3] = work_dft_pos[0], work_dft_pos[1], work_dft_pos[2], 0


print('exit...')

