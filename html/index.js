/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { L } from './lang/lang.js'
import { sleep, blob2dat, cpy } from './utils/helper.js';
import { CDWebSocket, CDWebSocketNS } from './utils/cd_ws.js';
import { Idb } from './utils/idb.js';
import { search_comp_parents, search_next_comp, select_comp, move_to_comp, get_comp_values, pos_to_page,
         set_board, get_board_safe, set_step, get_step_safe, set_comp_search, get_comp_search, get_comp_safe } from './pos_list.js';
import { input_init, csa_to_page_input } from './input_ctrl.js';
import { get_camera_cfg, get_init_home, get_motor_pos, set_motor_pos, set_pump, update_coeffs, pcb2xyz,
         z_keep_high, enable_force, cam_comp_snap } from './dev_cmd.js';

let csa = {
    cur_pos: [0, 0, 0, 0],
    old_pos: [0, 0, 0, 0],
    aux_pos: [0, 0, 0, 0],
    
    grab_ofs0:   [34.9, 8.0],
    grab_ofs180: [34.8, 7.9],
    comp_search: [[50, 165], [50, 145]],
    comp_top_z: -85.5,
    pcb_top_z: -84.5,
    comp_base_z: -89.3,
    pcb_base_z: -88.2,
    fiducial_pcb: [[-26.375, 21.35], [-6.3, 4.75]],
    fiducial_cam: [[[89.673, 175.000], [109.861, 158.607]], [[120.720, 175.347], [140.849, 158.856]]],
    
    comp_height: null
};

let csa_need_save = ['grab_ofs0', 'grab_ofs180', 'comp_search', 'comp_top_z', 'pcb_top_z', 'comp_base_z', 'pcb_base_z', 'fiducial_pcb', 'fiducial_cam'];

let db = null;
let ws_ns = new CDWebSocketNS('/');
let cmd_sock = new CDWebSocket(ws_ns, 'cmd');

function cal_grab_ofs(angle) {
    let rad = -angle * Math.PI / 180;
    let delta = [csa.grab_ofs0[0] - csa.grab_ofs180[0], csa.grab_ofs0[1] - csa.grab_ofs180[1]];
    let ofs = [csa.grab_ofs0[0] - delta[0] / 2, csa.grab_ofs0[1] - delta[1] / 2];
    let err = [csa.grab_ofs0[0] - ofs[0], csa.grab_ofs0[1] - ofs[1]];
    let err_at_angle = [
        Math.cos(rad) * err[0] - Math.sin(rad) * err[1],
        Math.sin(rad) * err[0] + Math.cos(rad) * err[1]
    ];
    return [ofs[0] + err_at_angle[0], ofs[1] + err_at_angle[1]];
}


document.getElementById('btn_run').onclick = async function() {
    let comp = get_comp_safe();
    if (!comp) {
        alert("list empty!");
        return;
    }
    document.getElementById('btn_run').disabled = true;
    document.getElementById('btn_stop').disabled = false;
    csa.stop = false;
    let parents_pre = null;
    
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
        }
        if (parents_pre && (parents_pre[0] != parents[0] || parents_pre[1] != parents[1])) {
            document.getElementById('pause_en').checked = true;
            set_board(board);
            await move_to_comp(comp);
        }
        console.log(`parents: ${parents_pre} -> ${parents}`);
        
        if (csa.stop)
            break;
        if (document.getElementById('pause_en').checked) {
            console.log(`enter wait`);
            while (document.getElementById('pause_en').checked)
                await sleep(100);
            console.log(`exit wait`);
            parents_pre = null;
            continue;
        }
        
        let comp_val = get_comp_values(comp);
        let comp_xyz = await pcb2xyz(board, comp_val[0], comp_val[1]);
        
        if (step == 0) { // show_target
            console.log('fsm show target');
            await z_keep_high();
            csa.cur_pos[0] = comp_xyz[0];
            csa.cur_pos[1] = comp_xyz[1];
            await set_motor_pos(true);
            await sleep(600);
            set_step(1);
            continue;
        }
        
        if (step == 1) { // goto_comp
            console.log('fsm goto_comp');
            await z_keep_high();
            csa.cur_pos[0] = csa.comp_search[search][0];
            csa.cur_pos[1] = csa.comp_search[search][1];
            csa.cur_pos[3] = 0;
            await set_motor_pos(true);
            if (csa.cur_pos[2] != csa.comp_top_z) {
                csa.cur_pos[2] = csa.comp_top_z;
                await set_motor_pos(true);
            }
            await sleep(800);
            set_step(2);
            continue;
        }
        
        if (step == 2) { // snap
            console.log('fsm snap');
            let ret = await cam_comp_snap();
            if (ret < 0) {
                if (++search >= csa.comp_search.length)
                    search = 0;
                set_comp_search(search);
                set_step(1);
            } else {
                set_step(3);
            }
            continue;
        }
        
        if (step == 3) { // pickup
            console.log('fsm pickup');
            csa.cur_pos[0] -= csa.grab_ofs0[0];
            csa.cur_pos[1] -= csa.grab_ofs0[1];
            if (csa.comp_height != null)
                csa.cur_pos[2] = csa.comp_base_z + csa.comp_height + 1; // 1mm space
            await set_motor_pos(true);
            await sleep(800);
            await enable_force();
            csa.cur_pos[2] = csa.comp_base_z - 1;
            await set_motor_pos(true, 6000);
            await set_pump(1);
            if (csa.comp_height == null) {
                await get_motor_pos();
                csa.comp_height = parseFloat((csa.cur_pos[2] - csa.comp_base_z).toFixed(3));
                document.getElementById('cur_height').innerText = `${csa.comp_height}`;
            }
            await sleep(600);
            await z_keep_high();
            //csa.cur_pos[3] = -csa.cv_cur_r;
            //await set_motor_pos(true, 2000);
            set_step(4);
            continue;
        }
        
        if (step == 4) { // goto_pcb
            console.log('fsm goto_pcb');
            await z_keep_high();
            // limit angle range
            let rad = (comp_val[2] - csa.cv_cur_r + comp_xyz[2]) * Math.PI / 180;
            csa.cur_pos[3] = Math.atan2(Math.sin(rad), Math.cos(rad)) * 180 / Math.PI;
            if (!document.getElementById('limit_angle').checked && Math.abs(csa.cur_pos[3]) > 90) {
                console.log('  rotate 180, before:', csa.cur_pos[3]);
                csa.cur_pos[3] = csa.cur_pos[3] > 90 ? csa.cur_pos[3] - 180 : csa.cur_pos[3] + 180;
            }
            let grab_ofs = cal_grab_ofs(csa.cur_pos[3]);
            csa.cur_pos[0] = comp_xyz[0] - grab_ofs[0];
            csa.cur_pos[1] = comp_xyz[1] - grab_ofs[1];
            await set_motor_pos(true);
            set_step(5);
            continue;
        }
        
        if (step == 5) { // putdown
            console.log('fsm putdown');
            if (!document.getElementById('putdown_en').checked) {
                document.getElementById('pause_en').checked = true;
                while (document.getElementById('pause_en').checked)
                    await sleep(100);
                // manual select comp during putdown pause
                if (get_comp_safe() != comp || get_board_safe() != board)
                    continue;
            } else {
                if (csa.comp_height != null) {
                    csa.cur_pos[2] = csa.pcb_base_z + csa.comp_height + 1; // 1mm space
                    await set_motor_pos(true);
                }
                await sleep(800);
                await enable_force();
                csa.cur_pos[2] = csa.pcb_base_z - 1;
                await set_motor_pos(true, 6000);
                await set_pump(0);
                await z_keep_high();
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
    csa.stop = true;
    document.getElementById('btn_run').disabled = false;
    document.getElementById('btn_stop').disabled = true;
};

document.getElementById('btn_stop').onclick = function() {
    csa.stop = true;
    document.getElementById('pause_en').checked = false;
    set_step(1);
};


function init_ws() {
    let ws_url = 'ws://' + window.location.hostname + ':8900';
    let ws = new WebSocket(ws_url);
    
    ws.onopen = async function(evt) {
        console.log("ws onopen");
        ws_ns.connections['server'] = ws;
        await get_motor_pos();
        await get_init_home();
        await get_camera_cfg();
        await update_coeffs();
    }
    ws.onmessage = async function(evt) {
        let dat = await blob2dat(evt.data);
        var msg = msgpack.deserialize(dat);
        //console.log("Received dat", msg);
        var sock = ws_ns.sockets[msg['dst'][1]];
        sock.recv_q.put([msg['dat'], msg['src']]);
    }
    ws.onerror = function(evt) {
        console.log("ws onerror: ", evt);
        document.body.style.backgroundColor = "gray";
    }
    ws.onclose = function(evt) {
        delete ws_ns.connections['server'];
        console.log('ws disconnected');
        document.body.style.backgroundColor = "gray";
    }
}


window.addEventListener('load', async function() {
    console.log("load app");
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
    csa, cmd_sock, db, csa_need_save
};
