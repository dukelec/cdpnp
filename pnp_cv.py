#!/usr/bin/env python3

# This programs calculates the orientation of an object.
# The input is an image, and the output is an annotated image
# with the angle of otientation for each object (0 to 180 degrees)

import sys, os, _thread
import struct, queue, re
from time import sleep, time

from cdnet.utils.log import *
from cdnet.dispatch import *

import cv2 as cv
from math import atan2, cos, sin, sqrt, pi
import numpy as np
from pathlib import Path

cur_path = Path(__file__).parent.absolute()

cv_dat = {
    'dev': 1,

    'cur': None,    # the chosen detection, [x, y, angle, dist] (+ [long, short] side in pixels for a component)
    'comps': [],    # every detection of the frame, cur first, the same entries
    'img_queue': None,

    'detect': 'default',
    'local': True,  # show opencv window

    'bg_img': None, # background image
    'bg_capture': False,
    
    'nozzle_thresh': 199,
    'debug': False,

    'sock_pic': None,
    'bad_cnt': 0,   # broken jpg counter, for file name of tmp/bad_N.jpg

    'expos': 20,    # last exposure written to the camera, for the api to read back

    # the last frame, for the external api (api_serve.py): one dict swapped in whole, so a reader
    # on another thread always sees a raw jpg, its annotated image and its detection together
    #   {'seq': N, 'ts': time.time(), 'dev': 1 | 2, 'detect': str, 'raw': jpg bytes,
    #    'img': annotated bgr ndarray, 'cur': [x, y, angle, dist, ...] | None, 'comps': [cur, ...]}
    'last': None
}



def cv_get_pos(img, detect):
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
        if detect[0:4] == "pld_":
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
        box = np.int_(np.around(box))

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

        if detect == 'limit_angle':
            if angle < -45:
                angle += 90
            elif angle > 45:
                 angle -= 90
        angle = round(angle, 1)

        x_center, y_center = round(cam_width/2), round(cam_height/2)
        l_center = abs(center[0] - x_center) + abs(center[1] - y_center)
        # the size as long and short side, so it does not depend on the orientation
        comps.append([center_f[0], center_f[1], angle, l_center, max(width, height), min(width, height)])

        label = str(angle) + (' !' if detect == 'limit_angle' else '')
        cv.drawContours(img,[box],0,(0,0,255),1)
        if detect[0:4] != "pld_":
            cv.putText(img, label, (center[0]+14, center[1]), cv.FONT_HERSHEY_SIMPLEX, 0.4, (0,200,255), 1, cv.LINE_AA)
        cv.drawMarker(img, (center[0],center[1]), color=(0,255,255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=10)

    if len(comps):
        if detect == "pld_first":
            comps.sort(key = lambda e : e[1])
        elif detect == "pld_last":
            comps.sort(key = lambda e : -e[1])
        else:
            comps.sort(key = lambda e : e[3])
        cv.drawMarker(img, (round(comps[0][0]),round(comps[0][1])), color=(0,0,255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=5)
        cv_dat['cur'] = comps[0]
    else:
        cv_dat['cur'] = None
    cv_dat['comps'] = comps
    return img


def cv_get_circle(img, detect):
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

        filter_radius = float(detect.split("_")[2]) / 2
        filter_delta = float(detect.split("_")[3]) / 2
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
    cv_dat['comps'] = comps
    return img


def cv_get_pad(img, detect):
    # Convert image to grayscale
    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
    gray = cv.medianBlur(gray, 3)

    # Closing small gaps
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (5, 5))
    gray = cv.morphologyEx(gray, cv.MORPH_OPEN, kernel)

    # Convert image to binary
    _, bw = cv.threshold(gray, 75, 255, cv.THRESH_BINARY)
    #cv.imwrite(f'{cur_path}/tmp/gray.png', gray) # for debug
    #cv.imwrite(f'{cur_path}/tmp/bw.png', bw)

    # Find all the contours in the thresholded image
    contours, _ = cv.findContours(bw, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_NONE)

    pads = []
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
        
        pads.append(center)


    if len(pads):
        avg_center = [round(sum(list(zip(*pads))[0]) / len(pads)), round(sum(list(zip(*pads))[1]) / len(pads))]
        for i in range(len(pads)):
            # connect all contours
            cv.line(bw, pads[i], avg_center, (255,255,255), 1)

    #cv.imwrite(f'{cur_path}/tmp/bw.png', bw)

    # Find all the contours in the thresholded image
    contours, _ = cv.findContours(bw, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_NONE)

    comps = []
    for i, c in enumerate(contours):

        # Calculate the area of each contour
        area = cv.contourArea(c)

        # Ignore contours that are too small or too large
        if area < 2*2 or 580*580 < area:
            continue

        # cv.minAreaRect returns:
        # (center(x, y), (width, height), angle of rotation) = cv2.minAreaRect(c)
        rect = cv.minAreaRect(c)
        box = cv.boxPoints(rect)
        box = np.int_(np.around(box))

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
    cv_dat['comps'] = comps
    return img



def fid_edge_fit(gray, sx, sy, r_min, r_max):
    """Sub-pixel circle on the bright -> dark edge going outward from (sx, sy), None if not a clean circle."""
    n = 96
    idx = np.arange(n)
    th = np.linspace(0, 2 * pi, n, endpoint=False)
    rr = np.arange(r_min, r_max + 0.25, 0.25)
    cx, cy = sx, sy
    for _ in range(3):
        xs = (cx + np.outer(np.cos(th), rr)).astype(np.float32)
        ys = (cy + np.outer(np.sin(th), rr)).astype(np.float32)
        dv = np.gradient(cv.remap(gray, xs, ys, cv.INTER_LINEAR), axis=1)
        k = np.argmin(dv, axis=1)
        keep = dv[idx, k] < -1.0
        if keep.sum() < n / 2:
            return None
        x, y = xs[idx, k][keep].astype(np.float64), ys[idx, k][keep].astype(np.float64)
        for _ in range(4):
            sol = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones(len(x))], x * x + y * y, rcond=None)[0]
            cx, cy = sol[0], sol[1]
            r = sqrt(max(sol[2] + cx * cx + cy * cy, 0))
            err = np.hypot(x - cx, y - cy) - r
            good = np.abs(err) < max(1.0, 2.2 * err.std())
            if good.all():
                break
            x, y = x[good], y[good]
        if len(x) < n / 2:
            return None
    sectors = np.floor((np.arctan2(y - cy, x - cx) + pi) / (2 * pi) * 12).astype(int)
    if len(x) < n * 0.7 or len(set(sectors.tolist())) < 11: # a pad has edges on two sides only
        return None
    return float(cx), float(cy), r, float(err.std())


# detect: fiducial_D_T, a bright round mark of diameter D +/- T pixels
def cv_get_fid(img, detect):
    d, t = float(detect.split("_")[1]), float(detect.split("_")[2])
    r_min, r_max = max((d - t) / 2, 2), (d + t) / 2
    cam_height, cam_width = img.shape[:2]
    x_center, y_center = cam_width / 2, cam_height / 2
    gray8 = cv.cvtColor(cv.GaussianBlur(img, (3, 3), 0), cv.COLOR_BGR2GRAY)
    gray = gray8.astype(np.float32)

    seeds = []
    cs = cv.HoughCircles(gray8, cv.HOUGH_GRADIENT, dp=1, minDist=max(d * 0.8, 6), param1=120, param2=14,
                         minRadius=int(r_min), maxRadius=int(r_max + 1))
    if cs is not None:
        seeds += [(float(c[0]), float(c[1])) for c in cs[0]]
    # a very small mark has too few edge points for Hough: bright blobs of about its size
    k = max(int(d * 2) | 1, 9)
    bright = cv.subtract(gray8, cv.blur(gray8, (k, k)))
    n, _, stats, cen = cv.connectedComponentsWithStats(cv.threshold(bright, 30, 255, cv.THRESH_BINARY)[1])
    for i in range(1, n):
        if 0.3 * pi * r_min * r_min <= stats[i, cv.CC_STAT_AREA] <= 1.3 * pi * r_max * r_max:
            seeds.append((float(cen[i, 0]), float(cen[i, 1])))

    margin = r_max + 3
    seeds = [s for s in seeds if margin < s[0] < cam_width - margin and margin < s[1] < cam_height - margin]
    seeds.sort(key=lambda s: abs(s[0] - x_center) + abs(s[1] - y_center))
    comps = []
    for sx, sy in seeds[:16]:
        ret = fid_edge_fit(gray, sx, sy, r_min, r_max)
        if ret is None:
            continue
        cx, cy, r, rms = ret
        if not (r_min <= r <= r_max and rms <= 0.8 and margin < cx < cam_width - margin and margin < cy < cam_height - margin):
            continue
        if any(np.hypot(cx - c[0], cy - c[1]) < max(r, 3) for c in comps):
            continue
        comps.append([cx, cy, 0, round(abs(cx - x_center) + abs(cy - y_center)), round(r * 2, 1), round(r * 2, 1)])

    for c in comps:
        center = (round(c[0]), round(c[1]))
        cv.circle(img, center, round(c[4] / 2), (0, 0, 255), 1)
        cv.drawMarker(img, center, color=(0, 255, 255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=10)
        cv.putText(img, 'd' + str(c[4]), (center[0] + 14, center[1]), cv.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1, cv.LINE_AA)

    comps.sort(key=lambda e: e[3])
    if comps:
        cv.drawMarker(img, (round(comps[0][0]), round(comps[0][1])), color=(0, 0, 255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=5)
    cv_dat['cur'] = comps[0] if comps else None
    cv_dat['comps'] = comps
    return img



def outer_edge(dv):
    """Index of the outermost strong bright -> dark edge of each ray: a blotch inside a pad has one too."""
    strong = dv < np.minimum(dv.min(axis=1, keepdims=True) * 0.5, -1.0)
    k = dv.shape[1] - 1 - np.argmax(strong[:, ::-1], axis=1)
    for i in range(len(k)):
        while k[i] > 0 and dv[i, k[i] - 1] < dv[i, k[i]]:
            k[i] -= 1
    return k


def pad_side_fit(gray, c, n, t, h, l, band):
    """Distance from c along n to the bright -> dark edge of a side, at the middle of the side, and its rms."""
    m = max(int(l * 1.2), 12)
    s = np.linspace(-0.6 * l, 0.6 * l, m)
    rr = np.arange(max(h - band, 1), h + band + 0.25, 0.25)
    xs = (c[0] + n[0] * rr[None, :] + t[0] * s[:, None]).astype(np.float32)
    ys = (c[1] + n[1] * rr[None, :] + t[1] * s[:, None]).astype(np.float32)
    dv = np.gradient(cv.remap(gray, xs, ys, cv.INTER_LINEAR), axis=1)
    k = outer_edge(dv)
    keep = dv[np.arange(m), k] < -1.0
    sk, d = s[keep], rr[k[keep]]
    if len(d) < m * 0.6:
        return None
    for _ in range(4):
        b, a = np.polyfit(sk, d, 1)
        err = d - (a + b * sk)
        good = np.abs(err) < max(1.0, 2.2 * err.std())
        if good.all():
            break
        sk, d = sk[good], d[good]
    if len(d) < m * 0.6:
        return None
    return float(a), float(err.std())


def pad_seeds(gray8, long_side, short_side, count=24):
    """Peaks of the match between the edges of the frame and the outline of the pad: (x, y, angle)."""
    mag = cv.magnitude(cv.Sobel(gray8, cv.CV_32F, 1, 0, ksize=3), cv.Sobel(gray8, cv.CV_32F, 0, 1, ksize=3))
    mag = cv.resize(mag, None, fx=0.5, fy=0.5, interpolation=cv.INTER_AREA) # half size: this runs in the camera thread
    near = max(int(short_side / 2) | 1, 3)
    peaks = []
    for deg in range(-6, 7, 3):
        for rot in ((0, 90) if long_side - short_side > 3 else (0,)):
            box = cv.boxPoints(((0, 0), (long_side / 2, short_side / 2), deg + rot))
            lo = box.min(axis=0) - 2
            size = np.ceil(box.max(axis=0) - lo + 2).astype(int)
            tpl = np.zeros((size[1], size[0]), np.float32)
            cv.polylines(tpl, [np.int32(np.around(box - lo))], True, 1.0, 2)
            res = cv.matchTemplate(mag, tpl, cv.TM_CCORR_NORMED)
            ys, xs = np.where((res == cv.dilate(res, np.ones((near, near), np.uint8))) & (res > 0.2))
            for x, y in zip(xs, ys):
                peaks.append((float(res[y, x]), float(x - lo[0]) * 2, float(y - lo[1]) * 2, np.radians(deg + rot)))
    peaks.sort(key=lambda p: -p[0])
    return [p[1:] for p in peaks[:count]]


def pad_refine(gray, cx, cy, ang, hl, hs, band):
    """Sub-pixel center of a rectangle from its 4 edges: (cx, cy, half long, half short, worst side rms) or None."""
    u = (cos(ang), sin(ang))
    v = (-u[1], u[0])
    rms = 0
    for _ in range(3):
        c = (cx, cy)
        up = pad_side_fit(gray, c, u, v, hl, hs, band)
        um = pad_side_fit(gray, c, (-u[0], -u[1]), v, hl, hs, band)
        vp = pad_side_fit(gray, c, v, u, hs, hl, band)
        vm = pad_side_fit(gray, c, (-v[0], -v[1]), u, hs, hl, band)
        if None in (up, um, vp, vm):
            return None
        du, dv = (up[0] - um[0]) / 2, (vp[0] - vm[0]) / 2
        cx += u[0] * du + v[0] * dv
        cy += u[1] * du + v[1] * dv
        hl, hs = (up[0] + um[0]) / 2, (vp[0] + vm[0]) / 2
        rms = max(up[1], um[1], vp[1], vm[1])
    return cx, cy, hl, hs, rms


# detect: fidrect_W_H_T, a bright rectangular pad of W x H +/- T pixels, in any direction
def cv_get_fidrect(img, detect):
    w, h, t = [float(v) for v in detect.split("_")[1:4]]
    long_side, short_side = max(w, h), min(w, h)
    cam_height, cam_width = img.shape[:2]
    x_center, y_center = cam_width / 2, cam_height / 2
    gray8 = cv.cvtColor(cv.GaussianBlur(img, (3, 3), 0), cv.COLOR_BGR2GRAY)
    gray = gray8.astype(np.float32)

    # the tin of a pad is blotchy and how bright it is varies: try a few levels, the edges decide
    k = max(int(long_side * 2) | 1, 17)
    bright = cv.subtract(gray8, cv.blur(gray8, (k, k)))
    size = max(3, min(int(short_side * 0.6), 9) | 1)  # bridges the blotches, not the gap to the silkscreen
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (size, size))
    seeds = pad_seeds(gray8, long_side, short_side)
    for level in (20, 35, 55):
        bw = cv.morphologyEx(cv.threshold(bright, level, 255, cv.THRESH_BINARY)[1], cv.MORPH_CLOSE, kernel)
        contours, _ = cv.findContours(bw, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_NONE)
        for c in contours:
            (cx, cy), (a, b), ang = cv.minAreaRect(c)
            if abs(max(a, b) - long_side) <= t + 3 and abs(min(a, b) - short_side) <= t + 3:
                seeds.append((cx, cy, np.radians(ang if a >= b else ang + 90)))

    seeds.sort(key=lambda s: abs(s[0] - x_center) + abs(s[1] - y_center))
    uniq = []
    for s in seeds:
        if all(np.hypot(s[0] - u[0], s[1] - u[1]) > short_side / 3 for u in uniq):
            uniq.append(s)
    margin = long_side / 2 + t + 8
    band = t / 2 + 3    # no wider: the silkscreen around a pad has edges too
    comps = []
    boxes = []
    for sx, sy, ang in uniq[:16]:
        if not (margin < sx < cam_width - margin and margin < sy < cam_height - margin):
            continue
        ret = pad_refine(gray, sx, sy, ang, long_side / 2, short_side / 2, band)
        if ret is None:
            continue
        cx, cy, hl, hs, rms = ret
        if abs(2 * hl - long_side) > t or abs(2 * hs - short_side) > t or rms > 2:
            continue
        if any(np.hypot(cx - c[0], cy - c[1]) < hs for c in comps):
            continue
        comps.append([cx, cy, 0, round(abs(cx - x_center) + abs(cy - y_center)), round(2 * hl, 1), round(2 * hs, 1)])
        boxes.append(((cx, cy), (2 * hl, 2 * hs), np.degrees(ang)))

    for c, b in zip(comps, boxes):
        cv.drawContours(img, [np.int_(np.around(cv.boxPoints(b)))], 0, (0, 0, 255), 1)
        cv.drawMarker(img, (round(c[0]), round(c[1])), color=(0, 255, 255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=10)

    comps.sort(key=lambda e: e[3])
    if comps:
        cv.drawMarker(img, (round(comps[0][0]), round(comps[0][1])), color=(0, 0, 255), markerType=cv.MARKER_CROSS, thickness=1, markerSize=5)
    cv_dat['cur'] = comps[0] if comps else None
    cv_dat['comps'] = comps
    return img



def pic_save_bad(rx_dat, reason):
    # save broken jpg for offline analysis, keep at most 10 files
    n = cv_dat['bad_cnt']
    cv_dat['bad_cnt'] = n + 1
    path = f'{cur_path}/tmp/bad_{n % 10}.jpg'
    with open(path, 'wb') as f:
        f.write(rx_dat)
    print(f'pic error: {reason}, len: {len(rx_dat)}, tail: {rx_dat[-2:].hex()}, saved to: {path}')


def pic_rx():
    rx_dat = None
    rx_src = None   # address of current camera, drop fragments from the other camera
    dat_cnt = 0
    detect = cv_dat['detect']
    dev_idx = cv_dat['dev']

    while True:
        dat, src = cv_dat['sock_pic'].recvfrom()
        hdr = src[1]  # [5:4] FRAGMENT: 00: error, 01: first, 10: more, 11: last, [3:0]: cnt

        if hdr == 0x50:     # first
            rx_dat = dat
            rx_src = src[0]
            dat_cnt = 0
            detect = cv_dat['detect']
            dev_idx = cv_dat['dev']

        elif rx_dat is None:
            #print(f'skip incomplete image data, hdr: {hdr:02x}')
            continue

        elif src[0] != rx_src:
            continue # fragment from the other camera, keep dat_cnt untouched

        elif (hdr & 0xf0) == 0x60: # more
            if dat_cnt == (hdr & 0xf):
                rx_dat += dat
            #else:
            #    print(f'pic, wrong cnt, local: {dat_cnt} != rx: {hdr & 0xf}, dat len: {len(dat)}')

        elif (hdr & 0xf0) == 0x70: # end
            if dat_cnt == (hdr & 0xf):
                rx_dat += dat # the last fragment also carries data
                #print('pic received!')
                if len(rx_dat) < 4 or rx_dat[0] != 0xff or rx_dat[1] != 0xd8:
                    pic_save_bad(rx_dat, 'wrong jpg header')
                    rx_dat = None
                    continue
                inp = np.asarray(bytearray(rx_dat), dtype=np.uint8)
                img = cv.imdecode(inp, cv.IMREAD_COLOR)
                if img is None:
                    pic_save_bad(rx_dat, 'img is none')
                    rx_dat = None
                    continue

                if dev_idx == 2:
                    img = cv.flip(img, 1)
                else:
                    img = cv.rotate(img, cv.ROTATE_90_CLOCKWISE)
                    if cv_dat['bg_capture']:
                        cv_dat['bg_capture'] = False
                        print(f'save bg_img to: {cur_path}/tmp/')
                        blur = cv.medianBlur(img, 15)
                        cv_dat['bg_img'] = np.invert(blur)
                        cv.imwrite(f'{cur_path}/tmp/bg_invert.png', cv_dat['bg_img'])
                    bg_img = cv_dat['bg_img']
                    if bg_img is not None:
                        img = cv.addWeighted(img, 0.8, bg_img, 0.6, 0)
                cam_height, cam_width = img.shape[:2]

                if detect.startswith("cali_nozzle"):
                    img = cv_get_circle(img, detect)
                elif detect == "cali_pad":
                    img = cv_get_pad(img, detect)
                elif detect.startswith("fiducial_"):
                    img = cv_get_fid(img, detect)
                elif detect.startswith("fidrect_"):
                    img = cv_get_fidrect(img, detect)
                elif detect:
                    img = cv_get_pos(img, detect)
                else:   # nothing looked for, so nothing found: do not keep the result of an older mode
                    cv_dat['cur'] = None
                    cv_dat['comps'] = []

                if dev_idx == 1:
                    img = cv.drawMarker(img, (int(cam_width/2),int(cam_height/2)), color=(0,255,0), markerType=cv.MARKER_CROSS, thickness=1)
                else:
                    img = cv.drawMarker(img, (int(cam_width/2),int(cam_height/2)), color=(0,255,0), markerType=cv.MARKER_CROSS, markerSize=cam_height-20, thickness=1)

                last = cv_dat['last']
                cv_dat['last'] = {'seq': (last['seq'] + 1) if last else 1, 'ts': time(), 'dev': dev_idx,
                                  'detect': detect, 'raw': rx_dat, 'img': img, 'cur': cv_dat['cur'], 'comps': cv_dat['comps']}

                if not cv_dat['img_queue'].full():
                    if not cv_dat['local']:
                        img = cv.imencode('.png', img)[1].tobytes()
                    cv_dat['img_queue'].put_nowait(img)
                rx_dat = None
            else:
                print(f'pic drop: wrong cnt at end, local: {dat_cnt} != rx: {hdr & 0xf}, len: {len(rx_dat)}')
                rx_dat = None

        else: # error type: fragment lost between fpga and mcu, reported by firmware
            print(f'pic drop: err fragment from firmware, hdr: {hdr:02x}, len: {len(rx_dat)}')
            rx_dat = None
            continue

        dat_cnt += 1
        if dat_cnt == 0x10:
            dat_cnt = 0


def pnp_cv_start(detect='default', local=True):
    cv_dat['detect'] = detect
    cv_dat['local'] = local
    cv_dat['img_queue'] = queue.Queue(10)
    cv_dat['sock_pic'] = CDNetSocket(('', 0x10))
    if os.path.exists(f'{cur_path}/tmp/bg_invert.png'):
        print(f'load bg_img from: {cur_path}/tmp/bg_invert.png ...')
        cv_dat['bg_img'] = cv.imread(f'{cur_path}/tmp/bg_invert.png')
    _thread.start_new_thread(pic_rx, ())
    while True:
        if cv_dat['local']:
            cur_pic = cv_dat['img_queue'].get()
            cv.imshow('image', cur_pic)
            cv.waitKey(10)
        else:
            sleep(0.5)

