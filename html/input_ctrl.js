/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { L } from './lang/lang.js'
import { escape_html, date2num, timestamp, val2hex, dat2str, dat2hex, hex2dat,
         read_file, download, readable_size, blob2dat, csv_parser, readable_float, cpy } from './utils/helper.js';
//import { konva_zoom, konva_responsive } from './utils/konva_helper.js';
import { CDWebSocket, CDWebSocketNS } from './utils/cd_ws.js';
import { Idb } from './utils/idb.js';
import { search_comp_parents, search_next_comp, search_current_comp, select_comp,
         pos_to_page, pos_from_page, csv_to_pos } from './pos_list.js';
import { get_init_home, get_motor_pos, set_motor_pos, set_pump, update_coeffs, pcb2xyz,
         z_keep_high, enable_force, get_cv_cur, cam_comp_snap } from './dev_cmd.js';
import { csa, cmd_sock, db, csa_need_save } from './index.js';


function auto_hide() {
    let skip_hide = true;
    for (let i = 0; i < 8; i++) {
        if (i < csa.comp_search.length) {
            document.getElementById(`search_grp${i}`).style.display = '';
        } else {
            document.getElementById(`search_grp${i}`).style.display = skip_hide ? '' : 'none';
            skip_hide = false;
        }
    }
    skip_hide = true;
    for (let i = 0; i < 10; i++) {
        if (i < csa.fiducial_cam.length) {
            document.getElementById(`fiducial_grp${i}`).style.display = '';
        } else {
            document.getElementById(`fiducial_grp${i}`).style.display = skip_hide ? '' : 'none';
            skip_hide = false;
        }
    }
}

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
    
    let skip_hide = true;
    for (let i = 0; i < 8; i++) {
        if (i < csa.comp_search.length) {
            document.getElementById(`comp_search${i}`).value = 
                `${readable_float(csa.comp_search[i][0])}, ${readable_float(csa.comp_search[i][1])}`;
        } else {
            document.getElementById(`comp_search${i}`).value = '';
        }
    }
    
    document.getElementById('comp_top_z').value = `${readable_float(csa.comp_top_z)}`;
    document.getElementById('pcb_top_z').value = `${readable_float(csa.pcb_top_z)}`;
    document.getElementById('comp_base_z').value = `${readable_float(csa.comp_base_z)}`;
    document.getElementById('pcb_base_z').value = `${readable_float(csa.pcb_base_z)}`;
    
    document.getElementById('fiducial_pcb0').value =
        `${readable_float(csa.fiducial_pcb[0][0])}, ${readable_float(csa.fiducial_pcb[0][1])}`;
    document.getElementById('fiducial_pcb1').value =
        `${readable_float(csa.fiducial_pcb[1][0])}, ${readable_float(csa.fiducial_pcb[1][1])}`;
    
    for (let i = 0; i < 10; i++) {
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
    auto_hide();
    await update_coeffs();
    let save = {'cfg_ver': 1};
    cpy(save, csa, csa_need_save);
    await db.set('tmp', 'csa', save);
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
    await set_motor_pos();
};
window.btn_goto_z = async function(name) {
    let z = Number(document.getElementById(name).value);
    csa.cur_pos[2] = z;
    csa_to_page_pos();
    await set_motor_pos();
};
window.btn_grab_ofs = async function(dir=1) {
    csa.cur_pos[0] += dir * csa.grab_ofs[0];
    csa.cur_pos[1] += dir * csa.grab_ofs[1];
    csa_to_page_pos();
    await set_motor_pos();
};
window.btn_detect_z = async function() {
    console.log('detect bottom z...');
    await enable_force();
    csa.cur_pos[2] = -90;
    await set_motor_pos(true, 2000);
    await get_motor_pos();
    console.log('detect bottom z done');
};


document.getElementById('pump_en').onchange = async function() {
    let pump_en = document.getElementById('pump_en').checked;
    await set_pump(pump_en);
};

document.getElementById('camera_en').onchange = async function() {
    let camera_en = document.getElementById('camera_en').checked;
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_camera', 'val': camera_en}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log(`camera_en ${camera_en} ret`, dat);
};

async function set_camera_cfg() {
    let limit_angle = document.getElementById('limit_angle').checked;
    let cv_detect = document.getElementById('cv_detect').checked;
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_camera_cfg', 'limit': limit_angle, 'detect': cv_detect}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log(`set_camera_cfg ${limit_angle}, ${cv_detect} ret`, dat);
}
document.getElementById('limit_angle').onchange = set_camera_cfg;
document.getElementById('cv_detect').onchange = set_camera_cfg;

document.getElementById('btn_set_home').onclick = async function() {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_home'}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log('set_home ret', dat);
    csa.old_pos = csa.cur_pos = csa.aux_pos = [0, 0, 0, 0];
    csa_to_page_pos();
    document.getElementById('btn_set_home').style.backgroundColor = '';
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
    csa_to_page_pos();
    await set_motor_pos();
}

window.move_button = move_button;

window.addEventListener('keydown', async function(e) {
    if (!csa.shortcuts || e.keyCode == 116) // F5
        return;
    e.preventDefault();
    console.log(e.keyCode);
    if (e.keyCode == 32) { // space
        document.getElementById('pause_en').checked = true;
        return;
    }
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
    else
        return;
    move_button(val);
});

document.getElementById('shortcuts').onclick = function() {
    csa.shortcuts = document.getElementById('shortcuts').checked;
};

document.getElementById('btn_reset').onclick = async function() {
    await db.set('tmp', 'csa', null);
    alert('Refresh page...');
    location.reload();
};

document.getElementById('btn_import').onclick = async function() {
    //let input = document.createElement('input');
    //cpy(input, {type: 'file', accept: '*.cdg'}, ['type', 'accept']);
    let input = document.getElementById('input_file');
    input.accept = '.json';
    input.onchange = async function () {
        var files = this.files;
        if (files && files.length) {
            let file = files[0];
            let data = await read_file(file);
            //let prj = msgpack.deserialize(data);
            let data_str = new TextDecoder().decode(data);
            let prj = JSON.parse(data_str);
            if (!prj || !prj.version || !prj.version.startsWith('cdpnp')) {
                alert(L('Format error'));
                this.value = '';
                return;
            }
            console.log('import dat:', prj);
            await db.set('tmp', 'csa', prj.csa);
            await db.set('tmp', 'list', prj.list);
            alert('Import succeeded');
            location.reload();
        }
        this.value = '';
    };
    input.click();
};

document.getElementById('btn_export').onclick = async function() {
    let c = await db.get('tmp', 'csa');
    let l = await db.get('tmp', 'list');
    //await db.set('tmp', 'list', null);
    let exp_dat = { version: 'cdpnp v0', csa: c, list: l};
    console.info('export_data:', exp_dat);
    //let file_dat = msgpack.serialize(exp_dat);
    let file_dat = JSON.stringify(exp_dat, null, 4);
    download(file_dat, 'cdpnp.json');
};


function input_init() {
    let search = document.getElementById('input_search');
    let fiducial = document.getElementById('input_fiducial');
    for (let i = 0; i < 8; i++) {
        search.insertAdjacentHTML('beforeend', `
            <div id="search_grp${i}">
                <span style="display: inline-block; min-width: 130px;">Comp search #${i}:</span>
                <input type="text" id="comp_search${i}" onchange="input_change()">
                <button class="button is-small" onclick="btn_goto_xy('comp_search${i}')">Goto</button>
                <button class="button is-small" onclick="btn_update_xy('comp_search${i}')">Update</button>
                <button class="button is-small" onclick="btn_select_search(${i})" id="btn_comp_search${i}">Select</button>
            </div>`);
    }
    for (let i = 0; i < 10; i++) {
        fiducial.insertAdjacentHTML('beforeend', `
            <div id="fiducial_grp${i}">
                <span style="display: inline-block; min-width: 130px;">Fiducial cam #${i}:</span>
                <input type="text" id="fiducial_cam${i}_0" onchange="input_change()">
                <button class="button is-small" onclick="btn_goto_xy('fiducial_cam${i}_0')">Goto</button>
                <button class="button is-small" onclick="btn_update_xy('fiducial_cam${i}_0')">Update</button>
                <input type="text" id="fiducial_cam${i}_1" onchange="input_change()">
                <button class="button is-small" onclick="btn_goto_xy('fiducial_cam${i}_1')">Goto</button>
                <button class="button is-small" onclick="btn_update_xy('fiducial_cam${i}_1')">Update</button>
                <button class="button is-small" onclick="btn_select_board(${i})" id="btn_board${i}">Select</button>
            </div>`);
    }
    auto_hide();
}

export {
    input_init, csa_to_page_pos, csa_to_page_input, csa_from_page_input
};
