/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { L, LANGS, lang_pref, set_lang } from './utils/lang.js?v=__V__';
import { sleep, blob2dat, cpy, deep_merge } from './utils/helper.js?v=__V__';
import { CDWebSocket, CDWebSocketNS } from './utils/cd_ws.js?v=__V__';
import { Idb } from './utils/idb.js?v=__V__';
import { search_comp_parents, search_next_comp, select_comp, move_to_comp, get_comp_values, pos_to_page,
         set_board, get_board_safe, set_step, get_step_safe, set_comp_search, get_comp_search, get_comp_safe } from './pos_list.js?v=__V__';
import { input_init, csa_to_page_input } from './input_ctrl.js?v=__V__';
import { get_camera_cfg, get_motor_pos, set_motor_pos, get_pump_hw_ver, check_suck_pressure, set_pump, pcb2xyz,
         z_keep_high, enable_force, cam_comp_snap, set_camera_cfg, get_cv_comps } from './dev_cmd.js?v=__V__';
import { init_api } from './api.js?v=__V__';
import { cands_scan, cands_next, cands_cur, cands_snapped, cands_lost, cands_fail, cands_picked, cands_clear,
         cands_reset_ref } from './comp_track.js?v=__V__';

let csa_dft = {
    cur_pos: [0, 0, 0, 0],
    old_pos: [0, 0, 0, 0],
    aux_pos: [0, 0, 0, 0],
    
    grab_ofs:    [33.53, 6.45], // camera to grab rotation center
    nozzle_cali: [-0.1, -0.05], // error vector at 0 degree
    cam_angle: [0, 0],          // cam1 and cam2 err angle
    cam_scale_samples: [],      // [pixel radius, mm] pairs measured by the snaps, the mm per pixel of cam1 (comp_track.js)
    comp_search: [[55, 142], [65, 142]],
    cam_dz: 7,
    comp_base_z: -89.9,
    pcb_base_z: -88.9,
    fiducial_pcb: [[-26.375, 21.35], [-6.3, 4.75]],
    fiducial_cam: [[[89.67, 175.0], [109.9, 158.6]], [[120.7, 175.3], [140.8, 158.9]]],
    
    user_pos: [
        ['Calibration', [27.95, 10.87, -29.57]],
        ['Idle', [132.0, 62.0, -45.0]]
    ],
    
    comp_height: null,
    motor_speed: 0.5,
    
    nozzle_expos: 5000,
    nozzle_thresh: 199,
    
    offset_config: "",
    
    pld_search: [47, 142],
    pld_base_z: -89.9,
    pld_comp_offset: 3.5,
    pld_comp_space: 0.5,
    pld_start_at: -0.5,
    pld_tgt_grid: [2.0, 2.0],
    pld_rotate: 0,
    pld_enable: 0,
    
    pump_hw_ver: null,
    pump_suck_on: false
};

let csa = {};
deep_merge(csa, csa_dft);

let csa_need_save = ['grab_ofs', 'nozzle_cali', 'cam_angle', 'cam_scale_samples', 'comp_search', 'cam_dz', 'comp_base_z', 'pcb_base_z',
                     'fiducial_pcb', 'fiducial_cam', 'user_pos', 'motor_speed', 'nozzle_expos', 'nozzle_thresh',
                     'offset_config', 'pld_search', 'pld_base_z', 'pld_comp_offset', 'pld_comp_space', 'pld_start_at', 'pld_tgt_grid', 'pld_rotate', 'pld_enable'];
let csa_prj_export = ['pcb_base_z', 'fiducial_pcb', 'fiducial_cam', 'offset_config'];
let csa_cfg_export = ['grab_ofs', 'nozzle_cali', 'cam_angle', 'cam_scale_samples', 'comp_search', 'cam_dz', 'comp_base_z', 'pcb_base_z', 'user_pos'];

const WS_CLOSE_DUPLICATE = 4001; // server close code: the page is already opened in another window

const VERSION = 'v3.16';    // shown in the title, web_serve.py reads it from here
// replaced by web_serve.py with "<VERSION>-<hash of all own front end files>", the same
// string the ?v= of every own js url carries, so a changed front end means changed urls
// and the browser is bound to fetch the new files
const ASSET_VER = '__V__';

let db = null;
let ws_ns = new CDWebSocketNS('/');
let cmd_sock = new CDWebSocket(ws_ns, 'cmd');


//         |  (90 degree)
//         |
//         |
// --------+-------->  x (0 degree)
//         |
//         |
//         |
//         v  y (-90 degree)

function rotate_vector(angle, vector) {
    let rad = -angle * Math.PI / 180;
    let new_vector = [
        Math.cos(rad) * vector[0] - Math.sin(rad) * vector[1],
        Math.sin(rad) * vector[0] + Math.cos(rad) * vector[1]
    ];
    return new_vector;
}

function cal_grab_ofs(angle, err=null) {
    if (err == null)
        err = [csa.nozzle_cali[0], csa.nozzle_cali[1]];
    let err_at_angle = rotate_vector(angle, err);
    return [csa.grab_ofs[0] + err_at_angle[0], csa.grab_ofs[1] + err_at_angle[1]];
}


document.getElementById('btn_run').onclick = async function() {
    let comp = get_comp_safe();
    if (!comp) {
        alert(L("list empty!"));
        return;
    }
    if (!document.getElementById('camera_detect').value) {
        alert(L("please set camera vision detect method!"));
        return;
    }
    if (document.getElementById('camera_dev').value != '1' || !document.getElementById('camera_en').checked) {
        console.log("auto enable camera before run task");
        document.getElementById('camera_dev').value = 1;
        document.getElementById('camera_en').checked = true;
        await document.getElementById('camera_dev').onchange();
    }
    document.getElementById('btn_run').disabled = true;
    document.getElementById('btn_stop').disabled = false;
    csa.stop = false;
    let parents_pre = null;
    cands_clear();      // what the tray looked like before this run is not to be trusted,
    cands_reset_ref();  // nor is the size of whatever the last run picked
    
    let z_middle = Math.min(csa.cur_pos[2] + csa.cam_dz, -2);
    if (csa.cur_pos[2] < z_middle) {
        csa.cur_pos[2] = z_middle;
        await set_motor_pos(100);
    }
    
    // error vector and nozzle angle before putdown
    let nozzle_err_vector = null;
    let nozzle_err_angle = null;
    
    while (true) {
        let comp = get_comp_safe();
        if (!comp)
            break;
        let board = get_board_safe();
        let step = get_step_safe();
        let search = get_comp_search();
        console.log(`comp: ${comp}, board: ${board}, step: ${step}, search: ${search}`);
        
        let parents = search_comp_parents(comp);
        if (parents_pre && parents_pre[0] != parents[0]) {
            csa.comp_height = null;
            document.getElementById('cur_height').innerText = `--`;
            cands_reset_ref();
        }
        if (parents_pre && (parents_pre[0] != parents[0] || parents_pre[1] != parents[1])) {
            cands_clear();  // the user changes the tray now
            document.getElementById('pause_en').checked = true;
            //document.getElementById('camera_light1').checked = true;
            await set_camera_cfg("");
            set_board(board);
            await move_to_comp(comp);
            if (csa.pump_suck_on && !(await check_suck_pressure(true)))
                await set_pump(0);
        }
        console.log(`parents: ${parents_pre} -> ${parents}`);
        
        if (csa.stop)
            break;
        if (document.getElementById('pause_en').checked) {
            console.log(`enter wait`);
            if (step == 2 || step == 3) {
                // the head may stand at a recorded part, and the list is dropped below: go back
                // through the search position; to snap where the camera is put by hand during
                // the pause, select Snap before releasing it (the step is read again then)
                console.log(`back to goto_comp before pause`);
                set_step(1);
            }
            while (document.getElementById('pause_en').checked)
                await sleep(100);
            console.log(`exit wait`);
            parents_pre = null;
            cands_clear();  // the tray may have been changed during the pause: look again
            continue;
        }
        
        let comp_val = get_comp_values(comp);
        let comp_xyz = await pcb2xyz(csa.fiducial_pcb, csa.fiducial_cam[board], comp_val[0], comp_val[1]);
        let [,,comp_offsets] = search_comp_parents(comp);
        
        if (step == 0) { // show_target
            console.log('fsm show target');
            //document.getElementById('camera_light1').checked = true;
            await set_camera_cfg("");
            await z_keep_high(70);
            csa.cur_pos[0] = comp_xyz[0];
            csa.cur_pos[1] = comp_xyz[1];
            if (csa.cur_pos[2] != csa.pcb_top_z) {
                await set_motor_pos(70);
                csa.cur_pos[2] = csa.pcb_top_z;
                await set_motor_pos(100);
            } else {
                await set_motor_pos(100);
            }
            await sleep(600);
            set_step(1);
            continue;
        }
        
        if (step == 1) { // goto_comp
            console.log('fsm goto_comp');
            document.getElementById('camera_light1').checked = false;
            await document.getElementById('camera_light1').onchange();
            await z_keep_high(70);
            // a part recorded at the search position and not tried yet: go straight to it,
            // else to the search position, and record what the camera sees there
            let cand = cands_next();
            if (cand) {
                csa.cur_pos[0] = cand.pos[0];
                csa.cur_pos[1] = cand.pos[1];
            } else {
                csa.cur_pos[0] = csa.comp_search[search][0];
                csa.cur_pos[1] = csa.comp_search[search][1];
            }
            csa.cur_pos[3] = 0;
            if (csa.cur_pos[2] != csa.comp_top_z) {
                await set_motor_pos(70);
                csa.cur_pos[2] = csa.comp_top_z;
                await set_motor_pos(100);
            } else {
                await set_motor_pos(100);
            }
            if (csa.pump_suck_on) {
                if (!(await check_suck_pressure(true))) {
                    await set_pump(0);
                } else {
                    document.getElementById('pause_en').checked = true;
                    continue;
                }
            }
            if (!cand && document.getElementById('pause_en').checked) {
                // paused on the way to the search position: the user places the tray under the camera
                // now, so stay here, and look at it once the pause is released (step 1 again)
                console.log('  paused at the search position, scan later');
                continue;
            }
            if (!cand) {
                await cands_scan(get_cv_comps);
                cand = cands_next();
                if (cand) {
                    csa.cur_pos[0] = cand.pos[0];
                    csa.cur_pos[1] = cand.pos[1];
                    await set_motor_pos(100);
                }
            }
            set_step(2);
            continue;
        }
        
        if (step == 2) { // snap
            console.log('fsm snap');
            document.getElementById('camera_light1').checked = false;
            await document.getElementById('camera_light1').onchange();
            let ret = await cam_comp_snap();
            if (ret < 0) {
                if (cands_cur()) {
                    cands_lost();   // the recorded part is not there any more, try the next
                } else {
                    if (++search >= csa.comp_search.length)
                        search = 0;
                    set_comp_search(search);
                }
                set_step(1);
            } else {
                cands_snapped([csa.cur_pos[0], csa.cur_pos[1]]);
                csa.cv_cur_r -= csa.cam_angle[0];
                set_step(3);
            }
            continue;
        }
        
        if (step == 3) { // pickup
            console.log('fsm pickup');
            let grab_ofs = cal_grab_ofs(0);
            csa.cur_pos[0] -= grab_ofs[0];
            csa.cur_pos[1] -= grab_ofs[1];
            csa.cur_pos[3] = 0;
            if (csa.comp_height != null)
                csa.cur_pos[2] = csa.comp_base_z + csa.comp_height + 1; // 1mm space
            if (comp_offsets[0][0] != 0 || comp_offsets[0][1] != 0) {
                let rad = -csa.cv_cur_r * Math.PI / 180;
                let offset = [
                    Math.cos(rad) * comp_offsets[0][0] - Math.sin(rad) * comp_offsets[0][1],
                    Math.sin(rad) * comp_offsets[0][0] + Math.cos(rad) * comp_offsets[0][1]
                ];
                csa.cur_pos[0] += offset[0];
                csa.cur_pos[1] += offset[1];
            }
            await set_motor_pos(100);
            if (csa.comp_height != null && document.getElementById('less_detect').checked) {
                csa.cur_pos[2] = csa.comp_base_z + csa.comp_height - 0.5; // -0.5mm space
                await set_motor_pos(100);
            } else {
                await sleep(800);
                await enable_force();
                csa.cur_pos[2] = csa.comp_base_z - 1;
                await set_motor_pos(100, csa.motor_speed >= 0.6 ? 12000 : 6000);
            }
            await set_pump(csa.pump_hw_ver == 'v1' ? 2 : -70);
            if (csa.comp_height == null) {
                await get_motor_pos();
                csa.comp_height = Math.max(parseFloat((csa.cur_pos[2] - csa.comp_base_z).toFixed(3)), 0);
                document.getElementById('cur_height').innerText = `${csa.comp_height}`;
            }
            await sleep(600);
            await z_keep_high(70, 260000);
            if (await check_suck_pressure()) {
                await set_pump(0);
                cands_fail();
                document.getElementById('pause_en').checked = true;
                set_step(1);
                continue;
            }
            cands_picked(csa.cv_cur_size);
            
            if (document.getElementById('check2_en').checked) {
                set_step(4);
            } else {
                // nozzle angle and nozzle_err_vector when comp rotate to 0 degrees
                nozzle_err_angle = -csa.cv_cur_r;
                nozzle_err_vector = rotate_vector(nozzle_err_angle, csa.nozzle_cali)
                set_step(5);
            }
            continue;
        }
        
        if (step == 4) { // 2nd check
            console.log('fsm check');
            let detect_bk = document.getElementById('camera_detect').value;
            document.getElementById('camera_dev').value = 2;
            document.getElementById('camera_light2').checked = true;
            document.getElementById('camera_detect').value = "";
            await document.getElementById('camera_dev').onchange();
            await set_camera_cfg("cali_pad");
            
            let cali_pos = csa.user_pos[0][1];
            csa.cur_pos[3] = -csa.cv_cur_r;
            let err = rotate_vector(csa.cur_pos[3], csa.nozzle_cali);
            
            let z_middle = Math.min(Math.max(cali_pos[2], csa.cur_pos[2]) + csa.comp_height, -2);
            if (csa.cur_pos[2] < z_middle) {
                csa.cur_pos[2] = z_middle;
                await set_motor_pos(70);
            }
            csa.cur_pos[0] = cali_pos[0] - err[0];
            csa.cur_pos[1] = cali_pos[1] - err[1];
            await set_motor_pos(70);
            csa.cur_pos[2] = cali_pos[2] + csa.comp_height;
            await set_motor_pos(100);
            
            while (document.getElementById('pause_en').checked)
                await sleep(100);
            if (csa.stop)
                break;
            
            await cam_comp_snap(3, 0.2);
            csa.cur_pos[3] -= csa.cv_cur_r;
            await set_motor_pos(100);
            await cam_comp_snap();
            
            if (!document.getElementById('putdown_en').checked) {
                document.getElementById('pause_en').checked = true;
            } else {
                await sleep(800);
            }
            while (document.getElementById('pause_en').checked)
                await sleep(100);
            if (csa.stop)
                break;
            
            nozzle_err_vector = [cali_pos[0] - csa.cur_pos[0], cali_pos[1] - csa.cur_pos[1]];
            nozzle_err_angle = csa.cur_pos[3];
            
            nozzle_err_angle += csa.cam_angle[1];
            nozzle_err_vector = rotate_vector(csa.cam_angle[1], nozzle_err_vector);

            document.getElementById('camera_dev').value = 1;
            document.getElementById('camera_detect').value = detect_bk;
            document.getElementById('camera_light2').checked = false;
            await document.getElementById('camera_dev').onchange();
            set_step(5);
            continue;
        }
        
        if (step == 5) { // goto_pcb
            console.log('fsm goto_pcb');
            await z_keep_high(70);
            // optimize the rotation angle for faster speed
            if (nozzle_err_angle != null) {
                let rad = (comp_val[2] + nozzle_err_angle + comp_xyz[2]) * Math.PI / 180;
                let tgt_angle = Math.atan2(Math.sin(rad), Math.cos(rad)) * 180 / Math.PI;
                if (document.getElementById('camera_detect').value == 'default' &&
                        Math.abs(tgt_angle) > 90 && !document.getElementById('check2_en').checked) {
                    console.log('  rotate 180, before:', tgt_angle);
                    tgt_angle = tgt_angle > 90 ? tgt_angle - 180 : tgt_angle + 180;
                }
                nozzle_err_vector = rotate_vector(tgt_angle - nozzle_err_angle, nozzle_err_vector);
                csa.cur_pos[3] = tgt_angle;
            } else {
                nozzle_err_vector = [0, 0];
            }
            
            csa.cur_pos[0] = comp_xyz[0] - csa.grab_ofs[0] - nozzle_err_vector[0];
            csa.cur_pos[1] = comp_xyz[1] - csa.grab_ofs[1] - nozzle_err_vector[1];
            await set_motor_pos(70);
            set_step(6);
            continue;
        }
        
        if (step == 6) { // putdown
            console.log('fsm putdown');
            if (csa.comp_height != null)
                csa.cur_pos[2] = csa.pcb_base_z + csa.comp_height + 1; // 1mm space
            await set_motor_pos(100);
            if (!document.getElementById('putdown_en').checked) {
                document.getElementById('pause_en').checked = true;
                while (document.getElementById('pause_en').checked)
                    await sleep(100);
                // manual select comp during putdown pause
                await set_pump(csa.pump_hw_ver == 'v1' ? 1 : 0);
                await sleep(500);
                await z_keep_high(70);
                await set_pump(0);
                if (get_comp_safe() != comp || get_board_safe() != board)
                    continue;
            } else {
                if (csa.comp_height != null && document.getElementById('less_detect').checked) {
                    csa.cur_pos[2] = csa.pcb_base_z + csa.comp_height - 0.5; // -0.5mm space
                    await set_motor_pos(100);
                } else {
                    await sleep(800);
                    await enable_force();
                    csa.cur_pos[2] = csa.pcb_base_z - 1;
                    await set_motor_pos(100, csa.motor_speed >= 0.6 ? 12000 : 6000);
                }
                //await set_pump(csa.pump_hw_ver == 'v1' ? 1 : 30); // blow
                await set_pump(csa.pump_hw_ver == 'v1' ? 1 : 0);
                await sleep(500);
                await z_keep_high(70);
                await set_pump(0);
                if (csa.pump_hw_ver != 'v1')
                    await set_pump(-70); // check nozzle empty
            }
            set_step(Number(!document.getElementById('show_target').checked));
        }
        
        if (++board >= csa.fiducial_cam.length) {
            set_board(0);
            let next = search_next_comp(comp);
            select_comp(next);
            parents_pre = parents;
            if (!next)
                break;
        } else {
            set_board(board);
            select_comp(comp); // update progress
        }
    }
    console.log('all comp finished');
    cands_clear();
    csa.cur_pos[3] = 0;
    document.getElementById('btn_pld_clear').onclick();
    await set_motor_pos();
    if (csa.pump_hw_ver != 'v1' && csa.pump_suck_on) {
        await sleep(1000);
        if (!(await check_suck_pressure(true)))
            await set_pump(0);
    }
    csa.comp_height = null;
    document.getElementById('cur_height').innerText = `--`;
    csa.stop = true;
    document.getElementById('btn_run').disabled = false;
    document.getElementById('btn_stop').disabled = true;
};

document.getElementById('btn_stop').onclick = function() {
    csa.stop = true;
    document.getElementById('pause_en').checked = false;
    document.getElementById('btn_stop').disabled = true;
    set_step(1);
};


// a notice that sticks to the top of the page, over the content, as cdbus_gui shows it
function show_banner(id, html, cls='is-danger') {
    let elem = document.getElementById(id);
    if (!elem) {
        let box = document.getElementById('banner_box');
        if (!box) {
            box = document.createElement('div');
            box.id = 'banner_box';
            box.style.cssText = 'position: sticky; top: 0; z-index: 100;';
            document.body.prepend(box);
        }
        elem = document.createElement('div');
        elem.id = id;
        // the text color is what bulma 1.0 gives cdbus_gui (hsl(348, 100%, 5%)), bulma 0.9 would make it white
        elem.style.cssText = 'margin: 0; border-radius: 0; white-space: pre-wrap; ' +
                             'border-bottom: 1px solid #0000001a; color: hsl(348, 100%, 5%); ' +
                             'background-color: #F5B7B180; backdrop-filter: blur(8px); ' +
                             '-webkit-backdrop-filter: blur(8px);';
        box.prepend(elem);
    }
    elem.className = `notification ${cls}`;
    elem.innerHTML = html;
    elem.style.display = html ? '' : 'none';
}

// say why the page lost its backend: it is gone, or this page is a duplicate
function ws_closed(evt) {
    if (evt && evt.code == WS_CLOSE_DUPLICATE)
        show_banner('ws_banner', `<b>${L('The page is already opened in another window, only one page is allowed.')}</b>\n` +
                    L('Close this window and use the existing one. (If the existing one was just closed, wait a few seconds and reload.)'));
    else
        show_banner('ws_banner', `<b>${L('WebSocket disconnected')}</b>\n` +
                    L('The backend may have exited or the connection was lost, please check the backend log and reload the page.'));
}

function init_ws() {
    let ws_url = `ws://${window.location.hostname}:${window.location.port}/`;
    let ws = new WebSocket(ws_url);
    
    ws.onopen = async function(evt) {
        console.log("ws onopen");
        ws_ns.connections['server'] = ws;
        await get_motor_pos();
        await get_camera_cfg();
        csa.pump_hw_ver = await get_pump_hw_ver();
        await init_api();   // the external api may now relay commands to this page
    }
    ws.onmessage = async function(evt) {
        let dat = await blob2dat(evt.data);
        var msg = msgpack.deserialize(dat);
        //console.log("Received dat", msg);
        if (msg['dst'][1] in ws_ns.sockets) {
            let sock = ws_ns.sockets[msg['dst'][1]];
            sock.recv_q.put([msg['dat'], msg['src']]);
        } else {
            console.log("ws drop msg:", msg);
        }
    }
    ws.onerror = function(evt) {
        console.log("ws onerror: ", evt);
    }
    ws.onclose = function(evt) {
        delete ws_ns.connections['server'];
        console.log('ws disconnected', evt.code, evt.reason);
        ws_closed(evt);
    }
}


window.addEventListener('load', async function() {
    console.log("load app");
    let ver = ASSET_VER.startsWith(`${VERSION}-`) ? ASSET_VER : VERSION;  // full one only when served
    document.title = `CDPNP Tools - ${VERSION}`;
    document.getElementById('version').innerText = VERSION;
    document.getElementById('version').title = ver;
    
    // apply translation
    for (let tag of ['button', 'span', 'option', 'td', 'div']) {
        let elems = document.getElementsByTagName(tag);
        for (let e of elems) {
            if (e.title)
                e.title = eval("`" + e.title + "`");
            if (tag == 'div')
                continue;
            e.innerHTML = eval("`" + e.innerHTML + "`");
        }
    }
    // the language picker, '' follows the browser; L() is fixed when the modules load,
    // so just remember the choice and reload the page
    let lang_sel = document.getElementById('lang_sel');
    lang_sel.innerHTML = LANGS.map(([v, t]) =>
        `<option value="${v}" ${v == lang_pref() ? 'selected' : ''}>${v ? t : L('Auto')}</option>`).join('');
    lang_sel.onchange = e => { set_lang(e.target.value); location.reload(); };
    
    db = await new Idb();
    init_ws();
    
    let csa_pre = await db.get('tmp', 'csa');
    if (csa_pre)
        cpy(csa, csa_pre, csa_need_save);
    let pos = await db.get('tmp', 'list');
    if (pos)
        pos_to_page(pos);
    input_init();
    csa_to_page_input();
});

export {
    csa_dft, csa, cmd_sock, db, ws_ns, csa_need_save, csa_prj_export, csa_cfg_export, cal_grab_ofs, rotate_vector, VERSION, show_banner
};
