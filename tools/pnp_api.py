#!/usr/bin/env python3
#
# Software License Agreement (MIT License)
#
# Author: Duke Fong <d@d-l.io>

"""Client for the CDPNP external API (see api_serve.py and doc/api.md).

The backend (pnp_main.py) must be running. The machine calls work on their
own; the page calls (cfg, comps, run ...) need http://localhost:8900 opened
in the browser, and a move, pump or camera call goes through the page
whenever it is opened, so what the page shows stays true.

Standalone use prints the state, or saves a frame:
  ./pnp_api.py [--url http://localhost:8901]
  ./pnp_api.py --frame out.png [--raw] [--wait]
"""

import sys
import json
import urllib.request
import urllib.parse
import urllib.error


class PnpApi:
    def __init__(self, url='http://localhost:8901', timeout=320):
        self.url = url.rstrip('/') + '/api'
        self.timeout = timeout

    def _req(self, method, path, query=None, body=None, raw=False):
        url = self.url + path
        if query:
            url += '?' + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        if body is not None and not isinstance(body, (bytes, str)):
            body = json.dumps(body)
        dat = None if body is None else (body if isinstance(body, bytes) else body.encode())
        req = urllib.request.Request(url, data=dat, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as f:
                if raw:
                    return f.read(), dict(f.headers)
                text = f.read().decode()
        except urllib.error.HTTPError as err:
            raise RuntimeError(err.read().decode().strip()) from None
        try:
            return json.loads(text)
        except ValueError:
            return text.strip()

    # ---------------------------------------------------------- the machine

    def state(self):
        """Everything at a glance: dev, page, pos, pump, camera, cv, and page_state when
        the page is opened."""
        return self._req('GET', '/state')

    def pos(self):
        """[x, y, z, r] read from the motors: mm, mm, mm (z <= 0), degrees."""
        return self._req('GET', '/pos')

    def move(self, pos=None, delta=None, wait=100, speed=None):
        """Move to `pos` (an axis given as None keeps its value) and / or by `delta`.
        wait: percent of the way to wait for before returning, 0 returns at once,
        100 waits until every motor stopped. Returns the position after."""
        body = {'wait': wait}
        if pos is not None:
            body['pos'] = list(pos)
        if delta is not None:
            body['delta'] = list(delta)
        if speed is not None:
            body['speed'] = speed
        return self._req('POST', '/pos', None, body)

    def pump(self):
        return self._req('GET', '/pump')

    def set_pump(self, val):
        """hw v1: 0 off, 1 valve on, 2 pump on; hw v2: target pressure, -70 sucks, 0 off.
        Returns the pressure after."""
        return self._req('POST', '/pump', None, {'val': val})

    def camera(self):
        return self._req('GET', '/camera')

    def set_camera(self, **kw):
        """set_camera(dev=1, enable=True, detect='default', light1=False, light2=False, expos=20).
        Returns the camera state after."""
        return self._req('POST', '/camera', None, kw)

    def camera_bg(self, update=True):
        """Take the next frame of camera 1 as the background to subtract, or remove it."""
        return self._req('POST', '/camera/bg', None, 'update' if update else 'remove')

    def set_vision(self, nozzle_thresh=None, debug=None):
        body = {k: v for k, v in (('nozzle_thresh', nozzle_thresh), ('debug', debug)) if v is not None}
        return self._req('POST', '/vision', None, body)

    def cv(self):
        """What the vision code found in the last frame: {'cur': [x_px, y_px, angle, dist] or
        None, 'offset_mm': [dx, dy] from the image center, 'seq', 'ts', 'dev', 'detect',
        'width', 'height', 'mm_per_pixel'}."""
        return self._req('GET', '/cv')

    def frame(self, raw=False, wait=False, min_seq=None, timeout=3, path=None):
        """The last frame: annotated png, or the camera's own jpg with raw=True. wait=True
        waits for the next frame to come in, min_seq for one at or after that number.
        Returns (bytes, info) with info {'seq', 'ts', 'dev', 'detect', 'cv'}, and writes
        the bytes to `path` when given."""
        q = {'type': 'raw' if raw else 'cv', 'wait': 1 if wait else None, 'min_seq': min_seq,
             'timeout': timeout}
        dat, hdr = self._req('GET', '/frame', q, raw=True)
        info = {'seq': int(hdr['X-Frame-Seq']), 'ts': float(hdr['X-Frame-Ts']),
                'dev': int(hdr['X-Frame-Dev']), 'detect': hdr['X-Frame-Detect'],
                'cv': json.loads(hdr['X-Frame-Cv'])}
        if path:
            with open(path, 'wb') as f:
                f.write(dat)
        return dat, info

    def snap(self, times=3, max_err=0.02):
        """Center the camera on the detected part, the Snap step of the run (page needed).
        Returns {'found', 'pos', 'angle'}."""
        return self._req('POST', '/snap', None, {'times': times, 'max_err': max_err})

    def pcb2xyz(self, pcb, cam, x, y):
        """Machine coordinates [x, y, angle] of pcb point (x, y), given the two fiducials
        in pcb coordinates and where the camera found them."""
        return self._req('POST', '/pcb2xyz', None, {'pcb': pcb, 'cam': cam, 'x': x, 'y': y})

    def wait_stop(self):
        return self._req('POST', '/wait_stop', None, '')

    def force(self):
        """Arm the z force sensor: the next move down stops when the nozzle touches."""
        return self._req('POST', '/force', None, '')

    # ---------------------------------------------------------- the page

    def page(self):
        """The page's state: cur_pos, camera, run (running, pause, step, board, comp ...), cfg."""
        return self._req('GET', '/page')

    def cfg(self):
        return self._req('GET', '/page/cfg')

    def set_cfg(self, vals=None, save=False, **kw):
        """set_cfg(motor_speed=0.5) or set_cfg({'grab_ofs': [33.5, 6.4]}); not kept across a
        page reload unless save=True. Returns the config after."""
        vals = dict(vals or {}, **kw)
        return self._req('POST', '/page/cfg', None, {'vals': vals, 'save': save})

    def comps(self):
        """{'list': {footprint: {value: [[name, x, y, angle], ...]}}, 'comp': selected, 'board'}"""
        return self._req('GET', '/page/comps')

    def select(self, comp, goto=False):
        """Select a component, and move the camera to it with goto=True."""
        return self._req('POST', '/page/select', None, {'comp': comp, 'goto': goto})

    def run(self):
        return self._req('POST', '/page/run', None, '')

    def pause(self, en=True):
        return self._req('POST', '/page/pause', None, {'en': en})

    def stop(self):
        return self._req('POST', '/page/stop', None, '')

    def step(self, idx):
        """0 show_target, 1 goto_comp, 2 snap, 3 pickup, 4 check, 5 goto_pcb, 6 put_down"""
        return self._req('POST', '/page/step', None, {'idx': idx})

    def board(self, idx):
        return self._req('POST', '/page/board', None, {'idx': idx})


if __name__ == '__main__':
    args = sys.argv[1:]
    def opt(name, dft=None):
        if name in args:
            i = args.index(name)
            return args[i + 1] if i + 1 < len(args) else dft
        return dft
    a = PnpApi(opt('--url', 'http://localhost:8901'))
    path = opt('--frame')
    if path:
        dat, info = a.frame(raw='--raw' in args, wait='--wait' in args, path=path)
        print(f'{len(dat)} bytes to {path}: {info}')
    else:
        print(json.dumps(a.state(), indent=2))
