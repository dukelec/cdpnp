#!/usr/bin/env python3

# This programs calculates the orientation of an object.
# The input is an image, and the output is an annotated image
# with the angle of otientation for each object (0 to 180 degrees)

import sys, os, _thread
import struct, queue, re
from time import sleep

from cdnet.utils.log import *
from cdnet.dispatch import *
 
import cv2 as cv
from math import atan2, cos, sin, sqrt, pi
import numpy as np

cv_dat = {
    'dev': 1,
    
    'cur': None,
    'img_queue': None,
    
    'detect': 'default',
    'local': True,  # show opencv window
    
    'sock_pic': None
}


def cv_get_pos(img):
    if not cv_dat['detect']:
        return
    
    # Convert image to grayscale
    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
     
    # Convert image to binary
    _, bw = cv.threshold(gray, 50, 255, cv.THRESH_BINARY | cv.THRESH_OTSU)
     
    # Find all the contours in the thresholded image
    contours, _ = cv.findContours(bw, cv.RETR_LIST, cv.CHAIN_APPROX_NONE)
    
    comps = []
    for i, c in enumerate(contours):
     
      # Calculate the area of each contour
      area = cv.contourArea(c)
     
      # Ignore contours that are too small or too large
      if area < 125 or 125000 < area:
        continue
     
      # cv.minAreaRect returns:
      # (center(x, y), (width, height), angle of rotation) = cv2.minAreaRect(c)
      rect = cv.minAreaRect(c)
      box = cv.boxPoints(rect)
      box = np.int0(box)
     
      # Retrieve the key parameters of the rotated bounding box
      center = (int(rect[0][0]),int(rect[0][1])) 
      width = int(rect[1][0])
      height = int(rect[1][1])
      angle = int(rect[2])
      
      if width < height:
        angle = 90 - angle
      else:
        angle = -angle
      
      if cv_dat['detect'] == 'limit_angle':
        if angle < -45:
            angle += 90
        elif angle > 45:
            angle -= 90
      
      height, width = img.shape[:2]
      x_center, y_center = int(width/2), int(height/2)
      l_center = abs(center[0] - x_center) + abs(center[1] - y_center)
      comps.append([center[0], center[1], angle, l_center])
      
      label = str(angle) + (' !' if cv_dat['detect'] == 'limit_angle' else '')
      cv.drawContours(img,[box],0,(0,0,255),1)
      cv.putText(img, label, (center[0]+14, center[1]), cv.FONT_HERSHEY_SIMPLEX, 0.4, (0,200,255), 1, cv.LINE_AA)
      cv.drawMarker(img, (center[0],center[1]), color=(0,255,255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=10)
    
    if len(comps):
        comps.sort(key = lambda e : e[3])
        cv.drawMarker(img, (comps[0][0],comps[0][1]), color=(0,0,255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=5)
        cv_dat['cur'] = comps[0]
    else:
        cv_dat['cur'] = None



def pic_rx():
    rx_dat = None
    dat_cnt = 0
    
    while True:
        rx = cv_dat['sock_pic'].recvfrom()
        #print('\x1b[0;37m  ' + re.sub(br'[^\x20-\x7e]',br'.', rx[0]).decode() + '\x1b[0m')
        
        hdr = rx[0][0]  # [5:4] FRAGMENT: 00: error, 01: first, 10: more, 11: last, [3:0]: cnt
        dat = rx[0][1:]
        
        if hdr == 0x50:     # first
            rx_dat = dat
            dat_cnt = 0
        
        elif (hdr & 0xf0) == 0x60: # more
            if dat_cnt == (hdr & 0xf):
                rx_dat += dat
            #else:
            #    print(f'pic, wrong cnt, local: {dat_cnt} != rx: {hdr & 0xf}, dat len: {len(dat)}')
        
        elif (hdr & 0xf0) == 0x70: # end
            if dat_cnt == (hdr & 0xf):
                #print('pic received!')
                inp = np.asarray(bytearray(rx_dat), dtype=np.uint8)
                img = cv.imdecode(inp, cv.IMREAD_COLOR)
                if cv_dat['dev'] == 1:
                    img = cv.rotate(img, cv.ROTATE_90_CLOCKWISE)
                if cv_dat['dev'] == 2:
                    img = cv.flip(img, 1)
                height, width = img.shape[:2]
                cv_get_pos(img)
                if cv_dat['dev'] != 2:
                    img = cv.drawMarker(img, (int(width/2),int(height/2)), color=(0,255,0), markerType=cv.MARKER_CROSS, thickness=1)
                if not cv_dat['img_queue'].full():
                    if not cv_dat['local']:
                        img = cv.imencode('.png', img)[1].tobytes()
                    cv_dat['img_queue'].put_nowait(img)

            #else:
            #    print(f'pic, wrong cnt at end, local: {dat_cnt} != rx: {hdr & 0xf}, dat len: {len(dat)}')
        
        #else:
        #    print(f'pic, receive err, local: {dat_cnt}, rx: {hdr & 0xf}, all len: {len(img_dat)}')
        
        dat_cnt += 1
        if dat_cnt == 0x10:
            dat_cnt = 0


def cv_window():
    while True:
        cur_pic = cv_dat['img_queue'].get()
        cv.imshow('image', cur_pic)
        cv.waitKey(10)

def pnp_cv_init(detect='default', local=True):
    cv_dat['detect'] = detect
    cv_dat['local'] = local
    cv_dat['img_queue'] = queue.Queue(10)
    cv_dat['sock_pic'] = CDNetSocket(('', 0x10))
    _thread.start_new_thread(pic_rx, ())
    if cv_dat['local']:
        _thread.start_new_thread(cv_window, ())

