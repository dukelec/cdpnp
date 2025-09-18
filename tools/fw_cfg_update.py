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

dev_str = '2E3C:5740' # bridge hw v6
#dev_str = '0483:5740' # bridge hw v5

last_list = {
    '00:00:01': ['81dc157', 'cdstep_v3_81dc157.hex',    'cdstep-v6.json', 'cdstep_01.mpk'],
    '00:00:02': ['81dc157', 'cdstep_v3_81dc157.hex',    'cdstep-v6.json', 'cdstep_02.mpk'],
    '00:00:03': ['81dc157', 'cdstep_v3_81dc157.hex',    'cdstep-v6.json', 'cdstep_03.mpk'],
    '00:00:04': ['f3cb10d', 'cdstep_z_v3_f3cb10d.hex',  'cdstep-v6.json', 'cdstep_04.mpk'],
    '00:00:05': ['38ca679', 'cdstep_r_v3_38ca679.hex',  'cdstep-v6.json', 'cdstep_05.mpk'],

    '00:00:11': ['1a47f00', 'cdpump_v2_1a47f00.hex',    'cdpump-v6.json', 'cdpump_v2_11.mpk'],
   #'00:00:11': ['545593d', 'cdpump_v1_545593d.hex',    'cdpump-v5.json', 'cdpump_11.mpk'],

    '00:00:21': ['5561abc', 'cdcam_v2_v3_5561abc.hex',  'cdcam-v3.json', 'cdcam_21.mpk'],
   #'00:00:21': ['d9529f5', 'cdcam_v1_d9529f5.hex',     'cdcam-v3.json', 'cdcam_21.mpk'],

    '00:00:22': ['d9529f5', 'cdcam_v1_d9529f5.hex',     'cdcam-v3.json', 'cdcam_22.mpk'],
   #'00:00:22': ['5561abc', 'cdcam_v2_v3_5561abc.hex',  'cdcam-v3.json', 'cdcam_22.mpk'],
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
    cdg_cmd_path = 'python ' + pjoin(cdbus_gui, 'tools', 'cdg_cmd.py') + f' --tty {dev_str} --baud 10000000'
    cdg_iap_path = 'python ' + pjoin(cdbus_gui, 'tools', 'cdg_iap.py') + f' --tty {dev_str} --baud 10000000'
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

