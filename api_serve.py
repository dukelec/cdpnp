#!/usr/bin/env python3
#
# Software License Agreement (MIT License)
#
# Author: Duke Fong <d@d-l.io>
#
# External control API, for scripts and AI agents (see doc/api.md):
#
#   script --HTTP--> api_serve --+--> dev service (pnp_main.py) --> motors, pump, cameras
#                                |
#                                +--> web page in the browser --> the page's own functions
#
# The machine itself (motors, pump, camera settings, the camera frames and what the vision
# code found in them) is driven by the backend, so those calls work with no page opened.
# They go through the same 'dev' service queue as the page's own requests, one after the
# other, so a script and the user never talk to the bus at the same time.
#
# What lives in the page (the config values, the component list, the run / pause / step
# state) is reached by relaying a command to the page, which runs the same functions the
# buttons run. A move, pump or camera call also goes through the page whenever it is opened,
# so the position and the check boxes the page shows stay true.

import asyncio
import json
import logging
import umsgpack
from urllib.parse import urlsplit
from aiohttp import web
import cv2 as cv
from cd_ws import CDWebSocket
from web_serve import ws_ns
from pnp_cv import cv_dat

logger = logging.getLogger('cdpnp.api')

MM_PER_PIXEL = 10 / 344     # of camera 1 at its working height, the page's starting value (it refines it, see
                            # cam_scale in GET /api/page)
CAM_SIZE = {1: (600, 800), 2: (800, 600)}   # (width, height) of the annotated image of each camera

# the page clamps a target the same way (dev_cmd.js set_motor_pos), applied here for a move
# that does not go through the page: a script must not be able to drive an axis into its end
POS_LIMIT = [(2, 300), (2, 249), (-92, -2), (None, None)]

api = {
    'has_dev': False,   # the backend runs with hardware (--dev not None)
    'sock': None,       # CDWebSocket on port 'api', the page side relay
    'page': None,       # what the page said in its hello, None until it did
    'waits': {},        # page request id: future
    'dev_waits': {},    # dev request port: future
    'id': 0
}


# ------------------------------------------------------------ the dev service

class DevConn:
    """Stands in for a websocket in ws_ns.connections under the name 'api': a reply the dev
    service sends to ('api', port) lands here and wakes the request that waits on port."""
    async def send(self, msg):
        msg = umsgpack.unpackb(msg)
        fut = api['dev_waits'].get(msg['dst'][1])
        if fut and not fut.done():
            fut.set_result(msg['dat'])
        else:
            logger.warning(f'drop late dev reply: {msg["dst"]}')


async def dev_call(action, timeout=20, **args):
    """One request to the dev service, as the page would send it, the reply as it would get."""
    sock = ws_ns.sockets.get('dev')
    if not sock:
        raise web.HTTPServiceUnavailable(text='err: the dev service is not running\n')
    api['id'] = (api['id'] + 1) & 0xffffff
    port = f'api{api["id"]}'
    fut = asyncio.get_running_loop().create_future()
    api['dev_waits'][port] = fut
    logger.info(f'dev: {action} {brief(args)}')
    sock.recv_q.put_nowait(({'action': action, **args}, ('api', port)))
    try:
        ret = await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        raise web.HTTPGatewayTimeout(text=f'err: the dev service did not answer "{action}" in {timeout}s\n')
    finally:
        api['dev_waits'].pop(port, None)
    if isinstance(ret, str) and ret.startswith('err:'):
        raise web.HTTPBadRequest(text=f'{ret}\n')
    return ret


# ------------------------------------------------------------ the page

def page_opened():
    return '/' in ws_ns.connections and api['page'] is not None


def need_page():
    if not page_opened():
        raise web.HTTPNotFound(text='err: the page is not opened, this call needs it: open '
                                    'http://localhost:8900 in the browser\n')


async def page_call(cmd, args=None, timeout=20):
    need_page()
    api['id'] = (api['id'] + 1) & 0xffffff
    rid = api['id']
    fut = asyncio.get_running_loop().create_future()
    api['waits'][rid] = fut
    logger.info(f'page: {cmd} {brief(args or {})}')
    try:
        ret = await api['sock'].sendto({'id': rid, 'cmd': cmd, 'args': args or {}}, ('/', 'api'))
        if ret:
            raise web.HTTPServiceUnavailable(text=f'err: send to page failed: {ret}\n')
        rep = await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        raise web.HTTPGatewayTimeout(text=f'err: the page did not answer "{cmd}" in {timeout}s\n')
    finally:
        api['waits'].pop(rid, None)
    if rep.get('err'):
        logger.warning(f'page: {cmd} err: {rep["err"]}')
        raise web.HTTPBadRequest(text=f'err: {rep["err"]}\n')
    return rep.get('ret')


async def api_service():
    sock = api['sock']
    while True:
        dat, src = await sock.recvfrom()
        if not isinstance(dat, dict):
            logger.warning(f'bad msg from {src}: {dat}')
            continue
        if dat.get('cmd') == 'hello':
            api['page'] = dat.get('args') or {}
            logger.info(f'page online: {api["page"]}')
            await sock.sendto({'ok': True}, src)
            continue
        fut = api['waits'].get(dat.get('id'))
        if fut and not fut.done():
            fut.set_result(dat)
        else:
            logger.warning(f'drop late page reply: {dat.get("id")}')


# ------------------------------------------------------------ helpers

def brief(v, n=100):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + '...'


async def body_json(request, what='a json object'):
    text = (await request.text()).strip()
    if not text:
        return {}
    try:
        val = json.loads(text)
    except Exception as err:
        raise web.HTTPBadRequest(text=f'err: body is not json: {err}\n')
    if not isinstance(val, dict):
        raise web.HTTPBadRequest(text=f'err: body must be {what}\n')
    return val


async def body_value(request, key='val'):
    """A bare value, or {"val": value}."""
    text = (await request.text()).strip()
    if not text:
        raise web.HTTPBadRequest(text=f'err: body is empty, send a value or {{"{key}": value}}\n')
    try:
        val = json.loads(text)
    except Exception:
        raise web.HTTPBadRequest(text=f'err: body is not a value: {text}\n')
    if isinstance(val, dict):
        if key not in val:
            raise web.HTTPBadRequest(text=f'err: "{key}" missing in body\n')
        val = val[key]
    return val


def q_int(request, key, dft=None):
    v = request.query.get(key)
    if v is None or v == '':
        return dft
    try:
        return int(v, 0)
    except ValueError:
        raise web.HTTPBadRequest(text=f'err: "{key}" is not an integer: {v}\n')


def q_float(request, key, dft=None):
    v = request.query.get(key)
    if v is None or v == '':
        return dft
    try:
        return float(v)
    except ValueError:
        raise web.HTTPBadRequest(text=f'err: "{key}" is not a number: {v}\n')


def as_bool(v):
    if isinstance(v, str):
        return v.strip().lower() not in ('0', 'false', 'off', 'no', '')
    return bool(v)


def num_list(v, n, what):
    if not isinstance(v, list) or len(v) != n:
        raise web.HTTPBadRequest(text=f'err: {what} must be a list of {n} numbers\n')
    for x in v:
        if x is not None and not isinstance(x, (int, float)):
            raise web.HTTPBadRequest(text=f'err: {what} must be a list of {n} numbers\n')
    return v


def as_text(val):
    if isinstance(val, str):
        return web.Response(text=val if val.endswith('\n') else val + '\n')
    return web.json_response(val)


def cv_info():
    """What the vision code found in the last frame, with the frame it belongs to."""
    last = cv_dat['last']
    if last is None:
        return {'cur': None, 'comps': [], 'seq': 0, 'ts': None, 'dev': cv_dat['dev'], 'detect': cv_dat['detect'],
                'width': CAM_SIZE[cv_dat['dev']][0], 'height': CAM_SIZE[cv_dat['dev']][1],
                'mm_per_pixel': MM_PER_PIXEL}
    h, w = last['img'].shape[:2]
    cur = last['cur']
    return {'cur': cur, 'comps': last['comps'], 'seq': last['seq'], 'ts': last['ts'], 'dev': last['dev'], 'detect': last['detect'],
            'width': w, 'height': h, 'mm_per_pixel': MM_PER_PIXEL,
            # the same thing in mm from the image center, the way the page moves the camera onto it
            'offset_mm': [round((cur[0] - w / 2) * MM_PER_PIXEL, 4),
                          round((cur[1] - h / 2) * MM_PER_PIXEL, 4)] if cur else None}


async def camera_get():
    cfg = await dev_call('get_camera_cfg')
    cfg = {'enable': bool(cfg['enable']), 'dev': cfg['dev'], 'detect': cfg['detect'],
           'light1': bool(cfg['light1']), 'light2': bool(cfg['light2']), 'expos': cv_dat['expos']}
    cfg['width'], cfg['height'] = CAM_SIZE[cfg['dev']]
    cfg['mm_per_pixel'] = MM_PER_PIXEL
    return cfg


# ------------------------------------------------------------ routes: the machine

async def h_state(request):
    pos = await dev_call('get_motor_pos')
    hw_ver = await dev_call('get_pump_hw_ver')
    ret = {'dev': api['has_dev'], 'page': page_opened(), 'pos': pos,
           'pump': {'hw_ver': hw_ver, 'pressure': await dev_call('get_pump_pressure')},
           'camera': await camera_get(), 'cv': cv_info()}
    if page_opened():
        ret['page_state'] = await page_call('info')
    return web.json_response(ret)


async def h_pos_get(request):
    return web.json_response(await dev_call('get_motor_pos'))


async def h_pos_post(request):
    body = await body_json(request, '{"pos": [x, y, z, r]} or {"delta": [dx, dy, dz, dr]}')
    args = {}
    if 'pos' in body:
        args['pos'] = num_list(body['pos'], 4, '"pos"')
    if 'delta' in body:
        args['delta'] = num_list(body['delta'], 4, '"delta"')
    if not args:
        raise web.HTTPBadRequest(text='err: send {"pos": [x, y, z, r]} (null keeps an axis) or {"delta": [dx, dy, dz, dr]}\n')
    wait = body.get('wait', 100)
    speed = body.get('speed')
    if not isinstance(wait, (int, float)) or (speed is not None and not isinstance(speed, (int, float))):
        raise web.HTTPBadRequest(text='err: "wait" and "speed" must be numbers\n')
    args['wait'] = wait
    if speed is not None:
        args['speed'] = speed

    if page_opened():   # the page keeps the position it believes, so a move goes through it
        return web.json_response(await page_call('move', args, timeout=310))

    cur = await dev_call('get_motor_pos')
    pos = list(cur)
    if 'pos' in args:
        pos = [c if p is None else p for p, c in zip(args['pos'], cur)]
    if 'delta' in args:
        pos = [p + (d or 0) for p, d in zip(pos, args['delta'])]
    for i, (lo, hi) in enumerate(POS_LIMIT):
        if lo is not None:
            pos[i] = min(max(pos[i], lo), hi)
    speed = speed if speed is not None else 260000
    await dev_call('set_motor_pos', timeout=310, pos=pos, wait=wait, speed=speed)
    return web.json_response(await dev_call('get_motor_pos') if api['has_dev'] else pos)


async def h_pump_get(request):
    return web.json_response({'hw_ver': await dev_call('get_pump_hw_ver'),
                              'pressure': await dev_call('get_pump_pressure')})


async def h_pump_post(request):
    val = await body_value(request)
    if not isinstance(val, (int, float)):
        raise web.HTTPBadRequest(text='err: the pump value must be a number\n')
    if page_opened():
        await page_call('pump', {'val': val})
    else:
        await dev_call('set_pump', val=val)
    return web.json_response(await dev_call('get_pump_pressure'))


async def h_camera_get(request):
    return web.json_response(await camera_get())


async def h_camera_post(request):
    body = await body_json(request, '{"enable": bool, "dev": 1|2, "detect": "...", "light1": bool, "light2": bool, "expos": N}')
    keys = ('enable', 'dev', 'detect', 'light1', 'light2', 'expos')
    args = {k: body[k] for k in keys if k in body}
    if not args:
        raise web.HTTPBadRequest(text=f'err: nothing to set, keys: {", ".join(keys)}\n')
    if 'dev' in args and args['dev'] not in (1, 2):
        raise web.HTTPBadRequest(text='err: "dev" must be 1 (down looking) or 2 (up looking)\n')
    if 'expos' in args and not (isinstance(args['expos'], int) and 0 <= args['expos'] <= 0xffff):
        raise web.HTTPBadRequest(text='err: "expos" must be an integer 0..65535\n')
    if 'detect' in args and not isinstance(args['detect'], str):
        raise web.HTTPBadRequest(text='err: "detect" must be a string\n')
    for k in ('enable', 'light1', 'light2'):
        if k in args:
            args[k] = as_bool(args[k])

    if page_opened():
        await page_call('camera_set', args)
        return web.json_response(await camera_get())

    cur = await camera_get()
    new = dict(cur, **args)
    cfg = {k: new[k] for k in ('dev', 'detect', 'light1', 'light2', 'expos')}
    if new['dev'] != cur['dev'] and cur['enable'] and new['enable']:
        await dev_call('set_camera', val=False)
        await dev_call('set_camera_cfg', **cfg)
        await dev_call('set_camera', val=True)
    else:
        await dev_call('set_camera_cfg', **cfg)
        if new['enable'] != cur['enable']:
            await dev_call('set_camera', val=new['enable'])
    return web.json_response(await camera_get())


async def h_camera_bg(request):
    action = (await request.text()).strip().strip('"').lower()
    if action not in ('update', 'remove'):
        raise web.HTTPBadRequest(text='err: body must be "update" (take the next frame of camera 1 as the '
                                      'background) or "remove"\n')
    await dev_call(f'{action}_camera_bg')
    return as_text('ok')


async def h_vision_post(request):
    body = await body_json(request, '{"nozzle_thresh": N, "debug": bool}')
    thresh = body.get('nozzle_thresh', cv_dat['nozzle_thresh'])
    if not (isinstance(thresh, int) and 0 <= thresh <= 255):
        raise web.HTTPBadRequest(text='err: "nozzle_thresh" must be an integer 0..255\n')
    await dev_call('set_vision_cfg', nozzle_thresh=thresh, debug=as_bool(body.get('debug', cv_dat['debug'])))
    return web.json_response({'nozzle_thresh': cv_dat['nozzle_thresh'], 'debug': cv_dat['debug']})


async def h_cv_get(request):
    return web.json_response(cv_info())


async def h_frame(request):
    typ = request.query.get('type', 'cv')
    if typ not in ('cv', 'raw'):
        raise web.HTTPBadRequest(text='err: type must be "cv" (annotated png) or "raw" (the camera\'s jpg)\n')
    last = cv_dat['last']
    min_seq = q_int(request, 'min_seq', 0)
    if q_int(request, 'wait', 0):
        min_seq = max(min_seq, (last['seq'] if last else 0) + 1)
    if min_seq:
        timeout = q_float(request, 'timeout', 3)
        deadline = asyncio.get_running_loop().time() + timeout
        while last is None or last['seq'] < min_seq:
            if asyncio.get_running_loop().time() > deadline:
                raise web.HTTPGatewayTimeout(text=f'err: no new frame in {timeout}s, is the camera enabled?\n')
            await asyncio.sleep(0.02)
            last = cv_dat['last']
    if last is None:
        raise web.HTTPNotFound(text='err: no frame received yet, is the camera enabled?\n')

    if typ == 'raw':
        body, ctype = last['raw'], 'image/jpeg'
    else:
        ok, png = await asyncio.get_running_loop().run_in_executor(None, cv.imencode, '.png', last['img'])
        if not ok:
            raise web.HTTPInternalServerError(text='err: png encode failed\n')
        body, ctype = png.tobytes(), 'image/png'
    headers = {'X-Frame-Seq': str(last['seq']), 'X-Frame-Ts': f'{last["ts"]:.3f}',
               'X-Frame-Dev': str(last['dev']), 'X-Frame-Detect': last['detect'],
               'X-Frame-Cv': json.dumps(last['cur'])}
    return web.Response(body=body, content_type=ctype, headers=headers)


async def h_snap(request):
    body = await body_json(request, '{"times": 3, "max_err": 0.02}')
    args = {k: body[k] for k in ('times', 'max_err') if k in body}
    for k, v in args.items():
        if not isinstance(v, (int, float)) or v <= 0:
            raise web.HTTPBadRequest(text=f'err: "{k}" must be a positive number\n')
    return web.json_response(await page_call('snap', args, timeout=120))


async def h_pcb2xyz(request):
    body = await body_json(request, '{"pcb": [[x, y], [x, y]], "cam": [[x, y], [x, y]], "x": X, "y": Y}')
    for k in ('pcb', 'cam'):
        v = body.get(k)
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(p, list) and len(p) == 2 for p in v)):
            raise web.HTTPBadRequest(text=f'err: "{k}" must be [[x, y], [x, y]], the two fiducials\n')
    for k in ('x', 'y'):
        if not isinstance(body.get(k), (int, float)):
            raise web.HTTPBadRequest(text=f'err: "{k}" must be a number\n')
    ret = await dev_call('pcb2xyz', pcb=body['pcb'], cam=body['cam'], x=body['x'], y=body['y'])
    return web.json_response(ret)


async def h_wait_stop(request):
    await dev_call('wait_stop', timeout=310)
    return as_text('ok')


async def h_force(request):
    await dev_call('enable_force')
    return as_text('ok')


# ------------------------------------------------------------ routes: the page

async def h_page(request):
    return web.json_response(await page_call('info'))


async def h_cfg_get(request):
    return web.json_response(await page_call('cfg_get'))


async def h_cfg_post(request):
    body = await body_json(request, '{"vals": {"name": value, ...}, "save": false}')
    vals = body.get('vals')
    if not isinstance(vals, dict) or not vals:
        raise web.HTTPBadRequest(text='err: "vals" must be an object of config values, see GET /api/page/cfg\n')
    return web.json_response(await page_call('cfg_set', {'vals': vals, 'save': as_bool(body.get('save', False))}))


async def h_comps(request):
    return web.json_response(await page_call('comps'))


async def h_select(request):
    body = await body_json(request, '{"comp": "R1", "goto": false}')
    if not isinstance(body.get('comp'), str):
        raise web.HTTPBadRequest(text='err: "comp" must be a component name, see GET /api/page/comps\n')
    args = {'comp': body['comp'], 'goto': as_bool(body.get('goto', False))}
    return web.json_response(await page_call('select', args, timeout=310))


async def h_run(request):
    return web.json_response(await page_call('run'))


async def h_pause(request):
    return web.json_response(await page_call('pause', {'en': as_bool(await body_value(request, 'en'))}))


async def h_stop(request):
    return web.json_response(await page_call('stop'))


async def h_step(request):
    idx = await body_value(request, 'idx')
    if not isinstance(idx, int) or not 0 <= idx <= 6:
        raise web.HTTPBadRequest(text='err: step must be 0..6: show_target, goto_comp, snap, pickup, check, goto_pcb, put_down\n')
    return web.json_response(await page_call('step', {'idx': idx}))


async def h_cali_scale(request):
    return web.json_response(await page_call('cali_scale', timeout=310))


async def h_board(request):
    idx = await body_value(request, 'idx')
    if not isinstance(idx, int) or not 0 <= idx <= 9:
        raise web.HTTPBadRequest(text='err: board must be 0..9\n')
    return web.json_response(await page_call('board', {'idx': idx}))


HELP = '''\
CDPNP external API, see doc/api.md. Positions are [x, y, z, r]: mm, mm, mm (z <= 0,
down is more negative), degrees. The machine calls need no page in the browser, the
/api/page calls do (http://localhost:8900).

  GET    /api/state            everything at a glance
  GET    /api/pos              motor position [x, y, z, r], read from the motors
  POST   /api/pos              move, body {"pos":[x,y,z,r]} (null keeps an axis) or
                               {"delta":[dx,dy,dz,dr]}, "wait": 100 (percent of the
                               way to wait for, 0: return at once), "speed": N
  GET    /api/pump             {"hw_ver", "pressure"}
  POST   /api/pump             body: hw v1: 0 off, 1 valve, 2 pump; v2: target pressure
                               (-70 suck, 0 off)
  GET    /api/camera           {"enable","dev","detect","light1","light2","expos",...}
  POST   /api/camera           any of those keys, body {"dev":1,"enable":true,...}
  POST   /api/camera/bg        body "update" or "remove": the background subtraction
                               image of camera 1
  POST   /api/vision           body {"nozzle_thresh": 0..255, "debug": bool}
  GET    /api/cv               what the vision code found in the last frame
  GET    /api/frame            the last frame, ?type=cv (annotated png, default) or
                               ?type=raw (the camera's own jpg), ?wait=1 waits for
                               the next frame, ?min_seq=N for one at or after N,
                               ?timeout=S; X-Frame-* headers carry seq / ts / cv
  POST   /api/snap             center the camera on the detected part (page needed),
                               body {"times": 3, "max_err": 0.02}
  POST   /api/pcb2xyz          body {"pcb":[[..],[..]],"cam":[[..],[..]],"x":X,"y":Y}
                               -> [x, y, angle] in machine coordinates
  POST   /api/wait_stop        wait until every motor has stopped
  POST   /api/force            arm the z force sensor: the next move down stops on touch
  GET    /api/page             the page's state: config, run state, component list
  GET    /api/page/cfg         the config values of the page
  POST   /api/page/cfg         body {"vals": {"name": value, ...}, "save": false}
  GET    /api/page/comps       the component list, as loaded from the csv
  POST   /api/page/select      body {"comp": "R1", "goto": false}, goto moves the
                               camera to the component
  POST   /api/page/run         start the semi-automatic placement
  POST   /api/page/pause       body 1 or 0
  POST   /api/page/stop        stop the run
  POST   /api/page/step        body 0..6: the step the run continues with
  POST   /api/page/board       body 0..9: the board the run continues with
  POST   /api/page/cali_scale  measure the mm per pixel of camera 1 around a part at the
                               comp search position (the Calibration button of Cam scale)
'''


async def h_help(request):
    return web.Response(text=HELP)


# A browser sends the Origin of the page a request comes from. Refuse any but a page on this
# machine, or any website open in the browser could move the machine through the api: a simple
# POST needs no preflight, so the request goes out even though its reply is then blocked. curl
# and the python wrapper send no Origin and go through.
@web.middleware
async def same_host_only(request, handler):
    origin = request.headers.get('Origin')
    if origin is not None and urlsplit(origin).hostname not in ('localhost', '127.0.0.1', '::1'):
        logger.warning(f'refused a request from origin {origin}: {request.method} {request.path}')
        raise web.HTTPForbidden(text=f'err: a request from another origin is refused: {origin}\n')
    return await handler(request)


async def start_api(addr, port):
    app = web.Application(middlewares=[same_host_only])
    app.add_routes([
        web.get('/', h_help),
        web.get('/api', h_help),
        web.get('/api/state', h_state),
        web.get('/api/pos', h_pos_get),
        web.post('/api/pos', h_pos_post),
        web.get('/api/pump', h_pump_get),
        web.post('/api/pump', h_pump_post),
        web.get('/api/camera', h_camera_get),
        web.post('/api/camera', h_camera_post),
        web.post('/api/camera/bg', h_camera_bg),
        web.post('/api/vision', h_vision_post),
        web.get('/api/cv', h_cv_get),
        web.get('/api/frame', h_frame),
        web.post('/api/snap', h_snap),
        web.post('/api/pcb2xyz', h_pcb2xyz),
        web.post('/api/wait_stop', h_wait_stop),
        web.post('/api/force', h_force),
        web.get('/api/page', h_page),
        web.get('/api/page/cfg', h_cfg_get),
        web.post('/api/page/cfg', h_cfg_post),
        web.get('/api/page/comps', h_comps),
        web.post('/api/page/select', h_select),
        web.post('/api/page/run', h_run),
        web.post('/api/page/pause', h_pause),
        web.post('/api/page/stop', h_stop),
        web.post('/api/page/step', h_step),
        web.post('/api/page/board', h_board),
        web.post('/api/page/cali_scale', h_cali_scale),
    ])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, addr, port)
    await site.start()
    logger.info(f'api server on http://{addr}:{port}')
    while True:
        await asyncio.sleep(3600)


def api_init(has_dev, addr='localhost', port=8901):
    """Called from the thread that runs the asyncio loop, with the loop set."""
    api['has_dev'] = has_dev
    api['sock'] = CDWebSocket(ws_ns, 'api')
    ws_ns.connections['api'] = DevConn()
    loop = asyncio.get_event_loop()
    loop.create_task(api_service())
    loop.create_task(start_api(addr, port))
