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

# registers of the module firmware in tools/firmware (the configs in tools/cdbus_gui_configs),
# tools/fw_cfg_update.py brings the modules to it
# cdstep v3:
STEP_TP_ACCEL_EMG   = 0x015c    # u32
STEP_TP_STATE       = 0x017f    # i8, trap planner: -1: disable, 0: idle, 1: planning
STEP_REF_VOLT       = 0x0290    # u16, mV
STEP_LIM_EN         = 0x0293    # bool
STEP_SET_HOME       = 0x03fe    # write 0x80 to set home position
STEP_STATE          = 0x0400    # 0: disable drive, 5: enable (position with trap planner)
STEP_MEAS_POS       = 0x0494    # i32
STEPZ_FORCE_TRIG    = 0x0500    # cdstep-z: arm the force trigger for the next move
# cdcam v2:
CAM_CAPTURE_CTRL    = 0x005f    # 0x80: cancel, 1: one-shot, 8: continuous
CAM_CAPTURE_STATE   = 0x0060    # 0: idle, 1: one-shot, 8: continuous
CAM_EXPOSURE        = 0x0044
CAM_LED_EN          = 0x0069

FW_DEVS = ['00:00:01', '00:00:02', '00:00:03', '00:00:04', '00:00:05', '00:00:11', '00:00:21', '00:00:22']

# 4mm / (50 * 512 (md: 7)) = ~ mm per micro step
# 360' / (50 * 512 (md: 7)) = ~' per micro step
DIV_MM2STEP = 0.00015625
DIV_DEG2STEP = 0.0140625

xyz = {
    'logger': None,
    'last_pos': None,
    'old_pos': None,
    'sock': None,
    'sock_dbg': None,
    'pump_hw_ver': 'v1'
}


def dbg_echo():
    while True:
        rx = xyz['sock_dbg'].recvfrom()
        xyz['logger'].info(f'#{rx[1][0][-2:]}  \x1b[0;37m' + rx[0][1:-1].decode() + '\x1b[0m')


# for unicast only
def cd_info_rd(dev_addr, timeout=0.8, retry=3):
    for cnt in range(retry):
        xyz['sock'].clear()
        xyz['sock'].sendto(b'', (dev_addr, 0x1))
        dat, src = xyz['sock'].recvfrom(timeout=timeout)
        if src:
            if src[0] == dev_addr and src[1] == 0x1:
                return dat
            xyz['logger'].warning(f'cd_info_rd recv wrong src')
        else:
            xyz['logger'].warning(f'cd_info_rd timeout, dev: {dev_addr}')
    raise Exception('info_rd retry error')
    #return None

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
            xyz['logger'].warning(f'cd_reg_rw timeout, dev: {dev_addr}')
    raise Exception('reg_rw retry error')
    #return None


# hw_v1: 0: off, 1: valve on, 2: pump on
# hw_v2: target pressure
def set_pump(val):
    xyz['logger'].info(f'set pump... {val}')
    if xyz['pump_hw_ver'] == 'v1':
        rx = cd_reg_rw('00:00:11', 0x0036, struct.pack("<B", val))
    else:
        rx = cd_reg_rw('00:00:11', 0x00f8, struct.pack("<f", val))
    xyz['logger'].info('set pump ret: ' + rx.hex())

def get_pump_pressure():
    xyz['logger'].info(f'get_pump_pressure...')
    rx = cd_reg_rw('00:00:11', 0x0124, read=4)
    pressure = struct.unpack("<f", rx[1:])[0]
    xyz['logger'].info(f'get_pump_pressure ret: {pressure}')
    return pressure


def enable_motor():
    for i in range(5):
        xyz['logger'].info(f'motor enable: #{i+1}')
        rx = cd_reg_rw(f'00:00:0{i+1}', STEP_STATE, struct.pack("<B", 5))
        xyz['logger'].info('motor enable ret: ' + rx.hex())
        
        xyz['logger'].info(f'motor set emergency accel #{i+1}')
        rx = cd_reg_rw(f'00:00:0{i+1}', STEP_TP_ACCEL_EMG, struct.pack("<I", 80000000 if i != 4 else 2000000))
        xyz['logger'].info('motor set ret: ' + rx.hex())
        
        xyz['logger'].info(f'motor set vref #{i+1}')
        rx = cd_reg_rw(f'00:00:0{i+1}', STEP_REF_VOLT, struct.pack("<H", 800 if i != 4 else 450))
        xyz['logger'].info('motor set vref ret: ' + rx.hex())


def load_pos(mask=0xf):
    pos = [None, None, None, None]
    #xyz['logger'].info(f'motor read pos')
    retry_cnt = 0
    while True:
        xyz['sock'].clear()
        tx_num = 0
        rx_num = 0
        if mask & 1:
            xyz['sock'].sendto(b'\x00'+struct.pack("<H", STEP_MEAS_POS) + struct.pack("<B", 4), ('00:00:03', 0x5))
            tx_num += 1
        if mask & 2:
            xyz['sock'].sendto(b'\x00'+struct.pack("<H", STEP_MEAS_POS) + struct.pack("<B", 4), ('00:00:01', 0x5))
            tx_num += 1
        if mask & 4:
            xyz['sock'].sendto(b'\x00'+struct.pack("<H", STEP_MEAS_POS) + struct.pack("<B", 4), ('00:00:04', 0x5))
            tx_num += 1
        if mask & 8:
            xyz['sock'].sendto(b'\x00'+struct.pack("<H", STEP_MEAS_POS) + struct.pack("<B", 4), ('00:00:05', 0x5))
            tx_num += 1
        
        for i in range(tx_num):
            dat, src = xyz['sock'].recvfrom(timeout=0.8)
            if src and src[1] == 0x5:
                if src[0] == '00:00:03':
                    pos[0] = struct.unpack("<i", dat[1:])[0] * DIV_MM2STEP
                    rx_num += 1
                elif src[0] == '00:00:01':
                    pos[1] = struct.unpack("<i", dat[1:])[0] * DIV_MM2STEP
                    rx_num += 1
                elif src[0] == '00:00:04':
                    pos[2] = struct.unpack("<i", dat[1:])[0] * DIV_MM2STEP * -1
                    rx_num += 1
                elif src[0] == '00:00:05':
                    pos[3] = struct.unpack("<i", dat[1:])[0] * DIV_DEG2STEP
                    rx_num += 1
        if rx_num == tx_num:
            break
        xyz['logger'].warning(f'error: retry_cnt: {retry_cnt}, pos: f{pos}')
        retry_cnt += 1
        if retry_cnt > 3:
            xyz['logger'].error(f'error: set retry > 3, pos: f{pos}')
            raise Exception('load_pos retry error')
    return pos


def wait_stop():
    for i in range(5):
        while True:
            rx = cd_reg_rw(f'00:00:0{i+1}', STEP_TP_STATE, read=1)
            if rx[0] == 0x00 and rx[1] != 1: # idle, or -1: drive disabled
                break
            sleep(0.1)


def wait_finish(axis, wait):
    old = xyz['old_pos'][axis]
    last = xyz['last_pos'][axis]
    xyz['logger'].debug(f'wait_finish: old: {xyz["old_pos"]}, last: {xyz["last_pos"]}, axis: {axis}')
    dist = abs(last - old)
    while True:
        cur = load_pos(1 << axis)[axis]
        finish = abs(cur - old)
        if dist == 0 or finish * 100 / dist >= wait:
            break
        sleep(0.02)


def enable_force():
    rx = cd_reg_rw('00:00:04', STEPZ_FORCE_TRIG, struct.pack("<B", 1))
    xyz['logger'].info(f'enable force ret: {rx[0]:02x}')


def cal_accel(v):
    # in 600000: out 1600000, in 60000: out 160000
    if v <= 60000:
        return 160000
    return round(v / 600000 * 1600000)


def goto_pos(pos, wait=0, s_speed=260000):
    xyz['old_pos'] = load_pos()
    delta = [pos[0]-xyz['old_pos'][0], pos[1]-xyz['old_pos'][1], pos[2]-xyz['old_pos'][2], pos[3]-xyz['old_pos'][3]]
    xyz['last_pos'] = [pos[0], pos[1], pos[2], pos[3]]
    xyz['logger'].debug(f"goto_pos: cur: {xyz['old_pos']}")
    xyz['logger'].debug(f"goto_pos: tgt: {xyz['last_pos']}")
    xyz['logger'].debug(f"goto_pos: dlt: {delta}")
    retry_cnt = 0
    done_flag = [0, 0, 0, 0, 0]
    dlt_max = max(abs(delta[0]), abs(delta[1]), abs(delta[2]), 0.01)
    # 360' / 4mm = 90, use 85 instead to avoid R axis waste time
    v_speed = [s_speed * abs(delta[0])/dlt_max, s_speed * abs(delta[1])/dlt_max, s_speed * abs(delta[2])/dlt_max, s_speed * abs(delta[3]/85)/dlt_max]
    xyz['logger'].debug(f"goto_pos: v_speed: {v_speed}, dlt_max: {dlt_max}")
    v_speed = [max(v_speed[0], 2000), max(v_speed[1], 2000), max(v_speed[2], 2000), min(s_speed/45, max(v_speed[3], 500))] # avoid zero speed
    xyz['logger'].debug(f"goto_pos: v_speed: {v_speed}")
    b_speed = [struct.pack("<i", round(v_speed[0])), struct.pack("<i", round(v_speed[1])), struct.pack("<i", round(v_speed[2])), struct.pack("<i", round(v_speed[3]))]
    accel = [cal_accel(v_speed[0]), cal_accel(v_speed[1]), cal_accel(v_speed[2]), cal_accel(v_speed[3]*85)/85]
    b_accel = [struct.pack("<i", round(accel[0])), struct.pack("<i", round(accel[1])), struct.pack("<i", round(accel[2])), struct.pack("<i", round(accel[3]))]
    while True:
        xyz['sock'].clear()
        if not done_flag[2]:
            xyz['sock'].sendto(struct.pack("<i", round(pos[0]/DIV_MM2STEP))+b_speed[0]+b_accel[0], ('00:00:03', 0x6))
        if (not done_flag[0]) or (not done_flag[1]):
            xyz['sock'].sendto(struct.pack("<i", round(pos[1]/DIV_MM2STEP))+b_speed[1]+b_accel[1], ('00:00:e0', 0x6))
        if not done_flag[3]:
            xyz['sock'].sendto(struct.pack("<i", round(pos[2]*-1/DIV_MM2STEP))+b_speed[2]+b_accel[2], ('00:00:04', 0x6))
        if not done_flag[4]:
            xyz['sock'].sendto(struct.pack("<i", round(pos[3]/DIV_DEG2STEP))+b_speed[3]+b_accel[3], ('00:00:05', 0x6))
        
        for i in range(5 - (done_flag[0] + done_flag[1] + done_flag[2] + done_flag[3] + done_flag[4])):
            dat, src = xyz['sock'].recvfrom(timeout=0.8)
            if src and src[0][:-1] == '00:00:0':
                done_flag[int(src[0][-1])-1] = 1
        if done_flag[0] and done_flag[1] and done_flag[2] and done_flag[3] and done_flag[4]:
            break
        xyz['logger'].warning(f'error: retry_cnt: {retry_cnt}, done_flag: f{done_flag}')
        retry_cnt += 1
        if retry_cnt > 3:
            xyz['logger'].error(f'error: set retry > 3, done_flag: f{done_flag}')
            raise Exception('goto_pos retry error')
    
    if wait <= 0:
        return 0
    elif wait >= 100:
        wait_stop()
    else:
        if dlt_max == abs(delta[0]):
            wait_finish(0, wait)
        elif dlt_max == abs(delta[1]):
            wait_finish(1, wait)
        elif dlt_max == abs(delta[2]):
            wait_finish(2, wait)
        elif dlt_max == 0.01:
            wait_finish(3, wait)


def detect_origin():
    # detect z axis
    xyz['logger'].info(f'detecting z origin, please wait...')
    goto_pos([0, 0, -1, 0], 100, 100000)
    goto_pos([0, 0, 110, 0], 100, 50000)
    for i in range(4):
        xyz['logger'].info(f'motor set origin: #{i+1}')
        rx = cd_reg_rw(f'00:00:0{i+1}', STEP_SET_HOME, struct.pack("<B", 0x80)) # set origin
        xyz['logger'].info('motor set origin ret: ' + rx.hex())
    sleep(0.5)
    xyz['last_pos'] = load_pos()
    
    # detect all axis
    xyz['logger'].info(f'detecting all origin, please wait...')
    goto_pos([1, 1, -1, 30], 100, 100000)
    goto_pos([-315, -265, 110, -375], 100, 50000)
    for i in range(5):
        xyz['logger'].info(f'motor set origin: #{i+1}')
        rx = cd_reg_rw(f'00:00:0{i+1}', STEP_SET_HOME, struct.pack("<B", 0x80))
        xyz['logger'].info('motor set origin ret: ' + rx.hex())
    
    xyz['logger'].info(f'motor disable limit switch: #5')
    rx = cd_reg_rw(f'00:00:05', STEP_LIM_EN, struct.pack("<B", 0))
    xyz['logger'].info('motor disable limit switch ret: ' + rx.hex())
    sleep(0.5)
    xyz['last_pos'] = load_pos()
    goto_pos([2, 2, -2, 7.2*17], 100) # 360/50=7.2, 7.2*17=122.4
    
    xyz['logger'].info(f'motor set origin: #5')
    rx = cd_reg_rw(f'00:00:05', STEP_SET_HOME, struct.pack("<B", 0x80))
    xyz['logger'].info('motor set origin ret: ' + rx.hex())
    sleep(0.5)
    xyz['last_pos'] = load_pos()


def check_fw():
    """old module firmware (its SW is a git hash, the new ones vX.Y) has other register addresses:
    refuse to drive it"""
    old = []
    for addr in FW_DEVS:
        try:
            info = cd_info_rd(addr).decode(errors='replace')
        except Exception:
            info = 'no reply: cdnet v1 firmware, or not connected'
        xyz['logger'].info(f'{addr}: {info}')
        m = re.search(r'SW:\s*([^\s;,]+)', info)
        if '(bl)' in info or not m or not re.fullmatch(r'v\d+\.\d+', m[1]):
            old.append(f'{addr} ({info})')
    if old:
        for o in old:
            xyz['logger'].error(f'module firmware not up to date: {o}')
        xyz['logger'].error('update the modules first: python3 tools/fw_cfg_update.py')
        raise Exception('module firmware not up to date')


def xyz_init():
    xyz['logger'] = logging.getLogger('pnp_xyz')
    xyz['sock'] = CDNetSocket(('', 0x40)) # bit[4:3] should be zero for qxchg
    xyz['sock_dbg'] = CDNetSocket(('', 9))
    _thread.start_new_thread(dbg_echo, ())
    check_fw()
    
    rx = cd_reg_rw(f"00:00:21", CAM_CAPTURE_CTRL, struct.pack("<B", 0x80))
    xyz['logger'].info('stop cam1 ret: ' + rx.hex())
    rx = cd_reg_rw(f"00:00:22", CAM_CAPTURE_CTRL, struct.pack("<B", 0x80))
    xyz['logger'].info('stop cam2 ret: ' + rx.hex())
    
    xyz['last_pos'] = load_pos()
    
    all_enable = True
    for i in range(5):
        rx = cd_reg_rw(f'00:00:0{i+1}', STEP_STATE, read=1)
        xyz['logger'].info('motor check enable ret: ' + rx.hex())
        if rx[1] != 5:
            all_enable = False
    
    enable_motor()
    if not all_enable:
        detect_origin()
    
    xyz['logger'].info(f'check pump hw version...')
    rx = cd_info_rd('00:00:11').decode()
    xyz['logger'].info(f'check pump hw version ret: {rx}')
    # the pump type rather than its hw version: v2: pressure control, HW: v2 (otp never written) or v2.1 and above;
    # v1: valve / pump on and off, any other HW (v1, v2.0, err) or none (the old builds)
    m = re.search(r'HW:\s*v(\d+)(?:\.(\d+))?', rx)
    xyz['pump_hw_ver'] = 'v2' if m and (int(m[1]), int(m[2] or 1)) >= (2, 1) else 'v1'
    xyz['logger'].info(f'pump hw version: {xyz["pump_hw_ver"]}')

