CDPNP External API
=======================================

Lets a script, or an AI agent, drive the machine from outside: move the axes,
switch the pump, set up the cameras, fetch the camera frames and what the
vision code found in them, and reach the page's config, component list and
run state. The idea is that an agent can look at what the camera sees, decide,
move, and look again, the loop a person goes through with the buttons, and
that it can improve the vision, the calibration or the placement steps with
real images and real results.

The machine calls are served by the backend itself (motors, pump, cameras),
so they work with no page opened in the browser. They share one queue with
the page's own requests, so a script and the user never talk to the bus at
the same time. The page calls (`/api/page/...`) relay to the page at
http://localhost:8900, which runs the same functions the buttons run, so it
must be opened. A move, pump or camera call goes through the page as well
whenever it is opened, so the position and the check boxes the page shows
stay true.

The server listens on `localhost:8901` by default, use `--api-port` to change
it, `--api-port 0` to disable it. `GET http://localhost:8901/` prints the
endpoint list.

The api is for scripts on this machine. A request made by a web page of some
other site through the browser carries that site's `Origin` header and is
refused (403): otherwise any website open in the browser could move the
machine. curl and the python wrapper send no `Origin` and go through.


### Endpoints

```
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
```

Errors come back as a 4xx / 5xx with a one line `err: ...` body.


### Coordinates

A position is `[x, y, z, r]`: x, y, z in mm, r in degrees. z is 0 at the top
and gets more negative going down, the bed is around -90. The working range
is x 2..300, y 2..249, z -92..-2, a target outside is clamped to it, the same
way the page clamps its buttons. The rotation axis is not limited.

Two cameras: `dev` 1 looks down from the head at the PCB and the component
trays, its image is 600 x 800 (width x height, the raw jpg is rotated 90
degrees to get there); `dev` 2 looks up at the nozzle from the bed, 800 x 600,
mirrored. The crosshair drawn in the middle of the annotated image is the
camera's optical center. At the working height one pixel of camera 1 is
10/344 mm (`mm_per_pixel` in `/api/cv` and `/api/camera`), so an object
found at pixel (x, y) is `offset_mm = ((x - w/2), (y - h/2)) * mm_per_pixel`
from the camera center, which `/api/cv` also gives. The page moves the head by
that offset (negated for camera 2) to center the camera on the object, which
is what `/api/snap` does.

Camera center and nozzle are not the same point: the config value `grab_ofs`
is the vector from the camera center to the nozzle rotation center, and
`nozzle_cali` the error of the nozzle tip at 0 degrees, see the calibration
section of the page.


### The camera and the vision result

`/api/camera` sets up what the cameras do: `enable` streams frames from the
selected `dev`, `light1` / `light2` are the lights of the two cameras,
`expos` is the exposure, and `detect` picks what the vision code looks for
in each frame:

- `""`: nothing, the frame is only annotated with the center cross
- `default`: a component, its center and angle (-90..90)
- `limit_angle`: the same, the angle folded into -45..45 (for square parts)
- `pld_first` / `pld_last`: a tray position for the preload feature
- `cali_nozzle_D_T`: a circle of diameter D +/- T pixels, the nozzle hole,
  camera 2 (the threshold is `nozzle_thresh` of `/api/vision`)
- `cali_pad`: the pads of a footprint, their common center and angle

`/api/cv` is the result for the last frame: `cur` is `[x, y, angle, dist]`
in pixels of the annotated image (dist is the L1 distance of the object to
the image center, the page picks the nearest one), or `null` when nothing was
found, with the frame `seq` and `ts` it belongs to. The detect mode and the
camera must be set before the frame is taken, so after `POST /api/camera`
wait for a new frame (`/api/frame?wait=1`) before reading `/api/cv`.

`/api/frame` returns the annotated image as png (what the OpenCV window on
the backend shows: the contours, the angle label, the cross on the chosen
object), or with `?type=raw` the jpg exactly as the camera sent it, in its
native orientation, for a vision algorithm of your own. The `X-Frame-Seq`,
`X-Frame-Ts`, `X-Frame-Dev`, `X-Frame-Detect` and `X-Frame-Cv` headers tell
which frame it is and what the vision code found in it, so a raw frame and
its result are read in one request. `?wait=1` returns the next frame that
comes in after the request, which is how to get a frame taken after a move;
`?min_seq=N` one with at least that number.

```shell
curl -X POST localhost:8901/api/camera -d '{"dev":1,"enable":true,"detect":"default","light1":false}'
curl -X POST localhost:8901/api/pos -d '{"pos":[55,142,-83,0]}'
curl -s -D - -o frame.png 'localhost:8901/api/frame?wait=1' | grep X-Frame
curl -s -o raw.jpg 'localhost:8901/api/frame?type=raw'
curl localhost:8901/api/cv
```


### Moving

`POST /api/pos` moves to an absolute target, an axis given as `null` keeps
its value, or by a `delta`, and both may be combined. `wait` is the percent
of the longest axis' travel to wait for before the call returns: 100 waits
until every motor has stopped (the default), 70 returns a bit early so the
next move blends into this one, which is what the page does between the
steps of a run, 0 returns at once. `speed` is the motor speed in steps per
second, up to 600000 for a page move at 100 % motor speed; when the page is
opened the page's own speed setting applies unless given.

A move down onto something should go through `POST /api/force` first: it arms
the strain gauge in the z axis, and the move stops when the nozzle touches,
which is how the page picks up and places. `POST /api/pump` then sucks
(`-70` on pump hw v2, `2` on v1) or releases (`0`, or `1` on v1 to open the
valve). `GET /api/pump` gives the pressure, the page takes below -30 as a
component held on hw v2.

```shell
curl -X POST localhost:8901/api/force
curl -X POST localhost:8901/api/pos -d '{"pos":[null,null,-90.5,null],"speed":6000}'
curl -X POST localhost:8901/api/pump -d -70
curl -X POST localhost:8901/api/pos -d '{"delta":[0,0,10,0]}'
```

While a run is in progress on the page, a move or a snap through the api is
refused, pause or stop the run first.


### The page

`GET /api/page` is what the page knows: `cur_pos` (the position the page
believes, kept up to date by every move through the page), the camera boxes,
`run` (running, pause, step, board, the selected component and the progress)
and `cfg`, the config values of the page: `grab_ofs`, `nozzle_cali`,
`cam_angle`, `comp_search` (the tray search positions), `cam_dz`,
`comp_base_z`, `pcb_base_z`, `fiducial_pcb`, `fiducial_cam`, `user_pos`,
`motor_speed`, `nozzle_expos`, `nozzle_thresh`, `offset_config` and the
`pld_*` preload values. `POST /api/page/cfg` changes any of them, the input
boxes follow; a change is kept in the browser only with `"save": true`, as
the Save button does.

`GET /api/page/comps` is the component list loaded from the csv, grouped by
footprint and value, each entry `[name, x, y, angle]` in pcb coordinates.
`POST /api/page/select` picks one, and with `"goto": true` moves the camera
over its place on the current board, which is what clicking a component does.

`POST /api/page/run` starts the semi-automatic placement, the same as the Run
button, and returns at once; `pause`, `stop`, `step` and `board` are the
controls next to it. The run pauses by itself where the page pauses, e.g.
before placing when "Put down" is unchecked, so an agent can watch the run
step by step: read `/api/page`, check the frame, and release the pause.

```shell
curl localhost:8901/api/page/cfg
curl -X POST localhost:8901/api/page/cfg -d '{"vals":{"motor_speed":0.3}}'
curl -X POST localhost:8901/api/page/select -d '{"comp":"R1","goto":true}'
curl -X POST localhost:8901/api/page/run
curl -X POST localhost:8901/api/page/pause -d 0
```


### Python Wrapper

`tools/pnp_api.py` wraps the same thing for python:

```python
from pnp_api import PnpApi

a = PnpApi()
a.set_camera(dev=1, enable=True, detect='default')
a.move(pos=[55, 142, -83, 0])
png, info = a.frame(wait=True, path='frame.png')     # the frame after the move
print(info['cv'], a.cv()['offset_mm'])
if info['cv']:
    dx, dy = a.cv()['offset_mm']
    a.move(delta=[dx, dy, 0, 0])                       # center the camera on it
raw, _ = a.frame(raw=True, wait=True)                  # the camera's jpg for your own algorithm
```

Commands are serialized, one finishes before the next starts, and they do not
interleave with the page's own requests. A move with `wait` takes as long as
the motion, the wrapper's default timeout allows for the longest one.


### For an AI agent

A typical loop: set the camera and the detect mode, move to where something
should be, take the next frame, read the result, decide, move again. Keep the
images small when sending them to a model, the annotated png of camera 1 is
600 x 800. Everything the agent does shows up in the backend log
(`pnp_main.py` prints each api call), and on the page when it is opened, so
a person can watch. The force sensor and the pump are what makes a pick or a
place safe, use them the way the page does, see above.
