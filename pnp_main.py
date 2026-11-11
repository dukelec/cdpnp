#!/usr/bin/env python3
# Software License Agreement (BSD License)
#
# Copyright (c) 2017, DUKELEC, Inc.
# All rights reserved.
#
# Author: Duke Fong <d@d-l.io>

"""CDPNP GUI tool

Args:
  --help    | -h        # this help message
  --verbose | -v        # debug level: verbose
  --debug   | -d        # debug level: debug
  --dev DEV             # serial port filter, default: the cdbus bridge (:574), None: no hardware
  --api-port API_PORT   # external api (for scripts and ai agents), default: 8901, 0: disable
"""

import sys, os, _thread
import struct
import asyncio
import math
import numpy as np
from cd_ws import CDWebSocket
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
dev_str = args.get("--dev", dft=":574")
api_port = int(args.get("--api-port", dft="8901"), 0)

if args.get("--help", "-h") != None:
    print(__doc__)
    exit()

if args.get("--verbose", "-v") != None:
    logger_init(logging.VERBOSE)
elif args.get("--debug", "-d") != None:
    logger_init(logging.DEBUG)
else:
    logger_init(logging.INFO)

logging.getLogger('websockets').setLevel(logging.WARNING)
logger = logging.getLogger(f'cdpnp')

if dev_str == ':574':
    if get_port('2E3C:574'):
        dev_str = '2E3C:574' # bridge hw v6
    elif get_port('0483:574'):
        dev_str = '0483:574' # bridge hw v5
    else:
        logger.error(f'cdbus bridge not found, serial ports:')
        dump_ports()
        exit()

dev = CDBusSerial(dev_str, 10000000) if dev_str != 'None' else None
if dev:
    CDNetIntf(dev, mac=0x00)
    xyz_init()

print('start...')


def collinear(p):
    l = np.linalg.eigvalsh(np.cov(p.T, bias=True)) # ascending
    return not l[0] >= l[1] * 0.0025


# skew: how far the X and Y motions are from 90 degrees (deg), the commanded position is
# C * square position with C = [[1, k/2], [k/2, 1]]
# 2 fiducials: rotation, scale and offset, on top of the skew of the machine
# 3 or more: least squares affine, which takes up the skew and what the PCB itself does
def pcb2xyz(pcb, cam, x, y, skew=0):
    n = min(len(pcb), len(cam))
    p, c = np.array(pcb[:n], dtype=float), np.array(cam[:n], dtype=float)
    if n >= 3 and not collinear(p):
        m = np.linalg.lstsq(np.c_[p, np.ones(n)], c, rcond=None)[0]
        ret = np.array([x, y, 1.0]) @ m
        a = math.atan2(m[0, 1] - m[1, 0], m[0, 0] + m[1, 1])
    else:
        k = math.radians(skew)
        C = np.array([[1, k / 2], [k / 2, 1]])
        w = np.linalg.solve(C, c[:2].T).T
        z = complex(*(w[1] - w[0])) / complex(*(p[1] - p[0]))
        t = complex(*w[0]) - z * complex(*p[0])
        q = z * complex(x, y) + t
        ret = C @ np.array([q.real, q.imag])
        a = np.angle(z)
    return float(ret[0]), float(ret[1]), math.degrees(math.atan2(math.sin(-a), math.cos(-a))) # limited-range angle


async def dev_service():
    sock = CDWebSocket(ws_ns, 'dev')
    while True:
        dat, src = await sock.recvfrom()
        logger.debug(f'dev ser: {dat}')
        try:
            await dev_handle(sock, dat, src)
        except Exception as err: # one bad request must not take the service down with it
            logger.error(f'dev ser: {dat.get("action") if isinstance(dat, dict) else dat}: {err!r}')
            await sock.sendto(f'err: dev: {err}', src)


async def dev_handle(sock, dat, src):
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
            rx = cd_reg_rw(f"00:00:2{cv_dat['dev']}", CAM_CAPTURE_CTRL, struct.pack("<B", 8 if dat['val'] else 0x80))
            logger.info('set cam ret: ' + rx.hex())
        await sock.sendto('succeeded', src)
    
    elif dat['action'] == 'set_camera_cfg':
        logger.info(f"set_camera_cfg dev: {dat['dev']}, detect: {dat['detect']}, light: {dat['light1']}_{dat['light2']}, expos: {dat['expos']}")
        cv_dat['dev'] = dat['dev']
        cv_dat['detect'] = dat['detect']
        cv_dat['expos'] = dat['expos']
        if dev:
            rx = cd_reg_rw(f"00:00:21", CAM_LED_EN, struct.pack("<b", 1 if dat['light1'] else 0))
            logger.info('set cam_light1 ret: ' + rx.hex())
            rx = cd_reg_rw(f"00:00:22", CAM_LED_EN, struct.pack("<b", 1 if dat['light2'] else 0))
            logger.info('set cam_light2 ret: ' + rx.hex())
            rx = cd_reg_rw(f"00:00:2{cv_dat['dev']}", CAM_EXPOSURE, struct.pack("<H", dat['expos']))
            logger.info('set exposure ret: ' + rx.hex())
        await sock.sendto('succeeded', src)
    
    elif dat['action'] == 'get_camera_cfg':
        logger.info('get_camera_cfg')
        rx0 = cd_reg_rw(f"00:00:2{cv_dat['dev']}", CAM_CAPTURE_STATE, read=1) if dev else bytes([0x00, 0x00])
        logger.info('get_camera_cfg ret: ' + rx0.hex())
        rx1 = cd_reg_rw(f"00:00:21", CAM_LED_EN, read=1) if dev else bytes([0x00, 0x00])
        logger.info('get_camera_light1 ret: ' + rx1.hex())
        rx2 = cd_reg_rw(f"00:00:22", CAM_LED_EN, read=1) if dev else bytes([0x00, 0x00])
        logger.info('get_camera_light2 ret: ' + rx2.hex())
        await sock.sendto({'enable': 1 if rx0[1] else 0, 'dev': cv_dat['dev'], 'detect': cv_dat['detect'], 'light1': rx1[1], 'light2': rx2[1]}, src)
    
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
        await sock.sendto(pcb2xyz(dat['pcb'], dat['cam'], dat['x'], dat['y'], dat.get('skew', 0)), src)
    
    elif dat['action'] == 'get_cv_cur':
        logger.info(f"get_cv_cur")
        await sock.sendto(cv_dat['cur'], src)
    
    elif dat['action'] == 'get_cv_comps': # every detection of the last frame, with the frame it belongs to
        logger.info(f"get_cv_comps")
        last = cv_dat['last']
        await sock.sendto({'seq': last['seq'], 'ts': last['ts'], 'dev': last['dev'], 'detect': last['detect'],
                           'cur': last['cur'], 'comps': last['comps']} if last else None, src)
    
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
    if api_port:
        from api_serve import api_init
        api_init(dev is not None, port=api_port)
    #csa['async_loop'].create_task(open_brower())
    logger.info('Please open url: http://localhost:8900')
    loop.run_forever()

if dev:
    _thread.start_new_thread(start_loop, ())
    pnp_cv_start() # make cv gui in foreground thread (for macos)
else:
    start_loop()

