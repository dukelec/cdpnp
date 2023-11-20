#!/usr/bin/env python3
# Software License Agreement (MIT License)
#
# Copyright (c) 2023, DUKELEC, Inc.
# All rights reserved.
#
# Author: Duke Fong <d@d-l.io>

"""CDPNP csv format converter

convert AD csv to CDPNP format:
  ./csv_conv_ad.py IN.csv [ENCODING]
"""

import os, sys
import csv

csv_list = []
encoding = "utf-8"

if len(sys.argv) < 2:
    print(__doc__)
if len(sys.argv) >= 3:
    encoding = sys.argv[2]

in_file = sys.argv[1]
out_prefix = os.path.splitext(in_file)[0] + '_cdpnp'
print(f'input file: {in_file}, out file prefix: {out_prefix}, encoding: {encoding}')

# remove top comments of csv file
with open(in_file, 'r', encoding=encoding, newline='') as csvfile:
    reader = csv.reader(csvfile, delimiter=',', quotechar='"')
    for row in reader:
        if len(row) <= 1:
            continue
        csv_list.append(','.join(row))

top_list = []
bottom_list = []

reader = csv.DictReader(csv_list, delimiter=',', quotechar='"')
for row in reader:
    print(row)
    if 'Center-X(mm)' in row:
        row['Center-X(mm)'] = float(row['Center-X(mm)'].rstrip('mm')) # removesuffix is better than rstrip
        row['Center-Y(mm)'] = float(row['Center-Y(mm)'].rstrip('mm'))
    elif 'Center-X(mil)' in row:
        row['Center-X(mm)'] = round(float(row['Center-X(mil)'].rstrip('mil')) * 0.0254, 6)
        row['Center-Y(mm)'] = round(float(row['Center-Y(mil)'].rstrip('mil')) * 0.0254, 6)
    if 'Rotation' in row:
        row['Rotation'] = float(row['Rotation'])
    
    if row['Layer'] == 'TopLayer':
        top_list.append({
            'Designator': row['Designator'],
            'Comment': row['Comment'],
            'Footprint': row['Footprint'],
            'Center-X(mm)': row['Center-X(mm)'],
            'Center-Y(mm)': row['Center-Y(mm)'],
            'Rotation': row['Rotation'],
            'Layer': row['Layer']})
    else:
        bottom_list.append({
            'Designator': row['Designator'],
            'Comment': row['Comment'],
            'Footprint': row['Footprint'],
            'Center-X(mm)': row['Center-X(mm)'] * -1,
            'Center-Y(mm)': row['Center-Y(mm)'],
            'Rotation': row['Rotation'],
            'Layer': row['Layer']})

if len(top_list):
    with open(f'{out_prefix}_top.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, top_list[0].keys(), delimiter=',', quotechar='"')
        writer.writeheader()
        writer.writerows(top_list)

if len(bottom_list):
    with open(f'{out_prefix}_bottom.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, bottom_list[0].keys(), delimiter=',', quotechar='"')
        writer.writeheader()
        writer.writerows(bottom_list)

