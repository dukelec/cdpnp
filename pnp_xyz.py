#!/usr/bin/env python3
# Software License Agreement (BSD License)
#
# Copyright (c) 2017, DUKELEC, Inc.
# All rights reserved.
#
# Author: Duke Fong <d@d-l.io>

import sys, os, _thread
import struct, re, math
from time import sleep

from cdnet.utils.log import *
from cdnet.dispatch import *

# 4mm / (50 * 512 (md: 7)) = ~ mm per micro step
# 360' / (50 * 512 (md: 7)) = ~' per micro step
DIV_MM2STEP = 0.00015625
DIV_DEG2STEP = 0.0140625

xyz = {
    'logger': None,
    'last_pos': None,
    'sock': None,
    'sock_dbg': None
}


def dbg_echo():
    while True:
        rx = xyz['sock_dbg'].recvfrom()
        #xyz['logger'].info('\x1b[0;37m  ' + re.sub(br'[^\x20-\x7e]',br'.', rx[0][5:-1]).decode() + '\x1b[0m')
        xyz['logger'].info('\x1b[0;37m  ' + re.sub(br'[^\x20-\x7e]',br'.', rx[0]).decode() + '\x1b[0m')


# for unicast only
def cd_reg_rw(dev_addr, reg_addr, write=None, read=0, timeout=0.8, retry=3):
    if write != None:
        tx_dat = b'\x20'+struct.pack("<H", reg_addr) + write
    else:
        tx_dat = b'\x00'+struct.pack("<H", reg_addr) + struct.pack("<B", read)
    for cnt in range(retry):
        xyz['sock'].clear()
        xyz['sock'].sendto(tx_dat, (dev_addr, 0x5))
        dat, src = xyz['sock'].recvfrom(timeout=timeout)
        if src:
            if src[0] == dev_addr and src[1] == 0x5:
                return dat
            xyz['logger'].warning(f'cd_reg_rw recv wrong src')
        else:
            xyz['logger'].warning(f'cd_reg_rw timeout')
    raise Exception('reg_rw retry error')
    #return None


def set_pump(val):
    pump = 2 if val != 0 else 1
    xyz['logger'].info(f'set pump... {pump}')
    rx = cd_reg_rw('80:00:11', 0x0036, struct.pack("<B", pump))
    xyz['logger'].info('set pump ret: ' + rx.hex())
    if pump == 1:
        sleep(0.5)
        pump = 0
        xyz['logger'].info(f'set pump... {pump}')
        rx = cd_reg_rw('80:00:11', 0x0036, struct.pack("<B", pump))
        xyz['logger'].info('set pump ret: ' + rx.hex())


def enable_motor():
    for i in range(5):
        xyz['logger'].info(f'motor enable: #{i+1}')
        rx = cd_reg_rw(f'80:00:0{i+1}', 0x0108, struct.pack("<B", 1))
        xyz['logger'].info('motor enable ret: ' + rx.hex())
        
        xyz['logger'].info(f'motor set accel #{i+1}')
        rx = cd_reg_rw(f'80:00:0{i+1}', 0x00c4, struct.pack("<I", 800000 if i != 4 else 20000))
        xyz['logger'].info('motor set ret: ' + rx.hex())
        
        xyz['logger'].info(f'motor set emergency accel #{i+1}')
        rx = cd_reg_rw(f'80:00:0{i+1}', 0x00c8, struct.pack("<I", 80000000))
        xyz['logger'].info('motor set ret: ' + rx.hex())
        
        xyz['logger'].info(f'motor set vref #{i+1}')
        rx = cd_reg_rw(f'80:00:0{i+1}', 0x00ae, struct.pack("<H", 600 if i != 4 else 300))
        xyz['logger'].info('motor set vref ret: ' + rx.hex())


def wait_stop():
    for i in range(5):
        while True:
            rx = cd_reg_rw(f'80:00:0{i+1}', 0x0109, read=1)
            if rx[0] == 0x80 and rx[1] == 0:
                break
            sleep(0.1)


def enable_force():
    rx = cd_reg_rw('80:00:04', 0x006c, struct.pack("<B", 1))
    xyz['logger'].info(f'enable force ret: {rx[0]:02x}')


def load_pos():
    pos = [0, 0, 0, 0]
    xyz['logger'].info(f'motor read pos')
    rx = cd_reg_rw('80:00:03', 0x00bc, read=4)
    pos[0] = struct.unpack("<i", rx[1:])[0] * DIV_MM2STEP
    rx = cd_reg_rw('80:00:01', 0x00bc, read=4)
    pos[1] = struct.unpack("<i", rx[1:])[0] * DIV_MM2STEP
    rx = cd_reg_rw('80:00:04', 0x00bc, read=4)
    pos[2] = struct.unpack("<i", rx[1:])[0] * DIV_MM2STEP * -1
    rx = cd_reg_rw('80:00:05', 0x00bc, read=4)
    pos[3] = struct.unpack("<i", rx[1:])[0] * DIV_DEG2STEP * -1
    return pos


def goto_pos(pos, wait=False, s_speed=260000):
    delta = [pos[0]-xyz['last_pos'][0], pos[1]-xyz['last_pos'][1], pos[2]-xyz['last_pos'][2]]
    xyz['last_pos'] = [pos[0], pos[1], pos[2], pos[3]]
    retry_cnt = 0
    done_flag = [0, 0, 0, 0, 0]
    m_vector = max(math.sqrt(math.pow(delta[0], 2) + math.pow(delta[1], 2) + math.pow(delta[2], 2)), 0.01)
    v_speed = [round(s_speed * abs(delta[0])/m_vector), round(s_speed * abs(delta[1])/m_vector), round(s_speed * abs(delta[2])/m_vector), round(s_speed / 5)]
    b_speed = [struct.pack("<i", v_speed[0]), struct.pack("<i", v_speed[1]), struct.pack("<i", v_speed[2]), struct.pack("<i", v_speed[3])]
    
    while True:
        xyz['sock'].clear()
        if not done_flag[2]:
            xyz['sock'].sendto(b'\x20'+struct.pack("<i", round(pos[0]/DIV_MM2STEP))+b_speed[0], ('80:00:03', 0x6))
        if (not done_flag[0]) or (not done_flag[1]):
            xyz['sock'].sendto(b'\x20'+struct.pack("<i", round(pos[1]/DIV_MM2STEP))+b_speed[1], ('80:00:e0', 0x6))
        if not done_flag[3]:
            xyz['sock'].sendto(b'\x20'+struct.pack("<i", round(pos[2]*-1/DIV_MM2STEP))+b_speed[2], ('80:00:04', 0x6))
        if not done_flag[4]:
            xyz['sock'].sendto(b'\x20'+struct.pack("<i", round(pos[3]*-1/DIV_DEG2STEP))+b_speed[3], ('80:00:05', 0x6))
        
        for i in range(5 - (done_flag[0] + done_flag[1] + done_flag[2] + done_flag[3] + done_flag[4])):
            dat, src = xyz['sock'].recvfrom(timeout=0.8)
            if src and src[0][:-1] == '80:00:0':
                done_flag[int(src[0][-1])-1] = 1
        if done_flag[0] and done_flag[1] and done_flag[2] and done_flag[3] and done_flag[4]:
            break
        xyz['logger'].warning(f'error: retry_cnt: {retry_cnt}, done_flag: f{done_flag}')
        retry_cnt += 1
        if retry_cnt > 3:
            xyz['logger'].error(f'error: set retry > 3, done_flag: f{done_flag}')
            raise Exception('goto_pos retry error')
    
    if not wait:
        return 0
    wait_stop()


def detect_origin():
    xyz['logger'].info(f'detecting origin, please wait...')
    goto_pos([2, 2, -2, 0], True, 100000)
    goto_pos([-1000, -1000, 1000, 0], True, 50000)
    for i in range(4):
        xyz['logger'].info(f'motor set origin: #{i+1}')
        rx = cd_reg_rw(f'80:00:0{i+1}', 0x00b1, struct.pack("<B", 1))
        xyz['logger'].info('motor set origin ret: ' + rx.hex())
    sleep(0.5)
    xyz['last_pos'] = load_pos()
    goto_pos([2, 2, -2, 0], True)


def xyz_init():
    xyz['logger'] = logging.getLogger('pnp_xyz')
    xyz['sock'] = CDNetSocket(('', 0xcdcd))
    xyz['sock_dbg'] = CDNetSocket(('', 9))
    _thread.start_new_thread(dbg_echo, ())
    xyz['last_pos'] = load_pos()
    
    all_enable = True
    for i in range(5):
        rx = cd_reg_rw(f'80:00:0{i+1}', 0x0108, read=1)
        xyz['logger'].info('motor check enable ret: ' + rx.hex())
        if rx[1] != 1:
            all_enable = False
    
    if not all_enable:
        enable_motor()
        detect_origin()

