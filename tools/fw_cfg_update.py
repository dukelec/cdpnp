#!/usr/bin/env python3
# Software License Agreement (MIT License)
#
# Copyright (c) 2023, DUKELEC, Inc.
# All rights reserved.
#
# Author: Duke Fong <d@d-l.io>

"""CDPNP fw update

"""

import os, sys, subprocess
from time import sleep
from os.path import join as pjoin

#cdbus_gui = '../../cdbus_gui'
cdbus_gui = pjoin('..', '..', 'cdbus_gui')

last_list = {
    '80:00:01': ['772b910', 'cdstep_v3_772b910.hex',    'cdstep-v6.json', 'cdstep_01.mpk'],
    '80:00:02': ['772b910', 'cdstep_v3_772b910.hex',    'cdstep-v6.json', 'cdstep_02.mpk'],
    '80:00:03': ['772b910', 'cdstep_v3_772b910.hex',    'cdstep-v6.json', 'cdstep_03.mpk'],
    '80:00:04': ['a49d731', 'cdstep_z_v3_a49d731.hex',  'cdstep-v6.json', 'cdstep_04.mpk'],
    '80:00:05': ['5e0418f', 'cdstep_r_v3_5e0418f.hex',  'cdstep-v6.json', 'cdstep_05.mpk'],

    '80:00:11': ['0b11b45', 'cdpump_v2_0b11b45.hex',    'cdpump-v6.json', 'cdpump_v2_11.mpk'],
   #'80:00:11': ['67edf93', 'cdpump_v1_67edf93.hex',    'cdpump-v5.json', 'cdpump_11.mpk'],

    '80:00:21': ['09c0b67', 'cdcam_v2_v3_09c0b67.hex',  'cdcam-v3.json', 'cdcam_21.mpk'],
   #'80:00:22': ['09c0b67', 'cdcam_v2_v3_09c0b67.hex',  'cdcam-v3.json', 'cdcam_22.mpk'],

   #'80:00:21': ['cea35ea', 'cdcam_v1_cea35ea.hex',    'cdcam-v3.json', 'cdcam_21.mpk'],
    '80:00:22': ['cea35ea', 'cdcam_v1_cea35ea.hex',    'cdcam-v3.json', 'cdcam_22.mpk'],
}


def invoke_cmd_r(cmd):
    print('$', cmd)
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(f'ret: {p.returncode}')
    print(p.stdout.decode() + p.stderr.decode())
    return (p.returncode, p.stdout.decode())

def invoke_cmd(cmd):
    print('$', cmd)
    p = subprocess.run(cmd, shell=True)
    print(f'ret: {p.returncode}')
    return p.returncode


for k in last_list:
    print(f'\n--------------------------------------------------------')
    print(f'Dev: {k}\n')
    t_ver = last_list[k][0]
    t_hex = last_list[k][1]
    t_json = last_list[k][2]
    t_mpk = last_list[k][3]
    cdg_cmd_path = 'python ' + pjoin(cdbus_gui, 'tools', 'cdg_cmd.py') + ' --tty 0483:5740'
    cdg_iap_path = 'python ' + pjoin(cdbus_gui, 'tools', 'cdg_iap.py') + ' --tty 0483:5740'
    t_json_path = pjoin(cdbus_gui, 'configs', t_json)
    t_hex_path = pjoin('firmware', t_hex)
    t_mpk_path = pjoin('cdbus_gui_configs', t_mpk)

    ret, info = invoke_cmd_r(f'{cdg_cmd_path} --dev {k} --cfg {t_json_path}')
    if ret != 0:
        exit(-1)
    c_ver = info.split('SW: ')[1].strip()
    print(f'current version: {c_ver}, target version: {t_ver}')
    if c_ver != t_ver:
        yn = input('Upgrade FW, Y or N?  (default N) ')
        if 'y' in yn.lower():
            print('upgrading............')
            ret = invoke_cmd(f'{cdg_iap_path} --dev {k} --cfg {t_json_path} --in-file {t_hex_path}')
            if ret != 0:
                exit(-1)
            sleep(2)
            print('\n')
        else:
            print('skip\n')
    else:
        print(f'already last version\n')

    ret = invoke_cmd(f'{cdg_cmd_path} --dev {k} --cfg {t_json_path} --import {t_mpk_path}')
    if ret != 0:
        exit(-1)
    yn = input('Save config to flash, Y or N? (default N) ')
    if 'y' in yn.lower():
        ret = invoke_cmd(f'{cdg_cmd_path} --dev {k} --cfg {t_json_path} --reg save_conf --val 1')
        if ret != 0:
            exit(-1)
    else:
        print('skip')

print('\nAll done.')

