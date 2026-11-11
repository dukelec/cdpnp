/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { L } from './utils/lang.js?v=__V__';
import { read_file, download, readable_float, cpy, sleep, wildcard_test } from './utils/helper.js?v=__V__';
import { set_camera_cfg, get_motor_pos, set_motor_pos, set_pump, enable_force, fid_mode } from './dev_cmd.js?v=__V__';
import { csa_dft, csa, cmd_sock, db, csa_need_save, csa_prj_export, csa_cfg_export, cal_grab_ofs } from './index.js?v=__V__';
import { pld_csa_to_page, pld_csa_from_page } from './preload_ctrl.js?v=__V__';
import { pos_to_page, pos_from_page, pos_normalize, get_board_safe } from './pos_list.js?v=__V__';
import { scale_show, scale_reset, cands_draw } from './comp_track.js?v=__V__';
import { fid_lock, fid_lock_all } from './calibration.js?v=__V__';
import { fid_fit } from './fid_fit.js?v=__V__';


function disable_goto_btn(val) {
    let btn = document.getElementsByClassName('goto_btn');
    for (let b of btn)
        b.disabled = val;
    document.getElementById('pos_list').style.backgroundColor = val ? '#f0f0f0' : '';
}

// created on demand, there is no limit on the number of boards
function fiducial_rows(count) {
    let pt = (i, j) => `
        <input type="text" id="fiducial_cam${i}_${j}" onchange="input_change()">
        <button class="button is-small goto_btn" onclick="btn_goto_xy('fiducial_cam${i}_${j}')">${L('Goto')}</button>
        <button class="button is-small" onclick="btn_update_xy('fiducial_cam${i}_${j}')">${L('Update')}</button>
        <button class="button is-small goto_btn" onclick="btn_lock_xy('fiducial_cam${i}_${j}')" title="${L('Finds the fiducial near the center of the camera and moves onto it from one side, then asks you to confirm or to place it by hand')}">${L('Lock')}</button>`;
    for (let i = document.getElementsByClassName('fiducial_grp').length; i < count; i++) {
        document.getElementById('panel_row').insertAdjacentHTML('beforebegin', `
            <div id="fiducial_grp${i}" class="fiducial_grp">
                <span style="display: inline-block; min-width: 138px;">${L('Fiducial cam')} #${i}:</span>
                ${pt(i, 0)} ${pt(i, 1)}
                <button class="button is-small btn_board" onclick="btn_select_board(${i})" id="btn_board${i}">${L('Select')}</button>
                ${i ? '' : `&nbsp;|&nbsp; <button class="button is-small goto_btn" id="btn_fid_lock_all" onclick="btn_lock_all()" title="${L('Goes to every fiducial of every board and locks on it, the Stop button stops it')}">${L('Lock all')}</button>`}
                <div id="fiducial_more${i}">
                    <span style="display: inline-block; min-width: 138px;"></span>
                    ${pt(i, 2)} <span id="fiducial_pt3_${i}">${pt(i, 3)}</span>
                    <span id="fiducial_info${i}" title="${L('XY skew')}, ${L('max error')}"></span>
                </div>
            </div>`);
    }
}

// what the 3 or 4 points of a board say; a point locked on the wrong thing shows up here
function fiducial_status() {
    // the size in pixels, as the camera is told to look for it
    let hint = document.getElementById('fiducial_size_px'), mode = fid_mode();
    if (!mode) {
        hint.innerText = L('Invalid');
        hint.style.color = 'red';
        hint.title = '';
    } else {
        let v = mode.split('_').slice(1).map(Number), t = v[v.length - 1];
        let range = (d, f) => `${f}${Math.max(d - t, 0).toFixed(0)}~${(d + t).toFixed(0)}`;
        hint.innerText = `≈ ${v.length == 2 ? v[0].toFixed(1) : `${v[0].toFixed(0)}×${v[1].toFixed(0)}`} px`;
        hint.style.color = '';
        hint.title = `${L('Accepted by the detection')}: ${v.length == 2 ? range(v[0], '') : `${range(v[0], '')} × ${range(v[1], '')}`} px`;
    }
    for (let i = 0; i < csa.fiducial_cam.length; i++) {
        let e = document.getElementById(`fiducial_info${i}`);
        let f = fid_fit(csa.fiducial_pcb, csa.fiducial_cam[i]);
        if (!f) {
            e.innerText = '';
        } else if (f.collinear) {
            e.innerText = L('On a line, the first 2 are used');
            e.style.color = 'red';
        } else {
            e.innerText = `${L('skew')} ${f.skew.toFixed(3)}°` + (f.n > 3 ? `, ${L('err')} ${f.max_err.toFixed(3)} mm` : '');
            let bad = f.max_err > 0.1 || Math.abs(f.scale - 1) > 0.005 || (csa.xy_skew && Math.abs(f.skew - csa.xy_skew) > 0.05);
            e.style.color = bad ? 'red' : '';
        }
    }
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
    fiducial_rows(csa.fiducial_cam.length + 1);     // the blank one is for adding a board by hand
    let grps = document.getElementsByClassName('fiducial_grp');
    for (let i = 0; i < grps.length; i++)
        grps[i].style.display = i <= csa.fiducial_cam.length ? '' : 'none';
    for (let i = 0; i < grps.length; i++) {
        document.getElementById(`fiducial_more${i}`).style.display = csa.fiducial_pcb.length > 2 ? '' : 'none';
        document.getElementById(`fiducial_pt3_${i}`).style.display = csa.fiducial_pcb.length > 3 ? '' : 'none';
    }
    fiducial_status();
    let ref = document.getElementById('panel_ref'), ref_val = Number(ref.value);
    ref.innerHTML = csa.fiducial_cam.map((_, i) => `<option value="${i}">#${i}</option>`).join('');
    ref.value = ref_val < csa.fiducial_cam.length ? ref_val : 0;
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
    cands_draw();   // the camera's place on the tray map follows every move
    document.getElementById('cur_pos').innerHTML =
        `${readable_float(csa.cur_pos[0])}, ${readable_float(csa.cur_pos[1])},
         ${readable_float(csa.cur_pos[2])}, ${readable_float(csa.cur_pos[3])}`;
    document.getElementById('aux_pos').innerHTML = 
        `${readable_float(csa.aux_pos[0])}, ${readable_float(csa.aux_pos[1])},
         ${readable_float(csa.aux_pos[2])}, ${readable_float(csa.aux_pos[3])}`;
}

function csa_to_page_input()
{
    scale_show();
    document.getElementById('motor_speed').value = csa.motor_speed;
    document.getElementById('nozzle_expos').value = csa.nozzle_expos;
    document.getElementById('nozzle_thresh').value = csa.nozzle_thresh;
    document.getElementById('grab_ofs').value =
        `${readable_float(csa.grab_ofs[0])}, ${readable_float(csa.grab_ofs[1])}`;
    document.getElementById('nozzle_cali').value =
        `${readable_float(csa.nozzle_cali[0])}, ${readable_float(csa.nozzle_cali[1])}`;
    document.getElementById('cam1_angle').value = `${readable_float(csa.cam_angle[0])}`;
    document.getElementById('cam2_angle').value = `${readable_float(csa.cam_angle[1])}`;
    document.getElementById('xy_skew').value = `${readable_float(csa.xy_skew)}`;
    
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
    
    let xy_text = p => p ? `${readable_float(p[0])}, ${readable_float(p[1])}` : '';
    for (let j = 0; j < 4; j++)
        document.getElementById(`fiducial_pcb${j}`).value = xy_text(csa.fiducial_pcb[j]);
    document.getElementById('fiducial_size').value = csa.fiducial_size;
    document.getElementById('fiducial_size_err').value = csa.fiducial_size_err;
    document.getElementById('fiducial_pos_err').value = csa.fiducial_pos_err;
    
    fiducial_rows(csa.fiducial_cam.length + 1);
    for (let i = 0; i < document.getElementsByClassName('fiducial_grp').length; i++) {
        for (let j = 0; j < 4; j++)
            document.getElementById(`fiducial_cam${i}_${j}`).value = xy_text((csa.fiducial_cam[i] || [])[j]);
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
    csa.nozzle_expos = Number(document.getElementById('nozzle_expos').value);
    csa.nozzle_thresh = Number(document.getElementById('nozzle_thresh').value);
    let xy_str;
    xy_str = document.getElementById('grab_ofs').value;
    csa.grab_ofs = [Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])];
    xy_str = document.getElementById('nozzle_cali').value;
    csa.nozzle_cali = [Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])];
    csa.cam_angle = [Number(document.getElementById('cam1_angle').value),
                     Number(document.getElementById('cam2_angle').value)];
    csa.xy_skew = Number(document.getElementById('xy_skew').value);
    
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
    
    // points 3 and 4 are optional, a list ends at the first blank one
    csa.fiducial_pcb = [];
    for (let j = 0; j < 4; j++) {
        xy_str = document.getElementById(`fiducial_pcb${j}`).value;
        if (j >= 2 && !xy_str)
            break;
        csa.fiducial_pcb.push([Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])]);
    }
    csa.fiducial_size = document.getElementById('fiducial_size').value.trim();
    csa.fiducial_size_err = Number(document.getElementById('fiducial_size_err').value);
    csa.fiducial_pos_err = Number(document.getElementById('fiducial_pos_err').value);
    
    csa.fiducial_cam = [];
    for (let i = 0; ; i++) {
        if (!document.getElementById(`fiducial_cam${i}_0`))
            break;
        let row = [];
        for (let j = 0; j < 4; j++) {
            xy_str = document.getElementById(`fiducial_cam${i}_${j}`).value;
            if (!xy_str)
                break;
            row.push([Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])]);
        }
        if (row.length < 2)
            break;
        csa.fiducial_cam.push(row);
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

async function save_cfg() {
    let save = {'cfg_ver': 1};
    cpy(save, csa, csa_need_save);
    await db.set('tmp', 'csa', save);
    await db.set('tmp', 'list', pos_from_page());
    console.log('config saved');
    document.getElementById('btn_save_cfg').style.background = '';
}

async function input_change() {
    console.log('input_change');
    csa_from_page_input();
    auto_hide();
    document.getElementById('btn_save_cfg').style.background = 'yellow';
}
window.input_change = input_change;


// The step is along the axes of Fiducial pcb, turned by the measured angle of the reference board, as pcb2xyz does.
// The reference board keeps its index, so its place in the grid, the others are relative to it.
window.btn_panel_gen = async function() {
    if (document.getElementById('btn_run').disabled) {
        alert(L('Stop the run first'));
        return;
    }
    let step = document.getElementById('panel_step').value.split(',').map(Number);
    let nx = Number(document.getElementById('panel_x').value);
    let ny = Number(document.getElementById('panel_y').value);
    if (step.length != 2 || !step.every(isFinite) || !Number.isInteger(nx) || !Number.isInteger(ny)
            || nx < 1 || ny < 1 || (nx > 1 && !step[0]) || (ny > 1 && !step[1])) {
        alert(L('Check the step (dx, dy, not 0 where there is more than one board) and X × Y (whole numbers)'));
        return;
    }
    let ref = Number(document.getElementById('panel_ref').value);
    if (ref >= nx * ny) {
        alert(L('The reference board is outside X × Y'));
        return;
    }
    let base = csa.fiducial_cam[ref];
    let [p0, p1] = csa.fiducial_pcb;
    let pcb_d = [p1[0] - p0[0], p1[1] - p0[1]];
    let cam_d = base ? [base[1][0] - base[0][0], base[1][1] - base[0][1]] : [0, 0];
    // written this way to catch NaN too; a stale Fiducial pcb would give a wrong angle without any error
    if (!(Math.abs(Math.hypot(...cam_d) / Math.hypot(...pcb_d) - 1) < 0.05)) {
        alert(L('Locate the reference board first: Fiducial pcb and the Fiducial cam of that board must be filled, with the same distance between the two points'));
        return;
    }
    if (csa.fiducial_cam.length > 1 && !confirm(L('Replace the fiducials of the other boards?')))
        return;

    // the angle and the step are in the square coordinates, see pcb2xyz of pnp_main.py
    let k = csa.xy_skew * Math.PI / 180;
    let a = Math.atan2(cam_d[1] - cam_d[0] * k / 2, cam_d[0] - cam_d[1] * k / 2) - Math.atan2(pcb_d[1], pcb_d[0]);
    let [cos, sin] = [Math.cos(a), Math.sin(a)];
    fiducial_rows(nx * ny + 1);
    for (let i = 0; i < document.getElementsByClassName('fiducial_grp').length; i++) {
        if (i == ref)
            continue;
        let x = (i % nx - ref % nx) * step[0], y = (Math.floor(i / nx) - Math.floor(ref / nx)) * step[1];
        let [rx, ry] = [x * cos - y * sin, x * sin + y * cos];
        let [dx, dy] = [rx + ry * k / 2, ry + rx * k / 2];
        for (let j = 0; j < 4; j++)
            document.getElementById(`fiducial_cam${i}_${j}`).value = i < nx * ny && base[j] ?
                `${readable_float(base[j][0] + dx, 3)}, ${readable_float(base[j][1] + dy, 3)}` : '';
    }
    await input_change();
    let board = get_board_safe();
    await window.btn_select_board(board < nx * ny ? board : 0);   // the list may have got shorter
};

window.btn_update_xy = async function(name) {
    let xy = `${readable_float(csa.cur_pos[0])}, ${readable_float(csa.cur_pos[1])}`;
    document.getElementById(name).value = xy;
    await input_change();
};
// name: the box the result goes to, null only returns it. ask: wait for the user to confirm;
// null: the user skipped it
async function fid_lock_to(name, ask=false) {
    disable_goto_btn(true);
    try {
        let m = name ? name.match(/(\d+)_(\d+)$/) : null;
        let p = await fid_lock(ask, m ? `#${m[1]}.${Number(m[2]) + 1}` : '');
        if (name && p) {
            document.getElementById(name).value = `${readable_float(p[0])}, ${readable_float(p[1])}`;
            await input_change();
        }
        return p;
    } finally {
        disable_goto_btn(false);
    }
}

// the camera follows a new size while Fiducial is selected
window.fid_size_change = async function() {
    await input_change();
    if (document.getElementById('camera_detect').value == 'fiducial' && !document.getElementById('btn_run').disabled)
        await set_camera_cfg();
};

window.btn_lock_xy = async function(name) {
    if (document.getElementById('btn_run').disabled) {
        alert(L('Stop the run first'));
        return;
    }
    try {
        await fid_lock_to(name, true);
    } catch (err) {
        alert(err.message);
    }
};

async function fid_lock_all_run(ask=false) {
    disable_goto_btn(true);
    try {
        return await fid_lock_all(ask);
    } finally {
        disable_goto_btn(false);
        await input_change();
    }
}

window.btn_lock_all = async function() {
    if (document.getElementById('btn_run').disabled) {
        alert(L('Stop the run first'));
        return;
    }
    try {
        let r = await fid_lock_all_run(true);
        let failed = r.failed.map(([b, j]) => `#${b}.${j + 1}`).join(' ');
        alert(`${L('Locked')}: ${r.locked} / ${r.total}, ${L('largest change')} ${r.max_move.toFixed(3)} mm` +
              (failed ? `\n${L('Skipped or not found, the old value is kept')}: ${failed}` : ''));
    } catch (err) {
        alert(err.message);
    }
};

window.btn_update_xyz = async function(name) {
    let xyz = `${readable_float(csa.cur_pos[0])}, ${readable_float(csa.cur_pos[1])}, ${readable_float(csa.cur_pos[2])}`;
    document.getElementById(name).value = xyz;
    await input_change();
    if (name == "user_pos0")
        document.getElementById('btn_reset_aux').onclick();
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
        await set_motor_pos(100);
    }
    csa.cur_pos[0] = Number(xy_str.split(',')[0]);
    csa.cur_pos[1] = Number(xy_str.split(',')[1]);
    csa.cur_pos[3] = 0;
    await set_motor_pos(100);
    csa.cur_pos[2] = z;
    await set_motor_pos(100);
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
        await set_motor_pos(100);
    }
    csa.cur_pos[0] = Number(xyz_str.split(',')[0]);
    csa.cur_pos[1] = Number(xyz_str.split(',')[1]);
    csa.cur_pos[3] = 0;
    await set_motor_pos(100);
    csa.cur_pos[2] = z;
    await set_motor_pos(100);
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
    await set_motor_pos(100);
    disable_goto_btn(false);
};
window.btn_grab_ofs = async function(type, dir=1) {
    disable_goto_btn(true);
    let origin_z = csa.cur_pos[2];
    csa.cur_pos[2] = Math.min(csa.cur_pos[2] + csa.cam_dz, -2);
    await set_motor_pos(100);
    let grab_ofs = type == 0 ? cal_grab_ofs(0) : csa.grab_ofs;
    csa.cur_pos[0] -= dir * grab_ofs[0];
    csa.cur_pos[1] -= dir * grab_ofs[1];
    csa.cur_pos[3] = 0;
    await set_motor_pos(100);
    csa.cur_pos[2] = origin_z;
    await set_motor_pos(100);
    disable_goto_btn(false);
};
window.btn_detect_z = async function() {
    disable_goto_btn(true);
    if (!document.getElementById('pump_en').checked) {
        console.log('detect bottom z... (fast)');
        await enable_force();
        csa.cur_pos[2] = -92;
        await set_motor_pos(100, 12000);
        await get_motor_pos();
        console.log('detect bottom z done (fast)');
        csa.cur_pos[2] += 1;
        await set_motor_pos(100);
        await sleep(800);
    }
    console.log('detect bottom z... (slow)');
    await enable_force();
    csa.cur_pos[2] = -92;
    await set_motor_pos(100, 2000);
    await get_motor_pos();
    console.log('detect bottom z done (slow)');
    disable_goto_btn(false);
};


document.getElementById('pump_en').onchange = async function() {
    let pump_en = document.getElementById('pump_en').checked;
    if (pump_en) {
        await set_pump(csa.pump_hw_ver == 'v1' ? 2 : -70);
    } else {
        await set_pump(csa.pump_hw_ver == 'v1' ? 1 : 0);
        await sleep(500);
        await set_pump(0);
    }
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
    let dr = val[3] * (div < 10 ? div * 10 : 45);
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

document.getElementById('btn_save_cfg').onclick = async function() {
    await save_cfg();
    alert(L('Saved.'));
};

document.getElementById('btn_reset_cfg').onclick = async function() {
    cpy(csa, csa_dft, csa_cfg_export);
    csa_to_page_input();
    await input_change();
    alert(L('Ok, please save config and refresh page.'));
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
            csa_to_page_input();
            await input_change();
            alert(L('Import config succeeded'));
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
            csa_to_page_input();
            await input_change();
            pos_to_page(prj.list);
            alert(L('Import project succeeded'));
        }
        this.value = '';
    };
    input.click();
};

document.getElementById('btn_export_prj').onclick = async function() {
    let c = await db.get('tmp', 'csa');
    let l = await db.get('tmp', 'list');
    let exp_dat = { version: 'cdpnp.prj v1', csa: {}, list: pos_normalize(l) };  // v1: the list in arrays
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

document.getElementById('btn_scale_reset').onclick = async function() {
    if (!confirm(L('Forget the measured camera scale and start again from 10/344 mm per pixel?')))
        return;
    scale_reset();
    await input_change();   // the Save button turns yellow
};

document.getElementById('offset_apply').onclick = async function() {
    offset_apply();
    alert(L("Apply OK."));
};


function input_init() {
    let search = document.getElementById('input_search');
    let fiducial = document.getElementById('input_fiducial');
    let user = document.getElementById('input_user');
    for (let j = 2; j < 4; j++)     // the translation of index.html does not reach a placeholder
        document.getElementById(`fiducial_pcb${j}`).placeholder = L('Optional');
    // room of the Goto, Update and Lock buttons, so a point stands above its column of Fiducial cam
    for (let j = 0; j < 4; j++)
        document.getElementById(`fiducial_pcb${j}`).insertAdjacentHTML('afterend', ` <span style="visibility: hidden;">
            <button class="button is-small">${L('Goto')}</button>
            <button class="button is-small">${L('Update')}</button>
            <button class="button is-small">${L('Lock')}</button></span>`);
    for (let i = 0; i < 8; i++) {
        search.insertAdjacentHTML('beforeend', `
            <div id="search_grp${i}">
                <span style="display: inline-block; min-width: 138px;">${L('Comp search')} #${i}:</span>
                <input type="text" id="comp_search${i}" onchange="input_change()">
                <button class="button is-small goto_btn" onclick="btn_goto_xy('comp_search${i}')">${L('Goto')}</button>
                <button class="button is-small" onclick="btn_update_xy('comp_search${i}')">${L('Update')}</button>
                <button class="button is-small" onclick="btn_select_search(${i})" id="btn_comp_search${i}">${L('Select')}</button>
            </div>`);
    }
    fiducial.insertAdjacentHTML('beforeend', `
        <div id="panel_row">
            <span style="display: inline-block; min-width: 138px;" title="${L('Fills the other boards from the chosen one, which keeps its place in the X × Y grid. Numbered row by row, the step is along the axes of Fiducial pcb, a negative step goes the other way.')}">${L('Panel from')} <select id="panel_ref"></select>:</span>
            <input type="text" id="panel_step" placeholder="dx, dy"> mm &nbsp;|&nbsp;
            X × Y: <input type="text" id="panel_x" size="2" value="1"> × <input type="text" id="panel_y" size="2" value="1">
            <button class="button is-small" onclick="btn_panel_gen()">${L('Generate')}</button>
        </div>`);
    for (let i = 0; i < 8; i++) {
        fiducial.insertAdjacentHTML('beforeend', `
            <div id="user_grp${i}">
                <span style="display: inline-block; min-width: 138px;">${L('User pos')} #${i}:</span>
                <input type="text" id="user_name${i}" onchange="input_change()" placeholder="name">
                <input type="text" id="user_pos${i}" onchange="input_change()">
                <button class="button is-small goto_btn" onclick="btn_goto_xyz('user_pos${i}')">${L('Goto')}</button>
                <button class="button is-small" onclick="btn_update_xyz('user_pos${i}')">${L('Update')}</button>
            </div>`);
    }
    document.getElementById('user_name0').disabled = true;
    document.getElementById('user_name1').disabled = true;
    auto_hide();
}

export {
    input_init, csa_to_page_pos, csa_to_page_input, csa_from_page_input, disable_goto_btn, offset_apply, input_change, save_cfg,
    fid_lock_to, fid_lock_all_run
};
