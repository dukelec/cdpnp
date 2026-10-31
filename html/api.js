/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 *
 * Command layer for the external API (see api_serve.py and doc/api.md).
 *
 * The backend relays a command here, this file runs the same functions the
 * buttons run, and replies with the result. So the position the page shows,
 * the check boxes and the selected component all follow what a script does.
 *
 * Commands are serialized: one finishes before the next starts.
 */

import { CDWebSocket } from './utils/cd_ws.js?v=__V__';
import { csa, csa_need_save, ws_ns, VERSION } from './index.js?v=__V__';
import { set_motor_pos, set_pump, set_camera_cfg, cam_comp_snap } from './dev_cmd.js?v=__V__';
import { csa_to_page_input, input_change, save_cfg } from './input_ctrl.js?v=__V__';
import { search_current_comp, search_first_comp, select_comp, move_to_comp, get_comp_values, pos_from_page,
         set_board, get_board_safe, set_step, get_step_safe, get_comp_search } from './pos_list.js?v=__V__';
import { cands_state, scale_info } from './comp_track.js?v=__V__';
import { cali_scale } from './calibration.js?v=__V__';


function elm(id) {
    return document.getElementById(id);
}

function run_state() {
    let comp = search_current_comp();
    return {
        running: elm('btn_run').disabled,
        pause: elm('pause_en').checked,
        step: get_step_safe(),
        board: get_board_safe(),
        comp_search: get_comp_search(),
        comp: comp,
        progress: elm('cur_progress').innerText,
        next: `${elm('next_comp').innerText} x ${elm('next_total').innerText}`,
        comp_height: csa.comp_height,
        show_target: elm('show_target').checked,
        check2_en: elm('check2_en').checked,
        putdown_en: elm('putdown_en').checked,
        less_detect: elm('less_detect').checked,
        preload_en: elm('preload_en').checked,
        cands: cands_state()    // the parts recorded at the comp search position, see comp_track.js
    };
}

function camera_state() {
    return {
        enable: elm('camera_en').checked,
        dev: Number(elm('camera_dev').value),
        detect: elm('camera_detect').value,
        light1: elm('camera_light1').checked,
        light2: elm('camera_light2').checked
    };
}

function cfg_get() {
    let ret = {};
    for (let k of csa_need_save)
        ret[k] = csa[k];
    return ret;
}


const cmds = {

async info() {
    return {
        version: VERSION,
        cur_pos: csa.cur_pos,
        aux_pos: csa.aux_pos,
        pump_hw_ver: csa.pump_hw_ver,
        pump_suck_on: csa.pump_suck_on,
        camera: camera_state(),
        cam_scale: scale_info(),    // the mm per pixel of camera 1 as measured so far
        run: run_state(),
        cfg: cfg_get()
    };
},

// an absolute target (null keeps the axis) or a delta, clamped the way the buttons are
async move(a) {
    if (elm('btn_run').disabled)
        throw new Error('the run is in progress, stop or pause it first');
    let pos = csa.cur_pos.slice();
    if (a.pos)
        pos = a.pos.map((p, i) => p == null ? pos[i] : p);
    if (a.delta)
        pos = pos.map((p, i) => p + (a.delta[i] || 0));
    csa.cur_pos = pos;
    await set_motor_pos(a.wait ?? 100, a.speed ?? 600000);
    return csa.cur_pos;
},

async pump(a) {
    await set_pump(a.val);
    return 0;
},

// set the camera boxes, then do what their onchange does
async camera_set(a) {
    let cur = camera_state();
    for (let k of ['light1', 'light2'])
        if (k in a)
            elm(`camera_${k}`).checked = a[k];
    if ('detect' in a)
        elm('camera_detect').value = a.detect;
    if ('dev' in a)
        elm('camera_dev').value = a.dev;
    if ('enable' in a)
        elm('camera_en').checked = a.enable;
    let now = camera_state();
    if (now.dev != cur.dev)
        await elm('camera_dev').onchange();     // restarts the camera if enabled, sends the cfg
    else if (now.enable != cur.enable)
        await elm('camera_en').onchange();      // sends the cfg too
    else
        await set_camera_cfg(null, a.expos ?? 20);
    if ('expos' in a && (now.dev != cur.dev || now.enable != cur.enable))
        await set_camera_cfg(null, a.expos);
    return camera_state();
},

// center the camera on the detected part, as the Snap step of the run does
async snap(a) {
    if (elm('btn_run').disabled)
        throw new Error('the run is in progress, stop or pause it first');
    if (!elm('camera_en').checked)
        throw new Error('the camera is not enabled');
    let ret = await cam_comp_snap(a.times ?? 3, a.max_err ?? 0.02);
    return { found: ret == 0, pos: csa.cur_pos, angle: csa.cv_cur_r };
},

async cfg_get() {
    return cfg_get();
},

async cfg_set(a) {
    for (let k in a.vals) {
        if (!csa_need_save.includes(k))
            throw new Error(`unknown config value: ${k}, see GET /api/page/cfg`);
    }
    for (let k in a.vals)
        csa[k] = a.vals[k];
    csa_to_page_input();
    await input_change();   // reads the boxes back, which also fixes up the derived values
    if (a.save)
        await save_cfg();
    return cfg_get();
},

async comps() {
    return { list: pos_from_page(), comp: search_current_comp(), board: get_board_safe() };
},

async select(a) {
    if (get_comp_values(a.comp) == null)
        throw new Error(`no such component: ${a.comp}`);
    if (a.goto) {
        if (elm('btn_run').disabled && !elm('pause_en').checked)
            throw new Error('the run is in progress, pause or stop it first');
        await move_to_comp(a.comp);
    } else {
        select_comp(a.comp);
    }
    return run_state();
},

async run() {
    if (elm('btn_run').disabled)
        throw new Error('already running');
    if (!search_current_comp() && !search_first_comp())
        throw new Error('the component list is empty (or all deleted), load a csv first');
    if (!elm('camera_detect').value)
        throw new Error('the camera detect method is empty, set it first (POST /api/camera {"detect": "default"})');
    elm('btn_run').onclick();   // runs until the list is done, not awaited
    return run_state();
},

async pause(a) {
    elm('pause_en').checked = !!a.en;
    return run_state();
},

async stop() {
    if (!elm('btn_run').disabled)
        throw new Error('not running');
    elm('btn_stop').onclick();
    return run_state();
},

async step(a) {
    set_step(a.idx);
    return run_state();
},

// measure the mm per pixel of camera 1 around a part at the comp search position, and apply it
async cali_scale() {
    if (elm('btn_run').disabled)
        throw new Error('the run is in progress, stop it first');
    return await cali_scale(false);
},

async board(a) {
    if (a.idx >= csa.fiducial_cam.length)
        throw new Error(`board ${a.idx} has no fiducials, ${csa.fiducial_cam.length} board(s) configured`);
    await window.btn_select_board(a.idx);
    return run_state();
}

};


async function api_serve(sock) {
    let queue = Promise.resolve();
    while (true) {
        let [dat, src] = await sock.recvfrom();
        if (!dat || !dat.cmd) { // answer of our 'hello', or api not enabled
            console.log('api: backend ret', dat);
            continue;
        }
        queue = queue.then(async () => {
            let rep = { id: dat.id, err: null, ret: null };
            try {
                if (!Object.hasOwn(cmds, dat.cmd))
                    throw new Error(`unknown cmd: ${dat.cmd}`);
                rep.ret = await cmds[dat.cmd](dat.args || {});
            } catch (err) {
                rep.err = `${err.message || err}`;
                console.error('api:', dat.cmd, err);
            }
            await sock.sendto(rep, src);
        }).catch(err => console.error('api:', err));
    }
}

let api_sock = null;

// called once the websocket is open: tell the backend the page is up, then serve its commands
async function init_api() {
    if (!api_sock) {
        api_sock = new CDWebSocket(ws_ns, 'api');
        api_serve(api_sock);
    }
    await api_sock.sendto({ 'cmd': 'hello', 'args': { version: VERSION } }, ['server', 'api']);
}

export { init_api };
