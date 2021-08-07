/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { L } from './lang/lang.js'
import { escape_html, date2num, timestamp, val2hex, dat2str, dat2hex, hex2dat,
         read_file, download, readable_size, blob2dat, csv_parser, readable_float } from './utils/helper.js';
//import { konva_zoom, konva_responsive } from './utils/konva_helper.js';
import { CDWebSocket, CDWebSocketNS } from './utils/cd_ws.js';
import { Idb } from './utils/idb.js';
import { search_comp_parents, search_next_comp, search_current_comp, select_comp,
         pos_to_page, pos_from_page, csv_to_pos } from './pos_list.js';
import { csa, cmd_sock, db } from './index.js';


function csa_to_page_pos()
{
    document.getElementById('cur_pos').innerHTML =
        `${readable_float(csa.cur_pos[0])}, ${readable_float(csa.cur_pos[1])},
         ${readable_float(csa.cur_pos[2])}, ${readable_float(csa.cur_pos[3])}`;
    document.getElementById('aux_pos').innerHTML = 
        `${readable_float(csa.aux_pos[0])}, ${readable_float(csa.aux_pos[1])},
         ${readable_float(csa.aux_pos[2])}, ${readable_float(csa.aux_pos[3])}`;
}

function csa_to_page_input()
{
    document.getElementById('grab_ofs').value =
        `${readable_float(csa.grab_ofs[0])}, ${readable_float(csa.grab_ofs[1])}`;
    
    for (let i = 0; i < 3; i++) {
        if (i < csa.comp_search.length)
            document.getElementById(`comp_search${i}`).value = 
                `${readable_float(csa.comp_search[i][0])}, ${readable_float(csa.comp_search[i][1])}`;
        else
            document.getElementById(`comp_search${i}`).value = '';
    }
    
    document.getElementById('comp_top_z').value = `${readable_float(csa.comp_top_z)}`;
    document.getElementById('pcb_top_z').value = `${readable_float(csa.pcb_top_z)}`;
    document.getElementById('comp_base_z').value = `${readable_float(csa.comp_base_z)}`;
    document.getElementById('pcb_base_z').value = `${readable_float(csa.pcb_base_z)}`;
    
    document.getElementById('fiducial_pcb0').value =
        `${readable_float(csa.fiducial_pcb[0][0])}, ${readable_float(csa.fiducial_pcb[0][1])}`;
    document.getElementById('fiducial_pcb1').value =
        `${readable_float(csa.fiducial_pcb[1][0])}, ${readable_float(csa.fiducial_pcb[1][1])}`;
    
    for (let i = 0; i < 3; i++) {
        if (i < csa.fiducial_cam.length) {
            document.getElementById(`fiducial_cam${i}_0`).value = 
                `${readable_float(csa.fiducial_cam[i][0][0])}, ${readable_float(csa.fiducial_cam[i][0][1])}`;
            document.getElementById(`fiducial_cam${i}_1`).value = 
                `${readable_float(csa.fiducial_cam[i][1][0])}, ${readable_float(csa.fiducial_cam[i][1][1])}`;
        } else {
            document.getElementById(`fiducial_cam${i}_0`).value = '';
            document.getElementById(`fiducial_cam${i}_1`).value = '';
        }
    }
}

function csa_from_page_input()
{
    let xy_str;
    xy_str = document.getElementById('grab_ofs').value;
    csa.grab_ofs = [Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])];
    
    csa.comp_search = [];
    for (let i = 0; ; i++) {
        if (!document.getElementById(`comp_search${i}`))
            break;
        xy_str = document.getElementById(`comp_search${i}`).value;
        if (xy_str)
            csa.comp_search.push([Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])]);
        else
            break;
    }
    
    csa.comp_top_z = Number(document.getElementById('comp_top_z').value);
    csa.pcb_top_z = Number(document.getElementById('pcb_top_z').value);
    csa.comp_base_z = Number(document.getElementById('comp_base_z').value);
    csa.pcb_base_z = Number(document.getElementById('pcb_base_z').value);
    
    xy_str = document.getElementById('fiducial_pcb0').value;
    csa.fiducial_pcb[0] = [Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])];
    xy_str = document.getElementById('fiducial_pcb1').value;
    csa.fiducial_pcb[1] = [Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])];
    
    csa.fiducial_cam = [];
    for (let i = 0; ; i++) {
        if (!document.getElementById(`fiducial_cam${i}_0`))
            break;
        xy_str = document.getElementById(`fiducial_cam${i}_0`).value;
        let xy_str2 = document.getElementById(`fiducial_cam${i}_1`).value;
        if (xy_str && xy_str2)
            csa.fiducial_cam.push([[ Number(xy_str.split(',')[0]),  Number(xy_str.split(',')[1])],
                                   [Number(xy_str2.split(',')[0]), Number(xy_str2.split(',')[1])]]);
        else
            break;
    }
}

async function input_change() {
    csa_from_page_input();
    await db.set('tmp', 'csa', csa);
    console.log('saved');
}
window.input_change = input_change;


window.btn_update_xy = async function(name) {
    let xy = `${readable_float(csa.cur_pos[0])}, ${readable_float(csa.cur_pos[1])}`;
    document.getElementById(name).value = xy;
    await input_change();
};
window.btn_update_grab = async function(name) {
    csa.grab_ofs = [-csa.aux_pos[0], -csa.aux_pos[1]];
    let xy = `${readable_float(csa.grab_ofs[0])}, ${readable_float(csa.grab_ofs[1])}`;
    document.getElementById('grab_ofs').value = xy;
    await input_change();
};
window.btn_update_z = async function(name) {
    let z = `${readable_float(csa.cur_pos[2])}`;
    document.getElementById(name).value = z;
    await input_change();
};
window.btn_goto_xy = async function(name) {
    let xy_str = document.getElementById(name).value;
    csa.cur_pos[0] = Number(xy_str.split(',')[0]);
    csa.cur_pos[1] = Number(xy_str.split(',')[1]);
    csa_to_page_pos();
    
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_motor_pos', 'pos': csa.cur_pos, 'wait': false}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log('btn_goto_xy ret', dat);
};
window.btn_goto_z = async function(name) {
    let z = Number(document.getElementById(name).value);
    csa.cur_pos[2] = z;
    csa_to_page_pos();
    
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_motor_pos', 'pos': csa.cur_pos, 'wait': false}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log('btn_goto_z ret', dat);
};
window.btn_grab_ofs = async function(dir=1) {
    csa.cur_pos[0] += dir * csa.grab_ofs[0];
    csa.cur_pos[1] += dir * csa.grab_ofs[1];
    csa_to_page_pos();
    
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_motor_pos', 'pos': csa.cur_pos, 'wait': false}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log('btn_grab_ofs ret', dat);
};


document.getElementById('pump_en').onchange = async function() {
    let pump_en = document.getElementById('pump_en').checked;
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_pump', 'val': pump_en}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log(`set_pump ${pump_en} ret`, dat);
};

document.getElementById('camera_en').onchange = async function() {
    let camera_en = document.getElementById('camera_en').checked;
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_camera', 'val': camera_en}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log(`camera_en ${pump_en} ret`, dat);
};

document.getElementById('btn_set_home').onclick = async function() {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_home'}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log('set_home ret', dat);
    csa.cur_pos = csa.aux_pos = [0, 0, 0, 0];
    csa_to_page_pos();
};

document.getElementById('btn_reset_aux').onclick = function() {
    csa.aux_pos = [0, 0, 0, 0];
    csa_to_page_pos();
};

async function move_button(val)
{
    let speed_pow = Number(document.getElementById('move_speed').value);
    let div = Math.pow(10, speed_pow) / 100;
    let dx = val[0] * div;
    let dy = val[1] * div;
    let dz = val[2] * div;
    let dr = val[3] * div * 10;
    csa.cur_pos = [csa.cur_pos[0] + dx, csa.cur_pos[1] + dy, csa.cur_pos[2] + dz, csa.cur_pos[3] + dr];
    csa.aux_pos = [csa.aux_pos[0] + dx, csa.aux_pos[1] + dy, csa.aux_pos[2] + dz, csa.aux_pos[3] + dr];
    csa_to_page_pos();
    
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_motor_pos', 'pos': csa.cur_pos, 'wait': false}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log('set_motor_pos ret', dat);
}

window.move_button = move_button;

window.addEventListener('keydown', async function(e) {
    if (!csa.shortcuts || e.keyCode == 116) // F5
        return;
    e.preventDefault();
    console.log(e.keyCode);
    let val = [0, 0, 0, 0];
    if (e.keyCode == 37) // left
        val[0] = -1;
    else if (e.keyCode == 39) // right
        val[0] = 1;
    else if (e.keyCode == 38) // up
        val[1] = -1;
    else if (e.keyCode == 40) // down
        val[1] = 1;
    else if (e.keyCode == 33 || e.keyCode == 222) // page up, "'"
        val[2] = 1;
    else if (e.keyCode == 34 || e.keyCode == 191) // page down, "/"
        val[2] = -1;
    else if (e.keyCode == 188) // "<"
        val[3] = -1;
    else if (e.keyCode == 190) // ">"
        val[3] = 1;
    move_button(val);
});

document.getElementById('shortcuts').onclick = function() {
    csa.shortcuts = document.getElementById('shortcuts').checked;
};

export {
    csa_to_page_pos, csa_to_page_input, csa_from_page_input 
};
