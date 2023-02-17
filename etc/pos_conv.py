#!/usr/bin/env python3
# Software License Agreement (BSD License)
#
# Copyright (c) 2017, DUKELEC, Inc.
# All rights reserved.
#
# Author: Duke Fong <d@d-l.io>

"""CDPNP csv position file convert tool

Usage: ./pos_conv -i in.csv -o out.csv [-x] [-y]
"""

import os, sys, csv
sys.path.append(os.path.join(os.path.dirname(__file__), '../pycdnet'))
from cdnet.utils.cd_args import CdArgs

args = CdArgs()
in_file = args.get("-i")
out_file = args.get("-o")
invert_x = args.get("-x") != None
invert_y = args.get("-y") != None

if args.get("--help", "-h") != None or in_file == None or out_file == None:
    print(__doc__)
    exit()

if invert_x == invert_y and not invert_x:
    print('At least one argment should apply: -x or -y')
    exit()

print(f"invert_x: {invert_x}, invert_y: {invert_y}\n")

pos = []
with open(in_file) as csvfile:
    reader = csv.reader(csvfile)
    for row in reader:
        pos.append(row)


for i in range(len(pos)):
    try:
        pos[i][5] = float(pos[i][5])
        # use removesuffix instead on python3.9+
        pos[i][3] = pos[i][3][:-2] if pos[i][3].lower().endswith("mm") else pos[i][3]
        pos[i][4] = pos[i][4][:-2] if pos[i][4].lower().endswith("mm") else pos[i][4]
        pos[i][3] = float(pos[i][3])
        pos[i][4] = float(pos[i][4])
        if invert_x:
            pos[i][3] = pos[i][3] * -1
        if invert_y:
            pos[i][4] = pos[i][4] * -1
        print(pos[i])
    except:
        print(pos[i], "                <------ skip")


with open(out_file, 'w') as csvfile:
    csvwriter = csv.writer(csvfile)
    csvwriter.writerows(pos)

