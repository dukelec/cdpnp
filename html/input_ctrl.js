/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { read_file, download, readable_float, cpy, sleep, wildcard_test } from './utils/helper.js';
import { set_camera_cfg, get_motor_pos, set_motor_pos, set_pump, enable_force } from './dev_cmd.js';
import { csa_dft, csa, cmd_sock, db, csa_need_save, csa_prj_export, csa_cfg_export } from './index.js';
import { pld_csa_to_page, pld_csa_from_page } from './preload_ctrl.js';


function disable_goto_btn(val) {
    let btn = document.getElementsByClassName('goto_btn');
    for (let b of btn)
        b.disabled = val;
    document.getElementById('pos_list').style.backgroundColor = val ? '#f0f0f0' : '';
}

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
    skip_hide = true;
    for (let i = 0; i < 8; i++) {
        if (i < csa.user_pos.length) {
            document.getElementById(`user_grp${i}`).style.display = '';
        } else {
            document.getElementById(`user_grp${i}`).style.display = skip_hide ? '' : 'none';
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
    document.getElementById('motor_speed').value = csa.motor_speed;
    document.getElementById('grab_ofs0').value =
        `${readable_float(csa.grab_ofs0[0])}, ${readable_float(csa.grab_ofs0[1])}`;
    document.getElementById('grab_ofs180').value =
        `${readable_float(csa.grab_ofs180[0])}, ${readable_float(csa.grab_ofs180[1])}`;
    
    for (let i = 0; i < 8; i++) {
        if (i < csa.comp_search.length) {
            document.getElementById(`comp_search${i}`).value = 
                `${readable_float(csa.comp_search[i][0])}, ${readable_float(csa.comp_search[i][1])}`;
        } else {
            document.getElementById(`comp_search${i}`).value = '';
        }
    }
    
    document.getElementById('comp_cam_dz').value = `${readable_float(csa.cam_dz)}`;
    document.getElementById('comp_base_z').value = `${readable_float(csa.comp_base_z)}`;
    document.getElementById('pcb_base_z').value = `${readable_float(csa.pcb_base_z)}`;
    csa.pcb_top_z = csa.pcb_base_z + csa.cam_dz;
    csa.comp_top_z = csa.comp_base_z + csa.cam_dz;
    
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
    
    for (let i = 0; i < 8; i++) {
        if (i < csa.user_pos.length) {
            document.getElementById(`user_pos${i}`).value = 
                `${readable_float(csa.user_pos[i][1][0])}, ${readable_float(csa.user_pos[i][1][1])}, ${readable_float(csa.user_pos[i][1][2])}`;
            document.getElementById(`user_name${i}`).value = csa.user_pos[i][0];
        } else {
            document.getElementById(`user_pos${i}`).value = '';
            document.getElementById(`user_name${i}`).value = '';
        }
    }
    
    document.getElementById('offset_config').value = csa.offset_config;
    pld_csa_to_page();
}

function csa_from_page_input()
{
    csa.motor_speed = Number(document.getElementById('motor_speed').value);
    let xy_str;
    xy_str = document.getElementById('grab_ofs0').value;
    csa.grab_ofs0 = [Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])];
    xy_str = document.getElementById('grab_ofs180').value;
    csa.grab_ofs180 = [Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])];
    
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
    
    csa.cam_dz = Number(document.getElementById('comp_cam_dz').value);
    csa.comp_base_z = Number(document.getElementById('comp_base_z').value);
    csa.pcb_base_z = Number(document.getElementById('pcb_base_z').value);
    csa.pcb_top_z = csa.pcb_base_z + csa.cam_dz;
    csa.comp_top_z = csa.comp_base_z + csa.cam_dz;
    
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
    
    csa.user_pos = [];
    for (let i = 0; ; i++) {
        if (!document.getElementById(`user_pos${i}`))
            break;
        let xyz_str = document.getElementById(`user_pos${i}`).value;
        let name_str = document.getElementById(`user_name${i}`).value;
        if (xyz_str)
            csa.user_pos.push([name_str, [Number(xyz_str.split(',')[0]), Number(xyz_str.split(',')[1]), Number(xyz_str.split(',')[2])]]);
        else
            break;
    }
    
    csa.offset_config = document.getElementById('offset_config').value;
    pld_csa_from_page();
}

async function input_change() {
    csa_from_page_input();
    auto_hide();
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
window.btn_update_xyz = async function(name) {
    let xyz = `${readable_float(csa.cur_pos[0])}, ${readable_float(csa.cur_pos[1])}, ${readable_float(csa.cur_pos[2])}`;
    document.getElementById(name).value = xyz;
    await input_change();
    if (name == "user_pos0")
        document.getElementById('btn_reset_aux').onclick();
};
window.btn_update_grab = async function(type) {
    let abs_xy = [Math.abs(csa.aux_pos[0]), Math.abs(csa.aux_pos[1])];
    if (type) {
        csa.grab_ofs180 = [abs_xy[0], abs_xy[1]];
    } else {
        csa.grab_ofs0 = [abs_xy[0], abs_xy[1]];
    }
    let xy = `${readable_float(abs_xy[0])}, ${readable_float(abs_xy[1])}`;
    document.getElementById(`grab_ofs${type}`).value = xy;
    await input_change();
};
window.btn_update_z = async function(name) {
    let z = `${readable_float(csa.cur_pos[2])}`;
    document.getElementById(name).value = z;
    await input_change();
};
window.btn_goto_xy = async function(name) {
    let xy_str = document.getElementById(name).value;
    if (!xy_str)
        return;
    disable_goto_btn(true);
    let z = name.startsWith('comp_search') ? csa.comp_top_z : (name == 'pld_search' ? csa.pld_top_z : csa.pcb_top_z);
    let z_middle = Math.min(Math.max(z, csa.cur_pos[2]) + csa.cam_dz, -2);
    if (csa.cur_pos[2] < z_middle) {
        csa.cur_pos[2] = z_middle;
        await set_motor_pos(true);
    }
    csa.cur_pos[0] = Number(xy_str.split(',')[0]);
    csa.cur_pos[1] = Number(xy_str.split(',')[1]);
    csa.cur_pos[3] = 0;
    await set_motor_pos(true);
    csa.cur_pos[2] = z;
    await set_motor_pos(true);
    disable_goto_btn(false);
};
window.btn_goto_xyz = async function(name) {
    let xyz_str = document.getElementById(name).value;
    if (!xyz_str)
        return;
    disable_goto_btn(true);
    let z = Number(xyz_str.split(',')[2]);
    let z_middle = Math.min(Math.max(z, csa.cur_pos[2]) + csa.cam_dz, -2);
    if (csa.cur_pos[2] < z_middle) {
        csa.cur_pos[2] = z_middle;
        await set_motor_pos(true);
    }
    csa.cur_pos[0] = Number(xyz_str.split(',')[0]);
    csa.cur_pos[1] = Number(xyz_str.split(',')[1]);
    csa.cur_pos[3] = 0;
    await set_motor_pos(true);
    csa.cur_pos[2] = z;
    await set_motor_pos(true);
    if (name == "user_pos0")
        document.getElementById('btn_reset_aux').onclick();
    disable_goto_btn(false);
};
window.btn_goto_z = async function(name) {
    disable_goto_btn(true);
    if (name == 'inc_camera_dz') {
        csa.cur_pos[2] = csa.cur_pos[2] + csa.cam_dz;
    } else if (name == 'dec_camera_dz') {
        csa.cur_pos[2] = csa.cur_pos[2] - csa.cam_dz;
    } else if (name == 'pcb_top_z') {
        csa.cur_pos[2] = csa.pcb_base_z + csa.cam_dz;
    } else if (name == 'comp_top_z') {
        csa.cur_pos[2] = csa.pcb_base_z + csa.cam_dz;
    } else if (name == 'pld_top_z') {
        csa.cur_pos[2] = csa.pld_base_z + csa.cam_dz;
    } else {
        csa.cur_pos[2] = Number(document.getElementById(name).value);
    }
    await set_motor_pos(true);
    disable_goto_btn(false);
};
window.btn_goto_r = async function(angle) {
    disable_goto_btn(true);
    csa.cur_pos[3] = angle;
    await set_motor_pos(true);
    disable_goto_btn(false);
};
window.btn_grab_ofs = async function(type, dir=1) {
    disable_goto_btn(true);
    let origin_z = csa.cur_pos[2];
    csa.cur_pos[2] = Math.min(csa.cur_pos[2] + csa.cam_dz, -2);
    await set_motor_pos(true);
    let grab_ofs = type ? csa.grab_ofs180 : csa.grab_ofs0;
    csa.cur_pos[0] -= dir * grab_ofs[0];
    csa.cur_pos[1] -= dir * grab_ofs[1];
    csa.cur_pos[3] = type ? 180 : 0;
    await set_motor_pos(true);
    csa.cur_pos[2] = origin_z;
    await set_motor_pos(true);
    disable_goto_btn(false);
};
window.btn_detect_z = async function() {
    disable_goto_btn(true);
    if (!document.getElementById('pump_en').checked) {
        console.log('detect bottom z... (fast)');
        await enable_force();
        csa.cur_pos[2] = -92;
        await set_motor_pos(true, 12000);
        await get_motor_pos();
        console.log('detect bottom z done (fast)');
        csa.cur_pos[2] += 1;
        await set_motor_pos(true);
        await sleep(800);
    }
    console.log('detect bottom z... (slow)');
    await enable_force();
    csa.cur_pos[2] = -92;
    await set_motor_pos(true, 2000);
    await get_motor_pos();
    console.log('detect bottom z done (slow)');
    disable_goto_btn(false);
};


document.getElementById('pump_en').onchange = async function() {
    let pump_en = document.getElementById('pump_en').checked;
    await set_pump(pump_en);
};

async function set_camera_en(enable) {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_camera', 'val': enable}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log(`camera_en ${camera_en} ret`, dat);
    await set_camera_cfg();
};
async function _set_camera_cfg() {
    await set_camera_cfg();
}
async function set_camera_dev() {
    if (document.getElementById('camera_en').checked) {
        await set_camera_en(false);
        await set_camera_cfg();
        await set_camera_en(true);
    } else {
        await set_camera_cfg();
    }
}
document.getElementById('camera_en').onchange = async function() {
    await set_camera_en(document.getElementById('camera_en').checked);
};
document.getElementById('camera_light1').onchange = _set_camera_cfg
document.getElementById('camera_light2').onchange = _set_camera_cfg
document.getElementById('camera_detect').onchange = _set_camera_cfg;
document.getElementById('camera_dev').onchange = set_camera_dev;

async function camera_update_bg()
{
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'update_camera_bg'}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log(`update_camera_bg ret`, dat);
}
async function camera_remove_bg()
{
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'remove_camera_bg'}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(500);
    console.log(`remove_camera_bg ret`, dat);
}
window.camera_update_bg = camera_update_bg;
window.camera_remove_bg = camera_remove_bg;

document.getElementById('btn_reset_aux').onclick = function() {
    csa.aux_pos = [0, 0, 0, 0];
    csa_to_page_pos();
};

async function move_button(val)
{
    let speed_pow = Number(document.getElementById('move_speed').value - 1);
    let div = Math.pow(10, speed_pow) / 100;
    let dx = val[0] * div;
    let dy = val[1] * div;
    let dz = val[2] * div;
    let dr = val[3] * div * 10;
    csa.cur_pos = [csa.cur_pos[0] + dx, csa.cur_pos[1] + dy, csa.cur_pos[2] + dz, csa.cur_pos[3] + dr];
    await set_motor_pos();
}
window.move_button = move_button;

window.addEventListener('keydown', async function(e) {
    if (document.activeElement.type == 'text' || document.activeElement.type == 'textarea')
        return;
    console.log(e.keyCode);
    if (e.keyCode == 32) { // space
        e.preventDefault();
        if (document.getElementById('btn_stop').disabled)
            document.getElementById('pause_en').checked = false;
        else
            document.getElementById('pause_en').checked = !document.getElementById('pause_en').checked;
        document.getElementById('btn_pld_clear').onclick();
        return;
    }
    if (e.keyCode >= 49 && e.keyCode <= 52) { // 1, 2, 3, 4
        e.preventDefault();
        document.getElementById('move_speed').value = String.fromCharCode(e.keyCode);
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
    e.preventDefault();
    move_button(val);
});

document.getElementById('btn_reset_cfg').onclick = async function() {
    cpy(csa, csa_dft, csa_cfg_export);
    await db.set('tmp', 'csa', csa);
    alert('Refresh page...');
    location.reload();
};

document.getElementById('btn_import_cfg').onclick = async function() {
    //let input = document.createElement('input');
    //cpy(input, {type: 'file', accept: '*.json'}, ['type', 'accept']);
    let input = document.getElementById('input_file');
    input.accept = '.json';
    input.onchange = async function () {
        var files = this.files;
        if (files && files.length) {
            let file = files[0];
            let data = await read_file(file);
            let data_str = new TextDecoder().decode(data);
            let cfg = JSON.parse(data_str);
            if (!cfg || !cfg.version || !cfg.version.startsWith('cdpnp.cfg')) {
                alert(L('Format error'));
                this.value = '';
                return;
            }
            console.log('import cfg dat:', cfg);
            cpy(csa, cfg.csa, csa_cfg_export);
            await db.set('tmp', 'csa', csa);
            alert('Import config succeeded');
            location.reload();
        }
        this.value = '';
    };
    input.click();
};

document.getElementById('btn_export_cfg').onclick = async function() {
    let c = await db.get('tmp', 'csa');
    let exp_dat = { version: 'cdpnp.cfg v0', csa: {}};
    cpy(exp_dat.csa, csa, csa_cfg_export);
    console.info('export cfg data:', exp_dat);
    let file_dat = JSON.stringify(exp_dat, null, 4);
    download(file_dat, 'cdpnp.cfg.json');
};

document.getElementById('btn_import_prj').onclick = async function() {
    //let input = document.createElement('input');
    //cpy(input, {type: 'file', accept: '*.json'}, ['type', 'accept']);
    let input = document.getElementById('input_file');
    input.accept = '.json';
    input.onchange = async function () {
        var files = this.files;
        if (files && files.length) {
            let file = files[0];
            let data = await read_file(file);
            let data_str = new TextDecoder().decode(data);
            let prj = JSON.parse(data_str);
            if (!prj || !prj.version || !prj.version.startsWith('cdpnp.prj')) {
                alert(L('Format error'));
                this.value = '';
                return;
            }
            console.log('import prj dat:', prj);
            cpy(csa, prj.csa, csa_prj_export);
            await db.set('tmp', 'csa', csa);
            await db.set('tmp', 'list', prj.list);
            alert('Import project succeeded');
            location.reload();
        }
        this.value = '';
    };
    input.click();
};

document.getElementById('btn_export_prj').onclick = async function() {
    let c = await db.get('tmp', 'csa');
    let l = await db.get('tmp', 'list');
    let exp_dat = { version: 'cdpnp.prj v0', csa: {}, list: l};
    cpy(exp_dat.csa, csa, csa_prj_export);
    console.info('export prj data:', exp_dat);
    let file_dat = JSON.stringify(exp_dat, null, 4);
    download(file_dat, 'cdpnp.prj.json');
};


function offset_apply() {
    let lines = csa.offset_config.split("\n");
    let offsets = {};
    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];
        if (!line || line.startsWith("//"))
            continue;
        let wildcard = line.split(":")[0];
        let xy_str1 = line.split(":")[1].split("|")[0];
        let xy_str2 = line.split(":")[1].split("|")[1];
        let offset1 = [Number(xy_str1.split(',')[0]), Number(xy_str1.split(',')[1])];
        let offset2 = [Number(xy_str2.split(',')[0]), Number(xy_str2.split(',')[1])];
        offsets[wildcard] = `${offset1[0]}, ${offset1[1]} | ${offset2[0]}, ${offset2[1]}`;
    }
    console.log(`offsets:`, offsets);
    
    let footprint_list = pos_list.getElementsByClassName('list_footprint');
    for (let elm of footprint_list) {
        let subs = elm.querySelectorAll('td');
        subs[1].innerText = '--';
    }
    for (let elm of footprint_list) {
        let subs = elm.querySelectorAll('td');
        for (let wildcard in offsets) {
            if (wildcard_test(subs[0].innerText, wildcard))
                subs[1].innerText = offsets[wildcard];
        }
    }
};

document.getElementById('offset_apply').onclick = async function() {
    offset_apply();
    alert("Apply OK.");
};


function input_init() {
    let search = document.getElementById('input_search');
    let fiducial = document.getElementById('input_fiducial');
    let user = document.getElementById('input_user');
    for (let i = 0; i < 8; i++) {
        search.insertAdjacentHTML('beforeend', `
            <div id="search_grp${i}">
                <span style="display: inline-block; min-width: 138px;">Comp search #${i}:</span>
                <input type="text" id="comp_search${i}" onchange="input_change()">
                <button class="button is-small goto_btn" onclick="btn_goto_xy('comp_search${i}')">Goto</button>
                <button class="button is-small" onclick="btn_update_xy('comp_search${i}')">Update</button>
                <button class="button is-small" onclick="btn_select_search(${i})" id="btn_comp_search${i}">Select</button>
            </div>`);
    }
    for (let i = 0; i < 10; i++) {
        fiducial.insertAdjacentHTML('beforeend', `
            <div id="fiducial_grp${i}">
                <span style="display: inline-block; min-width: 138px;">Fiducial cam #${i}:</span>
                <input type="text" id="fiducial_cam${i}_0" onchange="input_change()">
                <button class="button is-small goto_btn" onclick="btn_goto_xy('fiducial_cam${i}_0')">Goto</button>
                <button class="button is-small" onclick="btn_update_xy('fiducial_cam${i}_0')">Update</button>
                <input type="text" id="fiducial_cam${i}_1" onchange="input_change()">
                <button class="button is-small goto_btn" onclick="btn_goto_xy('fiducial_cam${i}_1')">Goto</button>
                <button class="button is-small" onclick="btn_update_xy('fiducial_cam${i}_1')">Update</button>
                <button class="button is-small" onclick="btn_select_board(${i})" id="btn_board${i}">Select</button>
            </div>`);
    }
    for (let i = 0; i < 8; i++) {
        fiducial.insertAdjacentHTML('beforeend', `
            <div id="user_grp${i}">
                <span style="display: inline-block; min-width: 138px;">User pos #${i}:</span>
                <input type="text" id="user_name${i}" onchange="input_change()" placeholder="name">
                <input type="text" id="user_pos${i}" onchange="input_change()">
                <button class="button is-small goto_btn" onclick="btn_goto_xyz('user_pos${i}')">Goto</button>
                <button class="button is-small" onclick="btn_update_xyz('user_pos${i}')">Update</button>
            </div>`);
    }
    document.getElementById('user_name0').disabled = true;
    document.getElementById('user_name1').disabled = true;
    auto_hide();
}

export {
    input_init, csa_to_page_pos, csa_to_page_input, csa_from_page_input, disable_goto_btn, offset_apply
};
