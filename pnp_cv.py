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
from pathlib import Path

cur_path = Path(__file__).parent.absolute()

cv_dat = {
    'dev': 1,

    'cur': None,
    'img_queue': None,

    'detect': 'default',
    'local': True,  # show opencv window

    'bg_img': None, # background image
    'bg_capture': False,
    
    'nozzle_thresh': 199,
    'debug': False,

    'sock_pic': None
}


def cv_get_pos(img):
    if not cv_dat['detect']:
        return img

    # Convert image to grayscale
    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)

    # Closing small gaps
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (7, 7))
    gray = cv.morphologyEx(gray, cv.MORPH_OPEN, kernel)

    # Convert image to binary
    _, bw = cv.threshold(gray, 125, 255, cv.THRESH_BINARY)
    #cv.imwrite(f'{cur_path}/tmp/gray.png', gray) # for debug
    #cv.imwrite(f'{cur_path}/tmp/bw.png', bw)

    # Find all the contours in the thresholded image
    contours, hierarchy = cv.findContours(bw, cv.RETR_TREE, cv.CHAIN_APPROX_NONE)

    comps = []
    for i, c in enumerate(contours):

        # Calculate the area of each contour
        area = cv.contourArea(c)

        # Ignore contours that are too small or too large
        if cv_dat['detect'][0:4] == "pld_":
            if area < 42*42 or 57*57 < area:
                continue
        else:
            if area < 11*11 or 580*580 < area:
                continue
        if hierarchy[0][i][2] != -1:        # skip if child exist
            continue

        # cv.minAreaRect returns:
        # (center(x, y), (width, height), angle of rotation) = cv2.minAreaRect(c)
        rect = cv.minAreaRect(c)
        box = cv.boxPoints(rect)
        box = np.int0(np.around(box))

        # Retrieve the key parameters of the rotated bounding box
        center_f = (rect[0][0], rect[0][1])
        center = (round(rect[0][0]),round(rect[0][1]))
        height = round(rect[1][0])
        width = round(rect[1][1])
        angle = rect[2]
        cam_height, cam_width = img.shape[:2]
        if width == cam_width - 1 and height == cam_height - 1:
            continue

        if width > height:
            angle = 90 - angle
        else:
            angle = -angle

        if cv_dat['detect'] == 'limit_angle':
            if angle < -45:
                angle += 90
            elif angle > 45:
                 angle -= 90
        angle = round(angle, 1)

        x_center, y_center = round(cam_width/2), round(cam_height/2)
        l_center = abs(center[0] - x_center) + abs(center[1] - y_center)
        comps.append([center_f[0], center_f[1], angle, l_center])

        label = str(angle) + (' !' if cv_dat['detect'] == 'limit_angle' else '')
        cv.drawContours(img,[box],0,(0,0,255),1)
        if cv_dat['detect'][0:4] != "pld_":
            cv.putText(img, label, (center[0]+14, center[1]), cv.FONT_HERSHEY_SIMPLEX, 0.4, (0,200,255), 1, cv.LINE_AA)
        cv.drawMarker(img, (center[0],center[1]), color=(0,255,255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=10)

    if len(comps):
        if cv_dat['detect'] == "pld_first":
            comps.sort(key = lambda e : e[1])
        elif cv_dat['detect'] == "pld_last":
            comps.sort(key = lambda e : -e[1])
        else:
            comps.sort(key = lambda e : e[3])
        cv.drawMarker(img, (round(comps[0][0]),round(comps[0][1])), color=(0,0,255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=5)
        cv_dat['cur'] = comps[0]
    else:
        cv_dat['cur'] = None
    return img


def cv_get_circle(img):
    if not cv_dat['detect']:
        return img

    # Convert image to grayscale
    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
    gray = cv.medianBlur(gray, 3)

    # Closing small gaps
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (7, 7))
    gray = cv.morphologyEx(gray, cv.MORPH_OPEN, kernel)

    # Convert image to binary
    _, bw = cv.threshold(gray, cv_dat['nozzle_thresh'], 255, cv.THRESH_BINARY)
    #cv.imwrite(f'{cur_path}/tmp/gray.png', gray) # for debug
    #cv.imwrite(f'{cur_path}/tmp/bw.png', bw)

    if cv_dat['debug']:
        img = bw

    # Find all the contours in the thresholded image
    contours, hierarchy = cv.findContours(bw, cv.RETR_TREE, cv.CHAIN_APPROX_NONE)
    comps = []

    for i in range(len(contours)):
        cnt = contours[i]
        center_f, radius = cv.minEnclosingCircle(cnt)
        center = (round(center_f[0]), round(center_f[1]))
        radius = round(radius, 1)

        filter_radius = float(cv_dat['detect'].split("_")[2]) / 2
        filter_delta = float(cv_dat['detect'].split("_")[3]) / 2
        if radius < filter_radius - filter_delta or filter_radius + filter_delta < radius: # filtering by nozzle hole size
            continue
        if bw[center[1], center[0]] != 0:   # skip white
            continue
        if hierarchy[0][i][2] != -1:        # skip if child exist
            continue

        label = 'd' + str(radius*2)
        cv.putText(img, label, (center[0]+14, center[1]), cv.FONT_HERSHEY_SIMPLEX, 0.4, (0,200,255), 1, cv.LINE_AA)
        cv.drawMarker(img, center, color=(0,255,255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=10)
        cv.circle(img, center, round(radius), (0,0,255), 1)
        #print(center, radius, bw[center[1], center[0]])

        cam_height, cam_width = img.shape[:2]
        x_center, y_center = round(cam_width/2), round(cam_height/2)
        l_center = abs(center[0] - x_center) + abs(center[1] - y_center)
        comps.append([center_f[0], center_f[1], 0, l_center])

    if len(comps):
        comps.sort(key = lambda e : e[3])
        cv.drawMarker(img, (round(comps[0][0]),round(comps[0][1])), color=(0,0,255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=5)
        cv_dat['cur'] = comps[0]
    else:
        cv_dat['cur'] = None
    return img


def cv_get_pad(img):
    if not cv_dat['detect']:
        return img

    # Convert image to grayscale
    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
    gray = cv.medianBlur(gray, 3)

    # Closing small gaps
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (5, 5))
    gray = cv.morphologyEx(gray, cv.MORPH_OPEN, kernel)

    # Convert image to binary
    _, bw = cv.threshold(gray, 100, 255, cv.THRESH_BINARY)
    #cv.imwrite(f'{cur_path}/tmp/gray.png', gray) # for debug
    #cv.imwrite(f'{cur_path}/tmp/bw.png', bw)

    # Find all the contours in the thresholded image
    contours, _ = cv.findContours(bw, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_NONE)

    for i, c in enumerate(contours):

        # Calculate the area of each contour
        area = cv.contourArea(c)

        # cv.minAreaRect returns:
        # (center(x, y), (width, height), angle of rotation) = cv2.minAreaRect(c)
        rect = cv.minAreaRect(c)

        # Retrieve the key parameters of the rotated bounding box
        center = (round(rect[0][0]), round(rect[0][1]))

        # Ignore contours that are too small or too large
        if area < 2*2 or 580*580 < area:
            continue
        if bw[center[1], center[0]] != 255:   # skip black
            continue
        # todo: ignore contours too far away

        cam_height, cam_width = img.shape[:2]
        cam_center = (round(cam_width/2), round(cam_height/2))

        # connect all contours
        cv.line(bw, center, cam_center, (255,255,255), 1)


    #cv.imwrite(f'{cur_path}/tmp/bw.png', bw)

    # Find all the contours in the thresholded image
    contours, _ = cv.findContours(bw, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_NONE)

    comps = []
    for i, c in enumerate(contours):

        # Calculate the area of each contour
        area = cv.contourArea(c)

        # Ignore contours that are too small or too large
        #if area < 2*11 or 580*580 < area:
        #  continue

        # cv.minAreaRect returns:
        # (center(x, y), (width, height), angle of rotation) = cv2.minAreaRect(c)
        rect = cv.minAreaRect(c)
        box = cv.boxPoints(rect)
        box = np.int0(np.around(box))

        # Retrieve the key parameters of the rotated bounding box
        center_f = (rect[0][0], rect[0][1])
        center = (round(rect[0][0]), round(rect[0][1]))
        height = round(rect[1][0])
        width = round(rect[1][1])
        angle = rect[2]

        if width > height:
            angle = 90 - angle
        else:
            angle = -angle

        if angle < -45:
            angle += 90
        elif angle > 45:
            angle -= 90
        angle = round(angle, 1)

        cam_height, cam_width = img.shape[:2]
        x_center, y_center = round(cam_width/2), round(cam_height/2)
        l_center = abs(center[0] - x_center) + abs(center[1] - y_center)
        comps.append([center_f[0], center_f[1], angle, l_center])

        label = str(angle) + ' !'
        cv.drawContours(img,[box],0,(0,0,255),1)
        cv.putText(img, label, (center[0]+14, center[1]), cv.FONT_HERSHEY_SIMPLEX, 0.4, (0,200,255), 1, cv.LINE_AA)
        cv.drawMarker(img, (center[0],center[1]), color=(0,255,255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=10)

    if len(comps):
        comps.sort(key = lambda e : e[3])
        cv.drawMarker(img, (round(comps[0][0]),round(comps[0][1])), color=(0,0,255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=5)
        cv_dat['cur'] = comps[0]
    else:
        cv_dat['cur'] = None
    return img



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

        elif rx_dat is None:
            #print(f'skip incomplete image data, hdr: {hdr:02x}')
            continue

        elif (hdr & 0xf0) == 0x60: # more
            if dat_cnt == (hdr & 0xf):
                rx_dat += dat
            #else:
            #    print(f'pic, wrong cnt, local: {dat_cnt} != rx: {hdr & 0xf}, dat len: {len(dat)}')

        elif (hdr & 0xf0) == 0x70: # end
            if dat_cnt == (hdr & 0xf):
                #print('pic received!')
                if rx_dat[0] != 0xff or rx_dat[1] != 0xd8:
                    print(f'jpg header error: {rx_dat[0]:02x} {rx_dat[1]:02x}!')
                inp = np.asarray(bytearray(rx_dat), dtype=np.uint8)
                img = cv.imdecode(inp, cv.IMREAD_COLOR)
                if cv_dat['dev'] == 2:
                    img = cv.flip(img, 1)
                if cv_dat['dev'] == 1:
                    img = cv.rotate(img, cv.ROTATE_90_CLOCKWISE)
                    if cv_dat['bg_capture']:
                        cv_dat['bg_capture'] = False
                        print(f'save bg_img to: {cur_path}/tmp/')
                        blur = cv.medianBlur(img, 15)
                        cv_dat['bg_img'] = np.invert(blur)
                        cv.imwrite(f'{cur_path}/tmp/bg_invert.png', cv_dat['bg_img'])
                    if cv_dat['bg_img'] is not None:
                        img = cv.addWeighted(img, 0.8, cv_dat['bg_img'], 0.6, 0)
                cam_height, cam_width = img.shape[:2]

                if cv_dat['detect'].startswith("cali_nozzle"):
                    img = cv_get_circle(img)
                elif cv_dat['detect'] == "cali_pad":
                    img = cv_get_pad(img)
                else:
                    img = cv_get_pos(img)

                if cv_dat['dev'] == 1:
                    img = cv.drawMarker(img, (int(cam_width/2),int(cam_height/2)), color=(0,255,0), markerType=cv.MARKER_CROSS, thickness=1)
                else:
                    img = cv.drawMarker(img, (int(cam_width/2),int(cam_height/2)), color=(0,255,0), markerType=cv.MARKER_CROSS, markerSize=cam_height-20, thickness=1)

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
    if os.path.exists(f'{cur_path}/tmp/bg_invert.png'):
        print(f'load bg_img from: {cur_path}/tmp/bg_invert.png ...')
        cv_dat['bg_img'] = cv.imread(f'{cur_path}/tmp/bg_invert.png')
    _thread.start_new_thread(pic_rx, ())
    if cv_dat['local']:
        _thread.start_new_thread(cv_window, ())

