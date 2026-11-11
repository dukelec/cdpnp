#!/usr/bin/env python3
# Software License Agreement (MIT License)
#
# Copyright (c) 2023, DUKELEC, Inc.
# All rights reserved.
#
# Author: Duke Fong <d@d-l.io>

"""CDPNP firmware and config updater

Brings the bootloader, the app and the config of every module to what is in
tools/firmware and tools/cdbus_gui_configs, whatever the module runs now:
cdnet v1 (L1 frames, 80:00:xx) or cdnet v2 (L0 frames, 00:00:xx) firmware,
in app or in bootloader mode.

  1. scan: each module is asked for its info string in both protocols, the
     firmware variant is told from the model, the HW field if there is one
     (only its major, modules shipped without a version in the otp have none),
     the flash size, the git hash the old builds report as SW (see
     firmware/fw_hashes.json), the git tag in the app image or, when still
     open, by comparing the flash with the candidate files; the bl and the app
     of a new build are compared with the files.
  2. a plan is printed, nothing is written before it is confirmed.
  3. per module, all at the configured address and baud rate (1M/10M), as the
     other modules keep talking on the bus and a 115200 bps node would break
     the arbitration:
     - the bootloader is written by the running app (a bl can not rewrite itself),
     - the config page is rewritten in the new layout before any new code boots
       from it: only the common part (address, baud rate, bus mode, ...) with a
       conf_ver of the same major but another minor, so the new bl reads it and
       the new app takes the bus config from it and the defaults for the rest
       (conf_from 2); the old pages break the new firmware (idle_wait_len 0,
       mode renumbered, cdstep moved everything),
     - reboot to the bl (do_reboot 1, keep_bl), write the app,
     - boot the app, write the config from the .mpk file, save_conf, reboot and
       check that it comes back with the config from flash.
  Every flash write is read back. A module that is not found at its address is
  looked for at 00:00:fe 115200 bps (default config), or caught in its
  bootloader while the machine is power cycled.

A power loss while a bl is written bricks the board (swd only then). --keep-bl
leaves a bl other than the file alone when it is new enough for these files
(min_bl of each board, told by the version in its image); older ones, and the
old builds that report a git hash, are updated anyway.

The cdbus bridge comes first, the modules need its v7 firmware or later (the
baud rate of the port sets the bus) and a v4 one does not pass frames through.
The port at the baud rate 0xcdcd talks to the bridge itself, found at 00:00:ff
(v7 on, every new bl), 80:00:fe (v5 / v6, cdnet v1) or 80:00:55 from host 0xaa
(v4, forwarding mode); the usb vid tells hw v4 / v5 (stm32) from v6 (at32). Its
app writes the bl, do_reboot 1 keeps the bl since early 2025, older ones need
the switch S1.1 ON (asked for), and OFF again when the new app is in. The new
app drops a config of another version and starts with the defaults, nothing of
cdpnp is in it. A reboot drops the usb port, the serial device opens it again.

Usage: tools/fw_cfg_update.py [-h] [options]
"""

import os, sys, re, json, time, glob, struct, argparse
from os.path import join as pjoin, dirname, abspath, basename

HERE = dirname(abspath(__file__))
sys.path.append(pjoin(HERE, '..', 'pycdnet'))

import logging
import umsgpack
from cdnet.utils.log import logger_init
from cdnet.dev.cdbus_serial import CDBusSerial
from cdnet.utils.serial_get_port import get_port, get_ports

FW_DIR = pjoin(HERE, 'firmware')
CFG_DIR = pjoin(HERE, 'cdbus_gui_configs')
CACHE_FILE = pjoin(HERE, '.fw_update_cache.json') # module serial -> variant, for a module found in bl later

BAUD = 10000000         # bridge: baud_h, baud_l limited to 1M (bridge switch S1.2 off)
BAUD_DFT = 115200       # modules with the default config
MAC_DFT = 0xfe
PAGE = 2048
BLK = 128               # flash read / write size per frame
APP_ADDR = 0x08006000   # end of the bl area
FLASHSIZE_REG = 0x1fff75e0 # stm32g0: flash size in KiB
BAUD_CONF = 0xcdcd      # the port at this baud rate talks to the bridge itself (config mode)

# csa registers that are at the same place in every firmware, old and new
R_CONF_FROM = 0x0004
R_REBOOT = 0x0005       # 1: reboot to bl (keep there), 2: reboot to app
R_KEEP_BL = 0x0006      # bootloader only
R_MARK = 0x0006         # app: unused (keep_bl of the bl), cleared at boot
R_SAVE_CONF = 0x0007


class Target:
    def __init__(self, desc, app, bl, cfg, flash_kb, conf_addr, conf_ver, end_common, conf_ranges, min_bl, skip=()):
        self.desc = desc
        self.min_bl = min_bl            # --keep-bl: an older bl is updated anyway, see Flasher.keep_bl
        self.app_pat, self.bl_pat = app, bl
        self.cfg = cfg                  # cdbus gui config: register names of the .mpk files
        self.flash_kb = flash_kb
        self.conf_addr = conf_addr      # APP_CONF_ADDR
        self.conf_ver = conf_ver        # APP_CONF_VER
        self.end_common = end_common    # _end_common: the part the app takes from a page of another minor version
        self.conf_ranges = conf_ranges  # register addresses saved by save_conf, the only ones taken from a .mpk
        self.skip = set(skip)           # saved, but runtime state, never written from a .mpk
        self.app = self.bl = None       # Fw, loaded on use

    @property
    def conf_ver_common(self):
        # same major, so the new bl loads it and the new app takes [0, _end_common)
        return (self.conf_ver & 0xf000) | 0x0fff

    def load(self):
        if not self.app:
            self.app = Fw(self.app_pat, 'app')
            self.bl = Fw(self.bl_pat, 'bl')
        return self


# min_bl: the oldest bl that works with these files: it reads the conf page of the new layout (else the
# bl would not answer at the address of the module any more) and speaks cdnet v2
_STEP = dict(flash_kb=128, conf_addr=0x0801f800, conf_ver=0x0300, end_common=0x0031, min_bl='v3.0',
             skip=('dbg_raw_en', 'tp_pos', 'tp_state', 'tp_vel_out'))
_PRJ = [(0x0008, 0x0294), (0x0300, 0x03d0)]
_CAM = dict(bl='bl/cdcam123_bl_v*.hex', cfg='cdcam-v2.0.0.json', flash_kb=128, conf_addr=0x0801f800,
            conf_ver=0x0200, end_common=0x002c, conf_ranges=[(0x0008, 0x005f)], min_bl='v3.0')

TARGETS = {
    'step':   Target('cdstep',   app='app/cdstep34_fw_v*.hex',  bl='bl/cdstep34_bl_v*.hex', cfg='cdstep-v3.0.0.json',
                     conf_ranges=[(0x0008, 0x0294)], **_STEP),
    'step_r': Target('cdstep-r', app='app/cdstep34r_fw_v*.hex', bl='bl/cdstep34_bl_v*.hex', cfg='cdstep-r-v3.0.0.json',
                     conf_ranges=_PRJ, **_STEP),
    'step_z': Target('cdstep-z', app='app/cdstep34z_fw_v*.hex', bl='bl/cdstep34_bl_v*.hex', cfg='cdstep-z-v3.0.0.json',
                     conf_ranges=_PRJ, **_STEP),
    'pump1':  Target('cdpump1 (g031)', app='app/cdpump1_fw_v*.hex', bl='bl/cdpump1_bl_v*.hex', cfg='cdpump-v2.0.0.json',
                     flash_kb=64, conf_addr=0x0800f800, conf_ver=0x0200, end_common=0x002c,
                     conf_ranges=[(0x0008, 0x0036)], min_bl='v2.0'),
    'pump2':  Target('cdpump2', app='app/cdpump2_fw_v*.hex', bl='bl/cdpump2_bl_v*.hex', cfg='cdpump-v2.0.1.json',
                     flash_kb=128, conf_addr=0x0801f800, conf_ver=0x0200, end_common=0x002b,
                     conf_ranges=[(0x0008, 0x00e2)], min_bl='v3.0', skip=('dbg_raw_msk',)),
    'cam1':   Target('cdcam1',  app='app/cdcam1_*.hex',  **_CAM),
    'cam23':  Target('cdcam23', app='app/cdcam23_*.hex', **_CAM),
}

# the modules of a cdpnp, address: {variant allowed here: config file}
DEVICES = {
    '00:00:01': {'step':   'cdstep_01.mpk'},
    '00:00:02': {'step':   'cdstep_02.mpk'},
    '00:00:03': {'step':   'cdstep_03.mpk'},
    '00:00:04': {'step_z': 'cdstep_04.mpk'},
    '00:00:05': {'step_r': 'cdstep_05.mpk'},
    '00:00:11': {'pump1':  'cdpump_11.mpk', 'pump2': 'cdpump_v2_11.mpk'},
    '00:00:21': {'cam1':   'cdcam_21.mpk',  'cam23': 'cdcam_21.mpk'},
    '00:00:22': {'cam1':   'cdcam_22.mpk',  'cam23': 'cdcam_22.mpk'},
}

class BridgeTarget:
    def __init__(self, desc, hw, app, bl, app_addr, conf_addr, conf_ver, flash_kb, min_bl='v7.0'):
        self.desc, self.hw = desc, hw
        self.min_bl = min_bl            # cdnet v2 (the cdbus gui of today), do_reboot 1 keeps it
        self.app_pat, self.bl_pat, self.app_addr = app, bl, app_addr
        self.conf_addr = conf_addr      # APP_CONF_ADDR of the app
        self.conf_ver = conf_ver        # APP_CONF_VER of the app
        self.flash_kb = flash_kb        # checked on the stm32 only
        self.app = self.bl = None

    def load(self):
        if not self.app:
            self.app = Fw(self.app_pat, 'app', self.app_addr)
            self.bl = Fw(self.bl_pat, 'bl', self.app_addr)
        return self

# the cdbus bridge, told by the usb vid: stm32g0b1 (hw v4 / v5) or at32f405 (hw v6)
BRIDGES = {
    0x0483: BridgeTarget('cdbus bridge hw v4 / v5', (4, 5), 'app/cdbridge45_fw_v*.hex', 'bl/cdbridge45_bl_v*.hex',
                         app_addr=0x08009000, conf_addr=0x0801f800, conf_ver=0x0204, flash_kb=128),
    0x2e3c: BridgeTarget('cdbus bridge hw v6', (6,), 'app/cdbridge6_fw_v*.hex', 'bl/cdbridge6_bl_v*.hex',
                         app_addr=0x08006000, conf_addr=0x0803f800, conf_ver=0x0205, flash_kb=None),
}

# model in the info string -> (family in fw_hashes.json, variants)
MODELS = {
    'cdstep':      ('cdstep', ['step']),
    'mdrv-step':   ('cdstep', ['step']),
    'cdstep-r':    ('cdstep', ['step_r']),
    'mdrv-step-r': ('cdstep', ['step_r']),
    'cdstep-z':    ('cdstep', ['step_z']),
    'mdrv-step-z': ('cdstep', ['step_z']),
    'cdpump':      ('cdpump2', ['pump1', 'pump2']), # the new pump1 builds report cdpump too
    'mdrv-pump':   ('cdpump1', ['pump1']),
    'cdcam':       ('cdcam', ['cam1', 'cam23']),
}
def hw_major(hw):
    """'v3.1', 'v1.10.2' (from the otp), 'v2', 'v1.xx' (older builds) -> the major, None for anything else ('err')"""
    m = re.fullmatch(r'v(\d+)(?:\.(?:\d+|x+)){0,2}', hw or '')
    return int(m[1]) if m else None

# a pump goes by its flash size: the pump1 bl and the old builds have no HW
CAM_HW = {1: 'cam1', 2: 'cam23', 3: 'cam23'}
# a cam without HW (otp never written) reports the same SW on both lines, the tag of its image tells
CAM_TAGS = {'cdcam1': 'cam1', 'cdcam3': 'cam23'}
# the bootloader is shared by the variants of a module
STEPS = {'step', 'step_r', 'step_z'}

def model_variants(info):
    return set(BL_MODELS.get(info.model, []) if info.bl else MODELS.get(info.model, (None, []))[1])

BL_MODELS = {
    'cdstep':    ['step', 'step_r', 'step_z'],
    'mdrv-step': ['step', 'step_r', 'step_z'],
    'cdpump':    ['pump1', 'pump2'],
    'mdrv-pump': ['pump1'],
    'cdcam':     ['cam1', 'cam23'],
}


logger = logging.getLogger('fw_update')
args = None


def say(*a, end='\n'):
    print(*a, end=end, flush=True)

def ask(question, default=False):
    if args.yes:
        return True
    yn = input(f'{question} [{"Y/n" if default else "y/N"}] ').strip().lower()
    return default if not yn else yn.startswith('y')


class UpdateError(Exception):
    pass

class BusError(UpdateError):
    pass


# ------------------------------------------------------------------ files

def load_hex(path):
    """intel hex -> [(addr, bytes)], contiguous segments"""
    mem = {}
    base = 0
    with open(path) as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            rec = bytes.fromhex(line[1:])
            if line[0] != ':' or sum(rec) & 0xff or len(rec) != rec[0] + 5:
                raise UpdateError(f'{path}:{ln}: bad record')
            n, addr, typ, dat = rec[0], rec[1] << 8 | rec[2], rec[3], rec[4:4+rec[0]]
            if typ == 0:
                for i, b in enumerate(dat):
                    mem[base + addr + i] = b
            elif typ == 1:
                break
            elif typ == 2:
                base = (dat[0] << 8 | dat[1]) << 4
            elif typ == 4:
                base = (dat[0] << 8 | dat[1]) << 16
    segs = []
    for a in sorted(mem):
        if segs and segs[-1][0] + len(segs[-1][1]) == a:
            segs[-1][1].append(mem[a])
        else:
            segs.append((a, bytearray([mem[a]])))
    return [(a, bytes(d)) for a, d in segs]


class Fw:
    def __init__(self, pattern, kind, app_addr=APP_ADDR):
        files = sorted(glob.glob(pjoin(FW_DIR, pattern)))
        if len(files) != 1:
            raise UpdateError(f'firmware/{pattern}: {len(files)} files, one expected')
        self.path = files[0]
        self.name = basename(self.path)
        m = re.search(r'_(v\d+\.\d+)_([0-9a-f]{7,40})\.hex$', self.name)
        self.ver, self.hash = (m[1], m[2]) if m else (None, None)
        self.segs = load_hex(self.path)
        pages = [set(range(a // PAGE, (a + len(d) - 1) // PAGE + 1)) for a, d in self.segs]
        for i in range(len(pages)):
            for j in range(i):
                if pages[i] & pages[j]:
                    raise UpdateError(f'{self.name}: segments share a flash page')
        if kind == 'app' and self.segs[0][0] < app_addr:
            raise UpdateError(f'{self.name}: starts at {self.segs[0][0]:08x}, the app at {app_addr:08x}: a bl image?')
        if kind == 'bl' and self.segs[-1][0] + len(self.segs[-1][1]) > app_addr:
            raise UpdateError(f'{self.name}: reaches into the app at {app_addr:08x}: not a bl image')

    def __str__(self):
        return f'{self.ver} ({self.hash})' if self.ver else self.name


def parse_ver(s):
    """'v3.2', 'cdcam3_v3.0-3-g05634f5', 'v5.1-17-g58b9a35', 'hw5_v7.0' -> (major, minor + count);
    a bare git hash (an old build) -> None"""
    m = re.search(r'v(\d+)\.(\d+)(?:-(\d+)-g[0-9a-f]{7,40})?(?:-dirty)?$', s or '')
    return (int(m[1]), int(m[2]) + int(m[3] or 0)) if m else None

def fmt_ver(v):
    return f'v{v[0]}.{v[1]}' if v else 'an old build'

def image_strs(img):
    return {m.group(1).decode() for m in re.finditer(rb'([\x20-\x7e]{4,})\x00', img)}

def image_cam_variant(img):
    """the cam variant an app image was built for, by the tag of its full git version, None if not told"""
    found = (re.fullmatch(r'(\w+)_v\d+\.\d+-\d+-g[0-9a-f]{7,40}(?:-dirty)?', x) for x in image_strs(img))
    tags = {m[1] for m in found if m}
    return CAM_TAGS.get(tags.pop()) if len(tags) == 1 else None

def image_version(img):
    """the version a firmware image reports, from the strings in it, None for a git hash"""
    strs = image_strs(img)
    full = {x for x in strs if re.fullmatch(r'(?:\w+_)?v\d+\.\d+-\d+-g[0-9a-f]{7,40}(?:-dirty)?', x)}
    if len(full) == 1:
        return parse_ver(full.pop())
    tags = {x for x in strs if re.fullmatch(r'(?:\w+_)?v\d+\.\d+', x)}
    return parse_ver(tags.pop()) if len(tags) == 1 and not full else None


def load_json5(path):
    """the cdbus gui configs: json with // comments, 0x numbers and trailing commas"""
    with open(path, encoding='utf-8') as f:
        s = f.read()
    try:
        import json5
        return json5.loads(s)
    except ImportError:
        pass
    str_re = r'"(?:\\.|[^"\\])*"'
    def sub1(m):
        t = m.group(0)
        return t if t[0] == '"' else '' if t[0] == '/' else str(int(t, 16))
    s = re.sub(str_re + r'|//[^\n]*|/\*.*?\*/|\b0[xX][0-9a-fA-F]+\b', sub1, s, flags=re.S)
    s = re.sub(str_re + r'|,(?=\s*[\]}])', lambda m: m.group(0) if m.group(0)[0] == '"' else '', s)
    return json.loads(s)


# ------------------------------------------------------------------ registers

_TSIZE = {'c': 1, 'b': 1, 'B': 1, 'h': 2, 'H': 2, 'i': 4, 'I': 4, 'f': 4, 'q': 8, 'Q': 8, 'd': 8}

def _fields(fmt):
    """'{H,B2}' -> [('H', 0), ('B', 2)]: type and offset of the fields of one element, element size"""
    f = re.sub(r'[\W_]', '', fmt)
    out, ofs, i = [], 0, 0
    while i < len(f):
        t = f[i]
        span = _TSIZE[t]
        if i + 1 < len(f) and f[i+1].isdigit():
            span = int(f[i+1])
            i += 1
        out.append((t, ofs))
        ofs += span
        i += 1
    return out, ofs


class Reg:
    def __init__(self, addr, len_, fmt, show, name):
        self.addr, self.len, self.fmt, self.show, self.name = addr, len_, fmt, show, name
        self.flds, self.esize = _fields(fmt)
        self.is_str = fmt.startswith('[c') and show != 1
        if self.len % self.esize:
            raise UpdateError(f'reg {name}: len {len_} does not fit {fmt}')

    def encode(self, s, cur):
        """value string as in a .mpk -> bytes, the bytes between the fields kept from cur"""
        dat = bytearray(cur)
        if self.is_str:
            b = s.encode()[:self.len]
            return bytes(b + bytes(self.len - len(b)))
        toks = s.split()
        n = 0
        for e in range(self.len // self.esize):
            for t, ofs in self.flds:
                if n >= len(toks):
                    raise UpdateError(f'{self.name}: "{s}": too few values')
                tok, o = toks[n], e * self.esize + ofs
                n += 1
                if t in 'fd':
                    v = float.fromhex(tok) if self.show == 1 and not re.fullmatch(r'-?\d+(\.\d*)?([eE][-+]?\d+)?', tok) \
                        else float(tok)
                    dat[o:o+_TSIZE[t]] = struct.pack('<' + t, v)
                elif self.show == 2 and t in 'bB':
                    dat[o] = bytes.fromhex(tok)[0]
                else:
                    tt = 'b' if t == 'c' else t
                    v = int(tok, 0)
                    if tt.isupper() and v < 0 or tt.islower() and v >= 1 << (_TSIZE[t] * 8 - 1):
                        v &= (1 << (_TSIZE[t] * 8)) - 1 # accept both spellings of the same bits
                        if tt.islower():
                            v -= (v >> (_TSIZE[t] * 8 - 1)) << (_TSIZE[t] * 8)
                    dat[o:o+_TSIZE[t]] = struct.pack('<' + tt, v)
        return bytes(dat)

    def mask(self):
        """the bytes the fields cover: the rest (padding) is not compared"""
        m = bytearray(self.len)
        if self.is_str:
            return bytes(b'\xff' * self.len)
        for e in range(self.len // self.esize):
            for t, ofs in self.flds:
                o = e * self.esize + ofs
                m[o:o+_TSIZE[t]] = b'\xff' * _TSIZE[t]
        return bytes(m)

    def same(self, a, b):
        return all((x ^ y) & k == 0 for x, y, k in zip(a, b, self.mask()))

    def decode(self, dat):
        if self.is_str:
            return dat.split(b'\0')[0].decode(errors='replace')
        out = []
        for e in range(self.len // self.esize):
            for t, ofs in self.flds:
                o = e * self.esize + ofs
                v = struct.unpack('<' + ('b' if t == 'c' else t), dat[o:o+_TSIZE[t]])[0]
                if self.show == 2:
                    out.append(f'{v & 0xff:02x}')
                elif self.show == 1 and t not in 'fd':
                    out.append(f'0x{v & ((1 << _TSIZE[t] * 8) - 1):0{_TSIZE[t] * 2}x}')
                else:
                    out.append(f'{v:.7g}' if t in 'fd' else str(v))
        return ' '.join(out)


class RegMap:
    def __init__(self, cfg_name):
        self.path = pjoin(CFG_DIR, cfg_name)
        cfg = load_json5(self.path)['reg']
        self.regs = {}
        for r in cfg['list']:
            addr, len_, fmt, show, name = r[:5]
            fsize = _fields(fmt)[1]
            if fmt.startswith('{') and len_ != fsize: # one register per element, as cdbus gui names them
                for n in range(len_ // fsize):
                    self.regs[f'{name}.{n}'] = Reg(addr + fsize * n, fsize, fmt, show, f'{name}.{n}')
            else:
                self.regs[name] = Reg(addr, len_, fmt, show, name)
        self.w_grps = [self._span(g) for g in cfg['reg_w']]

    def _span(self, g):
        def find(n):
            for k, r in self.regs.items():
                if k == n or k == f'{n}.0':
                    return r
            raise UpdateError(f'{self.path}: group member {n} not found')
        r0 = find(g[0])
        find(g[-1])
        last = max((r for k, r in self.regs.items() if k == g[-1] or k.startswith(g[-1] + '.')),
                   key=lambda r: r.addr)
        return (r0.addr, last.addr + last.len)

    def writable(self, reg):
        return any(a <= reg.addr and reg.addr + reg.len <= b for a, b in self.w_grps)


def load_mpk(name):
    with open(pjoin(CFG_DIR, name), 'rb') as f:
        dat = umsgpack.unpackb(f.read())
    return dat['reg']


# ------------------------------------------------------------------ bus

class Bus:
    """raw cdbus frames over the bridge: cdnet v2 L0 or cdnet v1 L1, host mac 0 (0xaa: a v4 bridge)"""
    PORT_V2 = 0x40      # our port for v2, v1 uses the default port 0xcdcd (left out of the frame)

    def __init__(self, dev, baud):
        self.dev = dev
        self.baud = baud

    def set_baud(self, baud):
        if baud == self.baud:
            return
        say(f'  (bus: {baud} bps)')
        if hasattr(self.dev, 'set_baud'):
            self.dev.set_baud(baud)
        else:
            self.dev.com.baudrate = baud # the bridge follows the line coding
        self.baud = baud
        if hasattr(self.dev, 'baud'):
            self.dev.baud = baud # CDBusSerial opens the port again at it, after the bridge rebooted
        time.sleep(0.3)
        self.flush()

    def flush(self):
        while self.dev.recv(timeout=0) is not None:
            pass

    def send(self, proto, mac, port, dat, host=0):
        hdr = bytes([0x80, port]) if proto == 1 else bytes([self.PORT_V2, port])
        payload = hdr + dat
        assert len(payload) <= 253
        self.dev.send(bytes([host, mac, len(payload)]) + payload)

    def _match(self, frame, proto, mac, port, host=0):
        if len(frame) < 5 or frame[0] != mac or frame[1] != host:
            return None
        p = frame[3:]
        if proto == 2 and not p[0] & 0x80 and p[0] == port and p[1] == self.PORT_V2:
            return p[2:]
        if proto == 1 and p[0] == 0x82 and p[1] == port: # src port 1 byte, dst default port
            return p[2:]
        return None

    def wait(self, want, timeout):
        """want: [(proto, mac, port[, host])] -> (index, data) of the first match, (None, None) on timeout"""
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return None, None
            frame = self.dev.recv(timeout=left)
            if frame is None:
                return None, None
            for i, w in enumerate(want):
                d = self._match(frame, *w)
                if d is not None:
                    return i, d
            if len(frame) > 5 and frame[1] == 0 and frame[3] == 64 and frame[4] == 9:
                logger.debug(f'dbg #{frame[0]:02x}: {frame[5:].decode(errors="replace").rstrip()}')

    def request(self, proto, mac, port, dat, timeout=0.2, retry=5, reply=True, host=0):
        for i in range(retry):
            self.flush()
            self.send(proto, mac, port, dat, host)
            if not reply:
                return None
            _, d = self.wait([(proto, mac, port, host)], timeout)
            if d:
                return d
            logger.debug(f'timeout: {mac:02x}:{port} {dat[:8].hex()}, retry {i + 1}')
        raise BusError(f'no reply from {mac:02x} port {port}')


class Node:
    """a module at one address, speaking one protocol"""
    def __init__(self, bus, mac, proto, host=0):
        self.bus, self.mac, self.proto, self.host = bus, mac, proto, host

    def _req(self, port, dat, timeout=0.2, retry=5, reply=True, check=True):
        d = self.bus.request(self.proto, self.mac, port, dat, timeout, retry, reply, self.host)
        if d is not None and check and d[0] & 0x0f: # v1: 0x80 | err, v2: err
            raise BusError(f'{self.mac:02x} port {port}: error status {d[0]:02x}')
        return d

    def info(self):
        d = self._req(1, b'' if self.proto == 2 else b'\x00', check=False)
        return (d[1:] if self.proto == 1 else d).decode(errors='replace')

    def reg_read(self, addr, n):
        d = self._req(5, b'\x00' + struct.pack('<HB', addr, n))
        if len(d) != n + 1:
            raise BusError(f'reg read {addr:04x}: {len(d) - 1} bytes')
        return d[1:]

    def reg_write(self, addr, dat, reply=True):
        self._req(5, b'\x20' + struct.pack('<H', addr) + dat, retry=1 if not reply else 5, reply=reply)

    def flash_read(self, addr, n):
        d = self._req(8, b'\x00' + struct.pack('<IB', addr, n))
        if len(d) != n + 1:
            raise BusError(f'flash read {addr:08x}: {len(d) - 1} bytes')
        return d[1:]

    def flash_write(self, addr, dat):
        """False on an error status: the doubleword was not erased, e.g. a retry of a write
        whose reply was lost; the caller reads back"""
        d = self._req(8, b'\x20' + struct.pack('<I', addr) + dat, check=False)
        return not d[0] & 0x0f

    def flash_erase(self, addr, n):
        pages = (addr % PAGE + n + PAGE - 1) // PAGE
        self._req(8, b'\x2f' + struct.pack('<II', addr, n), timeout=1 + 0.05 * pages, retry=3)

    def read_region(self, addr, n, progress=None):
        out = bytearray()
        while len(out) < n:
            out += self.flash_read(addr + len(out), min(BLK, n - len(out)))
            if progress:
                progress(len(out), n)
        return bytes(out)


def probe(bus, mac, timeout=0.25, tries=2, host=0):
    """ask both protocols at once -> (proto, info string), (None, None) if no reply
    (a v2 module drops the v1 frame: port 0; a v1 module drops the v2 L0 frame: reply bit)"""
    for _ in range(tries):
        bus.flush()
        bus.send(2, mac, 1, b'', host)
        bus.send(1, mac, 1, b'\x00', host)
        i, d = bus.wait([(2, mac, 1, host), (1, mac, 1, host)], timeout)
        if d is not None:
            if i == 1:
                if not d or d[0] != 0x80:
                    continue
                d = d[1:]
            return (2 if i == 0 else 1), d.decode(errors='replace')
    return None, None


class Info:
    def __init__(self, s):
        self.raw = s
        m = re.search(r'M:\s*([^;,]+)', s)
        self.model = m[1].strip() if m else ''
        self.bl = self.model.endswith('(bl)')
        if self.bl:
            self.model = self.model[:-4].strip()
        m = re.search(r'S:\s*([0-9a-fA-F]+)', s)
        self.serial = m[1].lower() if m else ''
        m = re.search(r'HW:\s*([^\s;,]+)', s)
        self.hw = m[1] if m else None
        m = re.search(r'SW:\s*([^\s;,]+)', s)
        self.sw = m[1] if m else ''
        m = re.search(r'(?:^|-g)([0-9a-f]{7,40})(?:-dirty)?$', self.sw)
        self.hash = m[1] if m else None


# ------------------------------------------------------------------ the work on one module

class Flasher:
    """writes the flash of self.node, page by page, read back"""

    def keep_bl(self, t, bl_end):
        """--keep-bl: True if the bl, other than the file, is not older than t.min_bl"""
        if self.info.bl:
            ver = parse_ver(self.info.sw)
        else:
            ver = image_version(self.node.read_region(0x08000000, bl_end - 0x08000000))
        if ver and ver >= parse_ver(t.min_bl):
            self.note.append(f'bl {fmt_ver(ver)} kept (the file has {t.bl.ver}), --keep-bl')
            return True
        self.note.append((f'bl {fmt_ver(ver)} is older than {t.min_bl}' if ver else 'the bl is an old build (a git hash)') +
                         ': updated in spite of --keep-bl')
        return False

    def same(self, fw, progress=None):
        total = sum(len(d) for _, d in fw.segs)
        done = 0
        for a, d in fw.segs:
            p = (lambda n, _t, base=done: progress(base + n, total)) if progress else None
            if self.node.read_region(a, len(d), p) != d:
                return False
            done += len(d)
        return True

    def write_fw(self, fw, label):
        for a, d in fw.segs:
            d = d + b'\xff' * (-len(d) % 8) # the flash is written by doublewords
            say(f'    {label}: erase {a:08x} +{len(d)}')
            self.node.flash_erase(a, len(d))
            first = a // PAGE * PAGE
            for page in range(first, a + len(d), PAGE):
                lo, hi = max(a, page), min(a + len(d), page + PAGE)
                self.write_page(lo, d[lo-a:hi-a], erase=page != first or lo == page)
                say(f'\r    {label}: write {(hi - a) * 100 // len(d):3d}%', end='')
            say(', read back ok')

    def write_page(self, addr, dat, erase=True):
        """write one page (or part of it), read back, redo the page on a mismatch"""
        for attempt in range(4):
            try:
                if attempt:
                    if not erase:
                        raise UpdateError(f'{addr:08x}: write failed, page shared, can not erase')
                    logger.warning(f'rewrite page {addr // PAGE * PAGE:08x}, attempt {attempt + 1}')
                    self.node.flash_erase(addr // PAGE * PAGE, PAGE)
                for o in range(0, len(dat), BLK):
                    self.node.flash_write(addr + o, dat[o:o+BLK])
                if self.node.read_region(addr, len(dat)) == dat:
                    return
            except BusError as err:
                logger.warning(f'{addr:08x}: {err}')
        raise UpdateError(f'flash write at {addr:08x} failed')


class Module(Flasher):
    def __init__(self, bus, addr, table, cache):
        self.bus = bus
        self.addr = addr
        self.mac = int(addr.split(':')[2], 16)
        self.allowed = DEVICES[addr]
        self.table = table
        self.cache = cache
        self.node = None        # where it answers now
        self.info = None
        self.where = None       # (mac, baud) it was found at, if not its own
        self.variant = None
        self.t = None
        self.todo = []
        self.cfg_diff = []
        self.note = []

    # -------- scan

    def find(self):
        self.bus.set_baud(BAUD)
        proto, s = probe(self.bus, self.mac)
        if not proto:
            return False
        self.node, self.info = Node(self.bus, self.mac, proto), Info(s)
        if self.info.bl: # just powered on: the bl starts the app within 2 s unless told to stay
            info = self.wait_for(False, 2.5)
            if info:
                self.info = info
        return True

    def find_default(self):
        """the module with the default config: config page erased or never written"""
        self.bus.set_baud(BAUD_DFT)
        proto, s = probe(self.bus, MAC_DFT, timeout=0.4, tries=3)
        if proto:
            self.node, self.info = Node(self.bus, MAC_DFT, proto), Info(s)
            self.where = (MAC_DFT, BAUD_DFT)
            return True
        self.bus.set_baud(BAUD)
        return False

    def attach(self):
        """make self.node usable: right baud rate"""
        self.bus.set_baud(self.where[1] if self.where else BAUD)

    def lookup_sw(self, family):
        """the variants an old build (SW: git hash) was made for, None if unknown or a new build"""
        if self.info.hash:
            hs = self.table['hash'].get(family, {})
            hit = [set(v) for k, v in hs.items() if k.startswith(self.info.hash)]
            return set.union(*hit) if hit else None
        return None

    def identify(self):
        info = self.info
        if len(info.serial) != 24:
            raise UpdateError(f'serial "{info.serial}" is not the 96 bit uid of an stm32: not a module this tool handles')
        if info.bl:
            cands = set(BL_MODELS.get(info.model, []))
            family = None
        else:
            family, cands = MODELS.get(info.model, (None, []))
            cands = set(cands)
        if not cands:
            raise UpdateError(f'unknown model "{info.model}"')
        if info.hw and info.model == 'cdcam':
            v = CAM_HW.get(hw_major(info.hw))
            if not v:
                raise UpdateError(f'unknown hardware "HW: {info.hw}" of {info.model}')
            cands &= {v}
        if family:
            sw = self.lookup_sw(family)
            if sw is not None:
                if not sw & set(TARGETS):
                    raise UpdateError(f'{info.sw} is firmware for {", ".join(sorted(sw))}, not supported')
                if sw & cands:
                    cands &= sw
        allowed = set(self.allowed)
        c = cands & allowed
        if not c:
            if cands <= STEPS and allowed <= STEPS: # the machine needs the variant of its place
                self.note.append(f'runs {"/".join(sorted(cands))} firmware, {self.addr} needs {list(allowed)[0]}')
                c = allowed
            else:
                raise UpdateError(f'{"/".join(sorted(cands))} does not belong at {self.addr}')
        if len(c) > 1 and len({TARGETS[v].flash_kb for v in c}) > 1: # a pump: g031 or g071
            self.attach()
            kb = self.flash_kb()
            c = {v for v in c if TARGETS[v].flash_kb == kb}
            if not c:
                raise UpdateError(f'flash size {kb} KiB: no firmware for it')
        if len(c) > 1 and info.serial in self.cache and self.cache[info.serial] in c:
            c = {self.cache[info.serial]}
        if len(c) > 1 and self.addr in args.variant:
            if args.variant[self.addr] not in c:
                raise UpdateError(f'--variant {args.variant[self.addr]}: not one of {sorted(c)}')
            c = {args.variant[self.addr]}
        if len(c) > 1 and c <= set(CAM_TAGS.values()):
            self.attach()
            v = image_cam_variant(self.node.read_region(APP_ADDR, min(TARGETS[x].conf_addr for x in c) - APP_ADDR))
            if v in c:
                c = {v}
        if len(c) > 1: # e.g. a cam in its bl, with an app of no known tag: compare the app with the files
            self.attach()
            for v in sorted(c):
                if self.same(TARGETS[v].load().app):
                    c = {v}
                    break
        if len(c) > 1:
            say(f'  {self.addr}: {info.raw}')
            say(f'  can not tell which firmware it needs: {", ".join(sorted(c))}')
            if args.yes:
                raise UpdateError(f'variant unknown, give it by --variant {self.addr[-2:]}=...')
            v = input(f'  firmware for {self.addr} ({"/".join(sorted(c))}, empty: skip): ').strip()
            if v not in c:
                raise UpdateError('skipped')
            c = {v}
        self.variant = c.pop()
        self.t = TARGETS[self.variant].load()
        self.cache[info.serial] = self.variant

    def flash_kb(self):
        return struct.unpack('<H', self.node.flash_read(FLASHSIZE_REG, 2))[0]

    def check_hw(self):
        kb = self.flash_kb()
        if kb != self.t.flash_kb:
            raise UpdateError(f'flash size {kb} KiB, {self.t.desc} needs {self.t.flash_kb} KiB: wrong hardware?')

    def conf_page_new(self):
        magic, ver = struct.unpack('<HH', self.node.flash_read(self.t.conf_addr, 4))
        return magic == 0xcdcd and ver in (self.t.conf_ver, self.t.conf_ver_common)

    def plan(self):
        t = self.t
        self.attach()
        self.check_hw()
        self.need_bl = args.force or not self.same(t.bl) and not (args.keep_bl and self.keep_bl(t, APP_ADDR))
        # an app that reports a git hash is an old build, the new ones report vX.Y
        self.need_app = args.force or bool(not self.info.bl and self.info.hash) or not self.same(t.app)
        self.conf_new = self.conf_page_new()
        self.mpk_name = self.allowed[self.variant]
        self.mpk = load_mpk(self.mpk_name)
        self.regmap = RegMap(t.cfg)
        self.conf_image() # check the .mpk early
        self.todo = []
        if self.need_bl:
            self.todo.append('bl')
        if not self.conf_new or self.where:
            self.todo.append('conf page')
        if self.need_app:
            self.todo.append('app')
        if self.info.bl and not self.todo:
            self.todo.append('boot app')
        if self.todo or not args.no_config:
            if not self.todo:
                self.cfg_diff = self.config_diff()
                if self.cfg_diff:
                    self.todo.append(f'config ({len(self.cfg_diff)} regs)')
            elif self.todo:
                self.todo.append('config')

    # -------- config

    def conf_regs(self):
        """the registers of the .mpk that are saved config: name, Reg"""
        out = []
        for name, val in self.mpk.items():
            r = self.regmap.regs.get(name)
            if r is None:
                raise UpdateError(f'{self.mpk_name}: {name} is not in {self.t.cfg}')
            if name in self.t.skip or not any(a <= r.addr and r.addr + r.len <= b for a, b in self.t.conf_ranges):
                continue
            if r.name.split('.')[0] in ('prj_conf_ver',) or not self.regmap.writable(r):
                continue
            out.append((name, r))
        return out

    def config_diff(self):
        diff = []
        for name, r in self.conf_regs():
            cur = self.node.reg_read(r.addr, r.len)
            new = r.encode(self.mpk[name], cur)
            if not r.same(cur, new):
                diff.append((name, r, cur, new))
        return diff

    def conf_image(self):
        """[0, _end_common) of the new layout: the bus config from the .mpk, zeros between"""
        t = self.t
        img = bytearray(t.end_common)
        img[0:4] = struct.pack('<HH', 0xcdcd, t.conf_ver_common)
        for name, r in self.regmap.regs.items():
            if r.addr >= 8 and r.addr + r.len <= t.end_common:
                if name not in self.mpk:
                    raise UpdateError(f'{self.mpk_name} lacks {name}, needed for the config page')
                img[r.addr:r.addr+r.len] = r.encode(self.mpk[name], img[r.addr:r.addr+r.len])
        return bytes(img + b'\xff' * (-len(img) % 8))

    # -------- flash

    def write_conf_page(self):
        img = self.conf_image()
        say(f'    conf page: {self.t.conf_addr:08x}, bus config of {self.mpk_name}')
        for attempt in range(4):
            try:
                self.node.flash_erase(self.t.conf_addr, PAGE)
                for o in range(0, len(img), BLK):
                    self.node.flash_write(self.t.conf_addr + o, img[o:o+BLK])
                if self.node.read_region(self.t.conf_addr, len(img)) == img:
                    return
            except BusError as err:
                logger.warning(f'conf page: {err}')
        raise UpdateError('conf page write failed')

    # -------- reboot

    def wait_for(self, want_bl, timeout, keep=False):
        """poll the module at its own address and the bus baud rate, return Info"""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            proto, s = probe(self.bus, self.node.mac, timeout=0.08, tries=1)
            if proto:
                info = Info(s)
                if info.bl == want_bl:
                    self.node = Node(self.bus, self.node.mac, proto)
                    if want_bl and keep:
                        self.node.reg_write(R_KEEP_BL, b'\x01') # an old app reboots without asking the bl to stay
                    return info
        return None

    def reboot(self, to_bl):
        """do_reboot: 1 to the bl and stay there, 2 to the app"""
        start, start_baud = self.node, self.bus.baud
        mark = not to_bl and not self.info.bl # app to app: only a marker the boot clears tells it went down
        for attempt in range(4):
            self.bus.set_baud(start_baud)
            try:
                if mark:
                    start.reg_write(R_MARK, b'\x5a')
                start.reg_write(R_REBOOT, b'\x01' if to_bl else b'\x02', reply=False)
            except BusError:
                pass
            time.sleep(0.05)
            # it comes back at its own address and baud rate, from the conf page
            self.bus.set_baud(BAUD)
            self.node = Node(self.bus, self.mac, start.proto)
            info = self.wait_for(to_bl, 4 if to_bl else 6, keep=to_bl)
            if info and not (mark and self.node.reg_read(R_MARK, 1)[0] == 0x5a):
                self.where = None
                self.info = info
                return info
            # still where it was: the reboot frame was lost, or the 2 s window of a bl started
            # without keep (an old app does not tell it to stay) was missed
            if info or self.wait_for(not to_bl, 0.5) or self.still_at(start, start_baud):
                say('    again')
                continue
            break
        raise UpdateError(f'no {"bootloader" if to_bl else "app"} at {self.addr} after the reboot')

    def still_at(self, node, baud):
        if (node.mac, baud) == (self.mac, BAUD):
            return False
        self.bus.set_baud(baud)
        return probe(self.bus, node.mac)[0] is not None

    # -------- run

    def run(self):
        t = self.t
        self.attach()
        say(f'\n== {self.addr} {t.desc}: {", ".join(self.todo)}')
        boot_new = any(x in self.todo for x in ('bl', 'app', 'conf page', 'boot app'))

        todo = list(self.todo)
        if 'bl' in todo and self.info.bl:
            # an old bl can not replace itself, and starting the app is a gamble on an app that
            # may be broken: write the new app and the conf page by this bl and boot the new app,
            # the old bl does not read the new page right, but it starts the app after its 2 s
            say(f'    in the old bootloader {self.info.sw}: write the new app by it first')
            self.write_fw(t.app, 'app')
            self.write_conf_page()
            todo = [x for x in todo if x not in ('app', 'conf page')]
            say('    boot the new app')
            self.reboot(False)

        if 'bl' in todo:
            say(f'    bl: {t.bl.name}, from app {self.info.sw}')
            self.write_fw(t.bl, 'bl')

        if 'conf page' in todo:
            self.write_conf_page()
            if self.where and self.info.bl: # to its own address and baud rate before the app
                self.reboot(True)

        if 'app' in todo:
            if not self.info.bl:
                say('    reboot to the bootloader')
                self.reboot(True)
            say(f'    app: {t.app.name}, by bl {self.info.sw}')
            self.write_fw(t.app, 'app')

        if boot_new:
            say('    boot the app')
            info = self.reboot(False)
            say(f'    app: {info.raw}')
            if t.app.ver and info.sw != t.app.ver:
                raise UpdateError(f'app reports {info.sw}, {t.app.ver} expected')

        if boot_new or self.cfg_diff:
            self.apply_config()

    def apply_config(self):
        diff = self.config_diff()
        conf_from = self.node.reg_read(R_CONF_FROM, 1)[0]
        say(f'    config: {self.mpk_name}, conf_from: {conf_from}, {len(diff)} regs to write')
        for name, r, cur, new in diff:
            say(f'      {name}: {r.decode(cur)} -> {r.decode(new)}')
            self.node.reg_write(r.addr, new)
        left = self.config_diff()
        if left:
            raise UpdateError(f'config not taken: {", ".join(n for n, *_ in left)}')
        self.node.reg_write(R_SAVE_CONF, b'\x01')
        time.sleep(0.5)
        say('    saved, reboot to check')
        self.reboot(False)
        conf_from = self.node.reg_read(R_CONF_FROM, 1)[0]
        left = self.config_diff()
        if conf_from != 1 or left:
            raise UpdateError(f'after reboot: conf_from {conf_from}, differs: {", ".join(n for n, *_ in left)}')
        say(f'    ok: {self.info.raw}')


def port_vid(dev):
    from serial.tools import list_ports
    for p in list_ports.comports():
        if p.device == dev.portstr:
            return p.vid
    return None


class Bridge(Flasher):
    """the cdbus bridge we talk through, its own firmware: at the baud rate 0xcdcd the port talks
    to the bridge (v5 on), its bl answers at any rate. A reboot of it drops the usb port, the
    serial device opens it again when it is back (the pid of the hw v6 bl and app differ)."""
    # where it answers: v7 on and every new bl; v5 / v6 (cdnet v1); v4 (forwarding mode, host 0xaa)
    PLACES = [(0xff, 0), (0xfe, 0), (0x55, 0xaa)]

    def __init__(self, bus, dev):
        self.bus, self.dev = bus, dev
        self.node = self.info = self.t = None
        self.todo = []
        self.note = []

    def look(self, timeout=0.25, tries=2):
        for mac, host in self.PLACES:
            proto, s = probe(self.bus, mac, timeout, tries, host)
            if proto:
                return Node(self.bus, mac, proto, host), Info(s)
        return None, None

    def find(self):
        self.bus.set_baud(BAUD_CONF)
        self.node, self.info = self.look()
        return self.node is not None

    @property
    def gen(self):
        return 'v4, forwarding mode' if self.node.host else f'cdnet v{self.node.proto}'

    def identify(self):
        vid = port_vid(self.dev)
        if vid not in BRIDGES:
            raise UpdateError(f'usb vid {vid:04x}: not a cdbus bridge this tool knows' if vid else 'usb vid unknown')
        if self.info.model != 'cdbus bridge':
            raise UpdateError(f'model "{self.info.model}": not a cdbus bridge')
        t = BRIDGES[vid].load()
        if self.info.hw == 'err':
            self.note.append('HW: err, its bus controller was not recognized: the bus is down')
        elif self.info.hw and hw_major(self.info.hw) not in t.hw:
            raise UpdateError(f'reports HW: {self.info.hw}, but the usb vid says {t.desc}')
        self.t = t

    def plan(self):
        t = self.t
        if t.flash_kb:
            kb = struct.unpack('<H', self.node.flash_read(FLASHSIZE_REG, 2))[0]
            if kb != t.flash_kb:
                raise UpdateError(f'flash size {kb} KiB, {t.desc} has {t.flash_kb} KiB: wrong hardware?')
        need_bl = args.force or not self.same(t.bl) and not (args.keep_bl and self.keep_bl(t, t.app_addr))
        # an app that reports a git hash is an old build
        need_app = args.force or bool(not self.info.bl and self.info.hash) or not self.same(t.app)
        magic, ver = struct.unpack('<HH', self.node.flash_read(t.conf_addr, 4))
        self.conf_new = magic == 0xcdcd and ver == t.conf_ver
        self.todo = (['bl'] if need_bl else []) + (['app'] if need_app else [])
        if need_app and not self.conf_new:
            # nothing of cdpnp in it: the port sets the bus baud rate, S1.2 the arbitration limit
            self.todo.append('config: defaults')
        if self.info.bl and not self.todo:
            self.todo.append('start app')

    # -------- reboot: the usb port goes away and comes back

    def wait_mode(self, want_bl, timeout):
        lg = logging.getLogger('cdnet.dev.serial')
        level = lg.level
        lg.setLevel(logging.ERROR) # the port is away for a while
        try:
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if not self.dev.online:
                    time.sleep(0.1)
                    continue
                node, info = self.look(timeout=0.1, tries=1)
                if node and info.bl == want_bl:
                    self.node, self.info = node, info
                    return True
            return False
        finally:
            lg.setLevel(level)

    def reboot(self, val):
        try:
            self.node.reg_write(R_REBOOT, bytes([val]), reply=False)
        except BusError:
            pass
        time.sleep(0.5)

    def enter_bl(self):
        say('    reboot the bridge to its bootloader')
        for attempt in range(2):
            self.reboot(1)
            if self.wait_mode(True, 10):
                return
            self.wait_mode(False, 5)
        # an app from before the reboot selection: its bl does not stay
        say('    the bridge does not stay in its bootloader: switch S1.1 ON (the one nearest the usb port)')
        if args.yes:
            raise UpdateError('switch S1.1 on, run it again, then switch it off when asked')
        input('    press enter when it is on ')
        self.reboot(1)
        if not self.wait_mode(True, 10):
            raise UpdateError('no bootloader after the reboot')

    def start_app(self):
        say('    start the app of the bridge')
        self.reboot(2)
        if self.wait_mode(False, 10):
            return
        if self.wait_mode(True, 1):
            say('    the bridge stays in its bootloader: switch S1.1 OFF, it starts the app then')
            if self.wait_mode(False, 120):
                return
        raise UpdateError('the app of the bridge does not start')

    def erase_conf(self):
        say(f'    config: erase {self.t.conf_addr:08x}, the new app starts with the defaults')
        self.node.flash_erase(self.t.conf_addr, PAGE)

    def run(self):
        t = self.t
        say(f'\n== bridge, {t.desc}: {", ".join(self.todo)}')
        todo = list(self.todo)
        if 'bl' in todo and self.info.bl:
            # a bl can not replace itself: the new app first, by this bl, then the bl by the new app
            say(f'    in the old bootloader {self.info.sw}: write the new app by it first')
            self.write_fw(t.app, 'app')
            if not self.conf_new:
                self.erase_conf()
            todo = [x for x in todo if x not in ('app', 'config: defaults')]
            self.start_app()
        if 'bl' in todo:
            say(f'    bl: {t.bl.name}, from app {self.info.sw}')
            self.write_fw(t.bl, 'bl')
        if 'app' in todo:
            self.enter_bl()
            say(f'    app: {t.app.name}, by bl {self.info.sw}')
            self.write_fw(t.app, 'app')
            if 'config: defaults' in todo:
                self.erase_conf()
        self.start_app() # also tries a new bl out
        if t.app.ver and self.info.sw != t.app.ver:
            raise UpdateError(f'the app reports {self.info.sw}, {t.app.ver} expected')
        say(f'    ok: {self.info.raw}')


def rescue_powerup(bus, mods, table, cache):
    """modules that do not answer: catch their bootloader while the machine is power cycled"""
    say(f'\nnot found: {", ".join(mods)}')
    if args.yes or not ask('power cycle the machine to catch their bootloader?', False):
        return []
    bus.set_baud(BAUD)
    say('switch the machine off and on now, waiting 30 s ...')
    found = []
    left = set(mods)
    end = time.monotonic() + 30
    while left and time.monotonic() < end:
        for addr in sorted(left):
            mac = int(addr.split(':')[2], 16)
            proto, s = probe(bus, mac, timeout=0.03, tries=1)
            if proto and Info(s).bl:
                Node(bus, mac, proto).reg_write(R_KEEP_BL, b'\x01')
                m = Module(bus, addr, table, cache)
                m.find()
                say(f'  {addr}: {m.info.raw}')
                found.append(m)
                left.discard(addr)
    return found


# ------------------------------------------------------------------ main

def do_bridge(bus, dev):
    """the bridge first: the modules need its v7 firmware or later (the port sets the bus baud rate),
    and a v4 bridge does not even pass the frames through. False: stop"""
    bridge = Bridge(bus, dev)
    say('scan the bridge ...')
    if not bridge.find():
        say('the bridge does not answer in config mode (baud rate 0xcdcd)')
        return ask('go on with the modules?', False)
    try:
        bridge.identify()
        bridge.plan()
    except UpdateError as err:
        bridge.todo = None
        bridge.note.append(str(err))
    say(f'bridge    {bridge.info.model}{" (bl)" if bridge.info.bl else ""} {bridge.info.sw}  [{bridge.gen}]')
    if bridge.t:
        say(f'          -> {bridge.t.desc}: app {bridge.t.app}, bl {bridge.t.bl}')
    if bridge.todo is not None:
        say(f'          to do: {", ".join(bridge.todo) or "nothing"}')
    for n in bridge.note:
        say(f'          ! {n}')
    old = bridge.node.host or bridge.node.proto == 1 # v4 / v5 / v6
    if bridge.todo and not args.scan:
        say('\nKeep the bridge plugged in until it is done.')
        if ask('update the bridge first?', True):
            try:
                bridge.run()
                return True
            except UpdateError as err:
                say(f'\n    !! bridge: {err}')
                say('run it again. If the bridge does not show up any more, switch S1.1 ON to start its '
                    'bootloader, run it again, and switch S1.1 OFF when asked')
                return False
    if old:
        say('the modules need the bridge firmware v7 or later' +
            (': a v4 bridge does not pass the frames through, stop' if bridge.node.host else ''))
        return not bridge.node.host
    return True


def main():
    global args
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tty', metavar='PORT',
                    help='serial port or filter (default: the bridge, 2E3C:574 hw v6, or 0483:574 hw v4 / v5)')
    ap.add_argument('--dev', action='append', default=[], metavar='ADDR',
                    help='only this module, repeatable: --dev 00:00:21 or --dev 21')
    ap.add_argument('--variant', action='append', default=[], metavar='A=V',
                    help='firmware for module A when it can not be told, e.g. 21=cam1 (cam1, cam23)')
    ap.add_argument('--scan', action='store_true', help='only show what is found and what would be done')
    ap.add_argument('--force', action='store_true', help='rewrite bl and app even when they are the same as the files')
    ap.add_argument('--no-config', action='store_true',
                    help='leave the config of modules that need no firmware update alone')
    ap.add_argument('--keep-bl', action='store_true',
                    help='keep a bl that is not too old (the minimum each board needs with these files), '
                         'a power loss while a bl is written bricks the board')
    ap.add_argument('--skip-bridge', action='store_true', help='leave the firmware of the cdbus bridge alone')
    ap.add_argument('--yes', action='store_true', help='do not ask')
    ap.add_argument('-v', action='store_true', help='show the bus traffic')
    args = ap.parse_args()

    def full_addr(a):
        a = a.lower()
        return a if a.count(':') == 2 else f'00:00:{int(a, 16):02x}'
    try:
        args.variant = {full_addr(a): v for a, v in (x.split('=') for x in args.variant)}
        addrs = [full_addr(a) for a in args.dev] or list(DEVICES)
    except ValueError:
        ap.error('bad --dev / --variant')
    for a in addrs + list(args.variant):
        if a not in DEVICES:
            ap.error(f'{a}: not a module of cdpnp ({", ".join(DEVICES)})')

    logger_init(logging.VERBOSE if args.v else logging.WARNING)
    if args.v:
        logging.getLogger('fw_update').setLevel(logging.DEBUG)

    with open(pjoin(FW_DIR, 'fw_hashes.json')) as f:
        table = json.load(f)
    try:
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}

    tty = args.tty or next((f for f in ('2E3C:574', '0483:574') if get_port(f)), None)
    if not tty:
        say('no cdbus bridge found, serial ports:')
        for p in get_ports():
            say(f'  {p}')
        return 1
    dev = CDBusSerial(tty, baud=BAUD)
    if not dev.online:
        say(f'can not open {tty}')
        return 1
    bus = Bus(dev, BAUD)
    say(f'port: {dev.portstr}')

    if not args.skip_bridge and not do_bridge(bus, dev):
        return 1

    bus.set_baud(BAUD)
    say('scan the modules ...')
    mods, missing, failed = [], [], []
    for addr in addrs:
        m = Module(bus, addr, table, cache)
        if not m.find():
            missing.append(m)
            continue
        mods.append(m)
    if missing: # one more time: a module in its first second after power on talks at 115200
        time.sleep(1)
        for m in list(missing):
            if m.find():
                missing.remove(m)
                mods.append(m)
    # one module at the default address can be one of the missing ones
    if missing:
        m0 = missing[0]
        if m0.find_default():
            say(f'found at 00:00:fe {BAUD_DFT} bps: {m0.info.raw}')
            vs = model_variants(m0.info)
            names = [m.addr for m in missing if vs & set(m.allowed) or (vs and vs <= STEPS and set(m.allowed) <= STEPS)]
            a = ''
            if len(names) == 1 and args.yes:
                a = names[0]
            elif names and not args.yes:
                a = input(f'which module is it ({", ".join(names)}, empty: none)? ').strip()
                a = full_addr(a) if a else ''
            for m in missing:
                if m.addr == a and a in names:
                    m.node, m.info, m.where = m0.node, m0.info, m0.where
                    missing.remove(m)
                    mods.append(m)
                    break
            bus.set_baud(BAUD)
    if missing and not args.scan:
        mods += rescue_powerup(bus, [m.addr for m in missing], table, cache)
        missing = [m for m in missing if m.addr not in {x.addr for x in mods}]
    mods.sort(key=lambda m: m.addr)

    say('')
    for m in mods:
        try:
            m.identify()
            m.plan()
        except (UpdateError, BusError) as err:
            m.todo = None
            m.note.append(str(err))
            failed.append(m)
        proto = f'cdnet v{m.node.proto}' + (f', at 00:00:fe {BAUD_DFT}' if m.where else '')
        say(f'{m.addr}  {m.info.model}{" (bl)" if m.info.bl else ""} {m.info.sw}  [{proto}]')
        if m.t:
            say(f'          -> {m.t.desc}: app {m.t.app}, bl {m.t.bl}')
        if m.todo is not None:
            say(f'          to do: {", ".join(m.todo) or "nothing"}')
            for name, r, cur, new in m.cfg_diff:
                say(f'            {name}: {r.decode(cur)} -> {r.decode(new)}')
        for n in m.note:
            say(f'          ! {n}')
    for m in missing:
        say(f'{m.addr}  not found')
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=1)

    work = [m for m in mods if m.todo]
    if args.scan or not work:
        say('\nnothing to do.' if not work else '')
        return 1 if failed or missing else 0
    say('\nKeep the machine powered and the cable in place until it is done.')
    if not ask(f'update {", ".join(m.addr for m in work)}?'):
        return 1

    for m in work:
        try:
            m.run()
        except (UpdateError, BusError) as err:
            say(f'\n    !! {m.addr}: {err}')
            failed.append(m)
            if not ask('    go on with the next module?', True):
                break
    say('\n' + ('failed: ' + ', '.join(m.addr for m in failed) if failed else 'all done.'))
    if failed:
        say('run it again: it picks up where a module is now. A module that does not answer at all can be caught '
            'in its bootloader by power cycling the machine when asked.')
    return 1 if failed or missing else 0


if __name__ == '__main__':
    sys.exit(main())
