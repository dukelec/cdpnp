/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { sleep } from './utils/helper.js';
import { csa_to_page_pos } from './input_ctrl.js';
import { csa, cmd_sock } from './index.js';


function update_aux() {
    let dx = csa.cur_pos[0] - csa.old_pos[0];
    let dy = csa.cur_pos[1] - csa.old_pos[1];
    let dz = csa.cur_pos[2] - csa.old_pos[2];
    let dr = csa.cur_pos[3] - csa.old_pos[3];
    csa.aux_pos = [csa.aux_pos[0] + dx, csa.aux_pos[1] + dy, csa.aux_pos[2] + dz, csa.aux_pos[3] + dr];
    csa.old_pos = [csa.cur_pos[0], csa.cur_pos[1], csa.cur_pos[2], csa.cur_pos[3]];
}

async function get_camera_cfg() {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'get_camera_cfg'}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log('get_camera_cfg ret', dat);
    document.getElementById('camera_en').checked = !!dat[0].enable;
    document.getElementById('camera_light1').checked = !!dat[0].light1;
    document.getElementById('camera_light2').checked = !!dat[0].light2;
    document.getElementById('camera_dev').value = dat[0].dev;
    document.getElementById('camera_detect').value = dat[0].detect;
}

async function set_camera_cfg(_detect=null, exposure=20) {
    let dev = Number(document.getElementById('camera_dev').value);
    let detect = _detect == null ? document.getElementById('camera_detect').value : _detect;
    let light1 = document.getElementById('camera_light1').checked;
    let light2 = document.getElementById('camera_light2').checked;
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_camera_cfg', 'dev': dev, 'detect': detect,
                           'light1': light1, 'light2': light2, 'expos': exposure}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log(`set_camera_cfg ${dev}, ${detect} ret`, dat);
}

async function set_vision_cfg(debug=false) {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_vision_cfg', 'nozzle_thresh': csa.nozzle_thresh, 'debug': debug}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log(`set_vision_cfg ret`, dat);
}

async function get_motor_pos() {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'get_motor_pos'}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log('get_cur_pos ret', dat);
    csa.cur_pos = dat[0];
    update_aux();
    csa_to_page_pos();
}

async function set_motor_pos(wait=0, speed=600000) {
    console.log(`set_motor_pos: ${csa.cur_pos}, wait: ${wait}`);
    if (speed == 600000)
        speed = Math.round(speed * csa.motor_speed);
    csa.cur_pos[0] = Math.min(Math.max(csa.cur_pos[0], 2), 300)
    csa.cur_pos[1] = Math.min(Math.max(csa.cur_pos[1], 2), 249)
    csa.cur_pos[2] = Math.min(Math.max(csa.cur_pos[2], -92), -2)
    update_aux();
    csa_to_page_pos();
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_motor_pos', 'pos': csa.cur_pos, 'wait': wait, 'speed': speed}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(wait ? 300000 : 2000);
    console.log('set_motor_pos ret', dat);
}

// 0: off, 1: valve on, 2: pump on
async function set_pump(val) {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_pump', 'val': val}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(2000);
    console.log(`set_pump ${val} ret`, dat);
    document.getElementById('pump_en').checked = val ? true : false;
}

async function pcb2xyz(pcb, cam, x, y) {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'pcb2xyz', 'pcb': pcb, 'cam': cam, 'x': x, 'y': y}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(1000);
    console.log('pcb2xyz ret', dat ? dat[0] : null);
    return dat ? dat[0] : null;
}

async function z_keep_high(wait=0, speed=600000) {
    let min_z = Math.max(csa.pcb_top_z, csa.comp_top_z);
    if (document.getElementById('pump_en').checked && csa.comp_height != null)
        min_z += csa.comp_height;
    if (csa.cur_pos[2] < min_z) {
        csa.cur_pos[2] = min_z;
        await set_motor_pos(wait, speed);
    }
}

async function enable_force() {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'enable_force'}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(1000);
    console.log('enable_force ret', dat);
    return dat ? dat[0] : null;
}

async function get_cv_cur() {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'get_cv_cur'}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(1000);
    console.log('get_cv_cur ret', dat);
    return dat ? dat[0] : null;
}

// 10mm / 344 pixel
let DIV_MM2PIXEL = 10/344;

async function cam_comp_snap(times=3) {
    let dev = Number(document.getElementById('camera_dev').value);
    let sign = dev == 1 ? 1 : -1;
    let cam_width = dev == 1 ? 600 : 800;
    let cam_height = dev == 1 ? 800 : 600;
    
    for (let i = 0; i < times; i++) {
        let cv = await get_cv_cur();
        if (cv) {
            let dx = (cv[0] - cam_width/2) * DIV_MM2PIXEL
            let dy = (cv[1] - cam_height/2) * DIV_MM2PIXEL
            console.log('cv dx dy', dx, dy)
            csa.cur_pos[0] += dx * sign
            csa.cur_pos[1] += dy * sign
            csa.cv_cur_r = cv[2] // [-89, 90]
            await set_motor_pos(100);
        } else {
            csa.cv_cur_r = null;
        }
        await sleep(600);
    }
    let cv = await get_cv_cur();
    return cv ? 0 : -1;
}


export {
    get_camera_cfg, set_camera_cfg, get_motor_pos, set_motor_pos, set_pump,
    pcb2xyz, z_keep_high, enable_force, get_cv_cur, cam_comp_snap, set_vision_cfg
};
