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
K_L = 108      # limit angle
K_M = 109      # enable monitor
K_SHF_M = 77   # disable monitor
K_D = 100      # toggle down put
K_N = 110      # skip
K_0 = 48
K_1 = 49
K_2 = 50
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
# 360' / (50 * 64 (md: 4)) = 0.45' per micro step
DIV_MM2STEP = 0.005
DIV_DEG2STEP = 0.1125

work_dft_pos = [50, 165, -85.5] # default work position
#grab_ofs = [-33.87, -6.64]  # grab offset to camera
#grab_ofs = [-33.900, -6.700]  # grab offset to camera
grab_ofs = [-33.82, -6.75]  # grab offset to camera

fiducial_pcb = [
    [3, 45.9],   # point 0
    [67, 6],     # point 1
]
fiducial_xyz = [
    [106.430, 165.850],   # point 0
    [170.840, 127.010],   # point 1
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
    sock.clear()
    sock.sendto(b'\x20'+struct.pack("<H", 0x0036) + struct.pack("<B", pump), ('80:00:11', 0x5))
    rx = sock.recvfrom(timeout=1)
    print('set pump ret: ' + rx[0].hex(), rx[1])
    if pump == 1:
        sleep(0.5)
        pump = 0
        print('set pump...', pump)
        sock.clear()
        sock.sendto(b'\x20'+struct.pack("<H", 0x0036) + struct.pack("<B", pump), ('80:00:11', 0x5))
        rx = sock.recvfrom(timeout=1)
        print('set pump ret: ' + rx[0].hex(), rx[1])


def motor_enable():
    for i in range(5):
        print(f'motor enable: #{i+1}')
        sock.clear()
        sock.sendto(b'\x20'+struct.pack("<H", 0x00d6) + struct.pack("<B", 1), (f'80:00:0{i+1}', 0x5))
        rx = sock.recvfrom(timeout=1)
        print('motor enable ret: ' + rx[0].hex(), rx[1])
    for i in range(5):
        print(f'motor set min speed: #{i+1}')
        sock.clear()
        sock.sendto(b'\x20'+struct.pack("<H", 0x00c8) + struct.pack("<I", 400), (f'80:00:0{i+1}', 0x5))
        rx = sock.recvfrom(timeout=1)
        print('motor set min speed ret: ' + rx[0].hex(), rx[1])
    '''
    print(f'motor set #5')
    sock.sendto(b'\x20'+struct.pack("<H", 0x00c8) + struct.pack("<I", 100), (f'80:00:05', 0x5))
    rx = sock.recvfrom(timeout=1)
    print('motor set #5 ret: ' + rx[0].hex(), rx[1])
    '''
    print(f'motor set #5')
    sock.clear()
    sock.sendto(b'\x20'+struct.pack("<H", 0x00c4) + struct.pack("<I", 100), (f'80:00:05', 0x5))
    rx = sock.recvfrom(timeout=1)
    print('motor set #5 ret: ' + rx[0].hex(), rx[1])


def wait_stop():
    retry_cnt = 0
    tgt = 1
    while True:
        sock.clear()
        sock.sendto(b'\x00'+struct.pack("<H", 0x00d7) + struct.pack("<B", 1), (f'80:00:0{tgt}', 0x5))
        dat, src = sock.recvfrom(timeout=0.8)
        if src == None:
            print(f'error: retry_cnt: {retry_cnt}')
            retry_cnt += 1
            if retry_cnt > 3:
                print('error: poll retry > 3')
                exit(-1)
            continue
        retry_cnt = 0
        if dat[0] == 0x80 and dat[1] == 0:
            tgt += 1
            if tgt > 5:
                return 0
        sleep(0.1)


last_pos = None
def goto_pos(pos, wait=False, s_speed=20000):
    global last_pos
    if last_pos == None:
        last_pos = load_pos()
    delta = [pos[0]-last_pos[0], pos[1]-last_pos[1], pos[2]-last_pos[2]]
    last_pos = [pos[0], pos[1], pos[2]]
    retry_cnt = 0
    done_flag = [0, 0, 0, 0, 0]
    m_vector = max(math.sqrt(math.pow(delta[0], 2) + math.pow(delta[1], 2) + math.pow(delta[2], 2)), 0.01)
    v_speed = [round(s_speed * abs(delta[0])/m_vector), round(s_speed * abs(delta[1])/m_vector), round(s_speed * abs(delta[2])/m_vector), round(s_speed / 100)]
    b_speed = [struct.pack("<i", v_speed[0]), struct.pack("<i", v_speed[1]), struct.pack("<i", v_speed[2]), struct.pack("<i", v_speed[3])]
    
    while True:
        sock.clear()
        if not done_flag[2]:
            sock.sendto(b'\x20'+struct.pack("<i", round(pos[0]/DIV_MM2STEP))+b_speed[0], ('80:00:03', 0x6))
        if (not done_flag[0]) or (not done_flag[1]):
            sock.sendto(b'\x20'+struct.pack("<i", round(pos[1]/DIV_MM2STEP))+b_speed[1], ('80:00:e0', 0x6))
        if not done_flag[3]:
            sock.sendto(b'\x20'+struct.pack("<i", round(pos[2]*-1/DIV_MM2STEP))+b_speed[2], ('80:00:04', 0x6))
        if not done_flag[4]:
            sock.sendto(b'\x20'+struct.pack("<i", round(pos[3]*-1/DIV_DEG2STEP))+b_speed[3], ('80:00:05', 0x6))
        
        for i in range(5 - (done_flag[0] + done_flag[1] + done_flag[2] + done_flag[3] + done_flag[4])):
            dat, src = sock.recvfrom(timeout=0.8)
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
            exit(-1)
    
    if not wait:
        return 0
    wait_stop()



def load_pos():
    pos = [0, 0, 0, 0]
    
    print(f'motor read pos')
    sock.clear()
    
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
        pos[3] = struct.unpack("<i", dat[1:])[0] * DIV_DEG2STEP * -1
    
    return pos



motor_enable()


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

# not include component height
comp_base_z = -89.1
pcb_base_z = -87.8 # -89.3

cur_comp = None
comp_height = {
    '0402': 0.2,
    '0402C_BIG': 0.4
}

def get_comp_height(comp=None):
    if not comp or comp not in comp_height:
        print(f'comp_height: default 1.0 ({comp})')
        return 1.0
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
        goto_pos(cur_pos, wait=True)
        sleep(0.5)
        set_pump(1)
        cur_pump = 1
        sleep(0.5)
        cur_pos[2] = work_dft_pos[2] + (pcb_base_z - comp_base_z) + get_comp_height(cur_comp)
        goto_pos(cur_pos, wait=True)
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
        goto_pos(cur_pos, wait=True)
        sleep(0.5)
        set_pump(0)
        cur_pump = 0
        cur_pos[2] = work_dft_pos[2] + (pcb_base_z - comp_base_z)
        goto_pos(cur_pos, wait=True)


def pos_set():
    global del_pow, aux_pos, cur_pump, comp_base_z, pcb_base_z, down_put, pause, redo, skip
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
            for i in range(5):
                print(f'motor set home: #{i+1}')
                sock.sendto(b'\x20'+struct.pack("<H", 0x00b1) + struct.pack("<B", 1), (f'80:00:0{i+1}', 0x5))
                rx = sock.recvfrom(timeout=1)
                print('motor set home: ' + rx[0].hex(), rx[1])
            for i in range(4):
                cur_pos[i] = 0
        
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
        if k == K_1:
            print('update fiducial p1!')
            fiducial_xyz[0][0] = cur_pos[0]
            fiducial_xyz[0][1] = cur_pos[1]
        if k == K_2:
            print('update fiducial p2!')
            fiducial_xyz[1][0] = cur_pos[0]
            fiducial_xyz[1][1] = cur_pos[1]
        
        if k == K_SHF_M or k == K_M:
            cur_cam = 255 if k == K_M else 0
            print('set cam...', cur_cam)
            sock.sendto(b'\x20'+struct.pack("<H", 0x0036) + struct.pack("<B", cur_cam), ('80:00:10', 0x5))
            rx = sock.recvfrom(timeout=1)
            print('set cam ret: ' + rx[0].hex(), rx[1])
        
        if k == K_P:
            cur_pump = int(not cur_pump)
            print('cur_pump:', cur_pump)
            set_pump(cur_pump)
        
        if k == K_SPACE:
            pause = not pause
            print('toggle pause, pause =', pause)
            continue
        
        print(f'goto: {cur_pos[0]:.3f} {cur_pos[1]:.3f} {cur_pos[2]:.3f} {cur_pos[3]:.3f}')
        print(f'delt: {cur_pos[0]-aux_pos[0]:.3f} {cur_pos[1]-aux_pos[1]:.3f} {cur_pos[2]-aux_pos[2]:.3f} {cur_pos[3]-aux_pos[3]:.3f}')
        goto_pos(cur_pos)


print('free run...')
pos_set()

coeff = fsolve(equations, (1, 1, 1, 1)) # ret: scale, angle, del_x, del_y
print('coefficient:', coeff)
print('equations(coeff):', equations(coeff))
print('pcb2xyz:', pcb2xyz(coeff, (-6.3, 4.75)))


def work_thread():
    global cur_comp, pause, redo, skip
    fast_to = None # e.g.: 'U12'
    print('show components...')
    for footprint in pos:
        cur_comp = footprint
        for comp_val in pos[footprint]:
            count = 0
            print(f'\n-> {footprint} -> {comp_val}, paused')
            if not fast_to:
                pause = True
            while pause:
                sleep(0.1)
            for comp in pos[footprint][comp_val]:
                count += 1
                while True:
                    redo = False
                    skip = False
                    print(f'--- {comp}, {count}/{len(pos[footprint][comp_val])}')
                    if comp[0] == fast_to:
                        fast_to = None
                    if fast_to:
                        break
                    p_x, p_y = pcb2xyz(coeff, (float(comp[3]), float(comp[4]) * -1))
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


_thread.start_new_thread(work_thread, ())
pos_set()

print('exit...')

