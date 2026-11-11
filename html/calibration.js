/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { L } from './utils/lang.js?v=__V__';
import { readable_float, sleep } from './utils/helper.js?v=__V__';
import { get_camera_cfg, get_motor_pos, set_motor_pos, check_suck_pressure, set_pump, get_cv_cur, get_cv_comps,
         z_keep_high, enable_force, cam_comp_snap, set_camera_cfg, set_vision_cfg, fid_mode, detect_for_parts } from './dev_cmd.js?v=__V__';
import { set_step, get_step_safe, set_comp_search, get_comp_search, get_board_safe } from './pos_list.js?v=__V__';
import { csa_to_page_input, input_change } from './input_ctrl.js?v=__V__';
import { csa, cal_grab_ofs, rotate_vector, show_banner } from './index.js?v=__V__';
import { px2mm, scale_info, scale_info_of, scale_set } from './comp_track.js?v=__V__';
import { fid_fit } from './fid_fit.js?v=__V__';


document.getElementById('btn_cali_offset').onclick = async function() {
    if (!detect_for_parts()) {
        alert(L("please set camera vision detect method!"));
        return;
    }
    if (!document.getElementById('btn_stop').disabled) {
        alert(L("please stop smt first!"));
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
    csa.comp_height = null;
    document.getElementById('cur_height').innerText = `--`;
    
    let z_middle = Math.min(csa.cur_pos[2] + csa.cam_dz, -2);
    if (csa.cur_pos[2] < z_middle) {
        csa.cur_pos[2] = z_middle;
        await set_motor_pos(100);
    }
    
    set_step(1);
    let cali_cnt = 0;
    let cali_dat = [];
    
    while (true) {
        let step = get_step_safe();
        let search = get_comp_search();
        console.log(`step: ${step}, search: ${search}, cali_cnt: ${cali_cnt}`);
        
        if (csa.stop)
            break;
        if (document.getElementById('pause_en').checked) {
            console.log(`enter wait`);
            while (document.getElementById('pause_en').checked)
                await sleep(100);
            console.log(`exit wait`);
            continue;
        }
        
        if (step == 0 || step == 4 || step == 5) {
            set_step(1);
            continue;
        }
        
        if (step == 1) { // goto_comp
            console.log('fsm goto_comp');
            document.getElementById('camera_light1').checked = false;
            await document.getElementById('camera_light1').onchange();
            await z_keep_high(70);
            if (cali_dat.length) {
                csa.cur_pos[0] = cali_dat[cali_dat.length-1][0];
                csa.cur_pos[1] = cali_dat[cali_dat.length-1][1];
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
            set_step(2);
            continue;
        }
        
        if (step == 2) { // snap
            console.log('fsm snap');
            document.getElementById('camera_light1').checked = false;
            await document.getElementById('camera_light1').onchange();
            let ret = await cam_comp_snap();
            if (ret < 0) {
                if (++search >= csa.comp_search.length)
                    search = 0;
                set_comp_search(search);
                set_step(1);
            } else {
                set_step(3);
                console.log(`cali_cnt: ${cali_cnt}, csa.cur_pos: ${csa.cur_pos}`);
                cali_dat.push([csa.cur_pos[0], csa.cur_pos[1]]);
                if (++cali_cnt >= 2)
                    break;
            }
            continue;
        }
        
        if (step == 3) { // pickup
            console.log('fsm pickup');
            csa.cur_pos[0] -= csa.grab_ofs[0];
            csa.cur_pos[1] -= csa.grab_ofs[1];
            csa.cur_pos[3] = 0;
            if (csa.comp_height != null)
                csa.cur_pos[2] = csa.comp_base_z + csa.comp_height + 1; // 1mm space
            await set_motor_pos(100);
            await sleep(800);
            await enable_force();
            csa.cur_pos[2] = csa.comp_base_z - 1;
            await set_motor_pos(100, csa.motor_speed >= 0.6 ? 12000 : 6000);
            await set_pump(csa.pump_hw_ver == 'v1' ? 2 : -70);
            if (csa.comp_height == null) {
                await get_motor_pos();
                csa.comp_height = Math.max(parseFloat((csa.cur_pos[2] - csa.comp_base_z).toFixed(3)), 0);
                document.getElementById('cur_height').innerText = `${csa.comp_height}`;
            }
            await sleep(600);
            await z_keep_high(70, 260000);
            if (await check_suck_pressure())
                break;
            csa.cur_pos[3] = 180;
            await set_motor_pos(100);
            set_step(6);
            continue;
        }
        
        if (step == 6) { // putdown
            console.log('fsm putdown');
            if (csa.comp_height != null)
                csa.cur_pos[2] = csa.comp_base_z + csa.comp_height + 1; // 1mm space
            await set_motor_pos(100);

            await sleep(800);
            await enable_force();
            csa.cur_pos[2] = csa.pcb_base_z - 1;
            await set_motor_pos(100, csa.motor_speed >= 0.6 ? 12000 : 6000);
            await set_pump(csa.pump_hw_ver == 'v1' ? 1 : 0);

            await sleep(500);
            await z_keep_high(70);
            set_step(1);
            await set_pump(0);
        }
        
    }
    console.log('cali_offset finished');
    csa.stop = true;
    document.getElementById('btn_run').disabled = false;
    document.getElementById('btn_stop').disabled = true;
    csa.comp_height = null;
    document.getElementById('cur_height').innerText = `--`;
    csa.cur_pos[3] = 0;
    document.getElementById('btn_pld_clear').onclick();
    await set_motor_pos();
    set_step(1);
    
    if (cali_cnt < 2)
        return;
    
    let delta_x = (cali_dat[1][0] - cali_dat[0][0]) / 2;
    let delta_y = (cali_dat[1][1] - cali_dat[0][1]) / 2;
    
    let is_confirm = confirm(`Add offset: ${readable_float(delta_x)}, ${readable_float(delta_y)}`);
    if (is_confirm) {
        csa.grab_ofs[0] += delta_x;
        csa.grab_ofs[1] += delta_y;
        csa_to_page_input();
        await input_change();
        console.log('offset added');
    }
};


document.getElementById('btn_cali_nozzle').onclick = async function() {
    if (!document.getElementById('camera_detect').value.startsWith('cali_nozzle')) {
        alert(L("please set camera vision detect method for nozzle calibration!"));
        return;
    }
    console.log("auto enable camera before run task");
    document.getElementById('camera_dev').value = 2;
    document.getElementById('camera_en').checked = true;
    document.getElementById('camera_light1').checked = false;
    document.getElementById('camera_light2').checked = true;
    await document.getElementById('camera_dev').onchange();
    
    await set_camera_cfg(document.getElementById('camera_detect').value, csa.nozzle_expos);
    await set_vision_cfg();
    
    await window.btn_goto_xyz('user_pos0'); // goto position for calibration
    
    if (document.getElementById('pause_en').checked)
        return;
    let ret = await cam_comp_snap();
    console.log(`csa.cur_pos at 0: ${csa.cur_pos}`);
    let x0 = csa.cur_pos[0];
    let y0 = csa.cur_pos[1];
    
    csa.cur_pos[3] = 180;
    await set_motor_pos(100);
    
    if (document.getElementById('pause_en').checked)
        return;
    ret = await cam_comp_snap();
    console.log(`csa.cur_pos at 180: ${csa.cur_pos}`);
    let x180 = csa.cur_pos[0];
    let y180 = csa.cur_pos[1];
    
    console.log('cali_nozzle finished');
    let delta_x = (x180 - x0) / 2;
    let delta_y = (y180 - y0) / 2;
    
    let is_confirm = confirm(`Update nozzle cali data: ${readable_float(delta_x)}, ${readable_float(delta_y)} and the cali pos`);
    if (is_confirm) {
        csa.nozzle_cali[0] = delta_x;
        csa.nozzle_cali[1] = delta_y;
        csa.user_pos[0][1][0] = x0 + delta_x;
        csa.user_pos[0][1][1] = y0 + delta_y;
        csa_to_page_input();
        await input_change();
        console.log('nozzle cali data updated');
        
    }
    if (document.getElementById('pause_en').checked)
        return;
    csa.cur_pos[0] = csa.user_pos[0][1][0];
    csa.cur_pos[1] = csa.user_pos[0][1][1];
    csa.cur_pos[3] = 0;
    await set_motor_pos();
};


document.getElementById('btn_update_vision').onclick = async function() {
    let debug_en = document.getElementById('vision_debug_en').checked;
    await set_camera_cfg(document.getElementById('camera_detect').value, csa.nozzle_expos);
    await set_vision_cfg(debug_en);
};


document.getElementById('btn_cali_cam1').onclick = async function() {
    if (!detect_for_parts()) {
        alert(L("please set camera vision detect method!"));
        return;
    }
    if (!document.getElementById('btn_stop').disabled) {
        alert(L("please stop smt first!"));
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
    csa.comp_height = null;
    document.getElementById('cur_height').innerText = `--`;
    
    let z_middle = Math.min(csa.cur_pos[2] + csa.cam_dz, -2);
    if (csa.cur_pos[2] < z_middle) {
        csa.cur_pos[2] = z_middle;
        await set_motor_pos(100);
    }
    
    set_step(1);
    let angle_avg = null;
    
    while (true) {
        let step = get_step_safe();
        let search = get_comp_search();
        console.log(`step: ${step}, search: ${search}`);
        
        if (csa.stop)
            break;
        if (document.getElementById('pause_en').checked) {
            console.log(`enter wait`);
            while (document.getElementById('pause_en').checked)
                await sleep(100);
            console.log(`exit wait`);
            continue;
        }
        
        if (step != 1 && step != 2) {
            set_step(1);
            continue;
        }
        
        if (step == 1) { // goto_comp
            console.log('fsm goto_comp');
            document.getElementById('camera_light1').checked = false;
            await document.getElementById('camera_light1').onchange();
            await z_keep_high(70);
            csa.cur_pos[0] = csa.comp_search[search][0];
            csa.cur_pos[1] = csa.comp_search[search][1];
            csa.cur_pos[3] = 0;
            if (csa.cur_pos[2] != csa.comp_top_z) {
                await set_motor_pos(70);
                csa.cur_pos[2] = csa.comp_top_z;
                await set_motor_pos(100);
            } else {
                await set_motor_pos(100);
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
                if (++search >= csa.comp_search.length)
                    search = 0;
                set_comp_search(search);
                set_step(1);
            } else {
                set_step(1);
                let x_bk = csa.cur_pos[0];
                let y_bk = csa.cur_pos[1];
                console.log(`csa.cur_pos: ${csa.cur_pos}`);
                
                let cv = await get_cv_cur();
                console.log(`cv 0,0: ${cv[0]}, ${cv[1]}`);

                csa.cur_pos[0] = x_bk + 4;
                csa.cur_pos[1] = y_bk;
                await set_motor_pos(100);
                await sleep(1000);
                cv = await get_cv_cur();
                console.log(`cv 4,0: ${cv[0]}, ${cv[1]}`);
                let x1 = [cv[0], -cv[1]];

                csa.cur_pos[0] = x_bk - 4;
                csa.cur_pos[1] = y_bk;
                await set_motor_pos(100);
                await sleep(1000);
                cv = await get_cv_cur();
                console.log(`cv -4,0: ${cv[0]}, ${cv[1]}`);
                let x2 = [cv[0], -cv[1]];

                csa.cur_pos[0] = x_bk;
                csa.cur_pos[1] = y_bk - 4;
                await set_motor_pos(100);
                await sleep(1000);
                cv = await get_cv_cur();
                console.log(`cv 0,-4: ${cv[0]}, ${cv[1]}`);
                let y1 = [cv[0], -cv[1]];

                csa.cur_pos[0] = x_bk;
                csa.cur_pos[1] = y_bk + 4;
                await set_motor_pos(100);
                await sleep(1000);
                cv = await get_cv_cur();
                console.log(`cv 0,4: ${cv[0]}, ${cv[1]}`);
                let y2 = [cv[0], -cv[1]];
                
                csa.cur_pos[0] = x_bk;
                csa.cur_pos[1] = y_bk;
                await set_motor_pos(100);
                
                let xv = [x2[0]-x1[0], x2[1]-x1[1]];
                let yv = [y2[0]-y1[0], y2[1]-y1[1]];
                
                let xa = Math.atan2(xv[1], xv[0]) / Math.PI * 180;
                let ya = Math.atan2(yv[1], yv[0]) / Math.PI * 180 - 90;
                angle_avg = (xa + ya) / 2;
                
                console.log(`xv: ${xv}`);
                console.log(`yv: ${yv}`);
                console.log(`xa: ${xa}`);
                console.log(`ya: ${ya}`);
                console.log(`avg: ${angle_avg}`);
                break;
            }
            continue;
        }
    }
    console.log('cali_offset finished');
    csa.stop = true;
    document.getElementById('btn_run').disabled = false;
    document.getElementById('btn_stop').disabled = true;
    csa.comp_height = null;
    document.getElementById('cur_height').innerText = `--`;
    csa.cur_pos[3] = 0;
    document.getElementById('btn_pld_clear').onclick();
    await set_motor_pos();
    set_step(1);
    
    if (angle_avg != null) {
        let is_confirm = confirm(`Update cam1 angle err: ${readable_float(angle_avg)}`);
        if (is_confirm) {
            csa.cam_angle[0] = angle_avg;
            csa_to_page_input();
            await input_change();
            console.log('cam1 angle updated');
        }
    }
};


// The mm per pixel of camera 1 (comp_track.js): with a part centered under the camera, the
// head goes to known offsets around it, out to the edge of the frame, and where the part
// shows up in pixels against the offset in mm is one sample each. The offsets cover the
// radius from 70 to 350 px in every direction, so the fit tells the lens from the center
// to the corner at once, instead of waiting for the run to gather that many snaps.
const SCALE_CALI_OFFSETS = [  // mm, the part appears at -offset / scale pixels
    [2, 0], [4, 0], [6.5, 0], [-2, 0], [-4, 0], [-6.5, 0],
    [0, 2], [0, 4], [0, 6.5], [0, 9], [0, -2], [0, -4], [0, -6.5], [0, -9],
    [4.5, 6], [4.5, -6], [-4.5, 6], [-4.5, -6], [5.5, 8], [5.5, -8], [-5.5, 8], [-5.5, -8]
];

async function scale_measure() {
    const W = 600, H = 800;
    let x0 = csa.cur_pos[0], y0 = csa.cur_pos[1];
    await sleep(600);
    let cv = await get_cv_cur();
    if (!cv)
        return null;
    let p0 = px2mm(cv[0] - W/2, cv[1] - H/2);   // the part is this much off the center to begin with, mm
    let size0 = cv.length > 5 ? [cv[4], cv[5]] : null;
    let a0 = scale_info().a;
    let samples = [];
    for (let [dx, dy] of SCALE_CALI_OFFSETS) {
        if (csa.stop)
            break;
        while (document.getElementById('pause_en').checked)
            await sleep(100);
        csa.cur_pos[0] = x0 + dx;
        csa.cur_pos[1] = y0 + dy;
        await set_motor_pos(100);
        await sleep(800);
        let ret = await get_cv_comps();
        let t = [p0[0] - dx, p0[1] - dy];           // where the part really is now, mm from the center
        let exp = [W/2 + t[0] / a0, H/2 + t[1] / a0]; // and about where that is in the frame
        let best = null, best_d = 60;
        for (let c of (ret && ret.comps) || []) {
            if (size0 && c.length > 5 && (Math.abs(c[4] - size0[0]) > 4 || Math.abs(c[5] - size0[1]) > 4))
                continue;   // another part or a speck, not the one tracked
            let d = Math.hypot(c[0] - exp[0], c[1] - exp[1]);
            if (d < best_d) {
                best = c;
                best_d = d;
            }
        }
        if (!best) {
            console.log(`scale cali: part not found at offset ${dx}, ${dy}`);
            continue;
        }
        let r = Math.hypot(best[0] - W/2, best[1] - H/2);
        let m = Math.hypot(t[0], t[1]);
        console.log(`scale cali: offset ${dx}, ${dy} -> r ${r.toFixed(1)} px, ${m.toFixed(4)} mm, ${(m / r).toFixed(6)} mm/px`);
        samples.push([Math.round(r * 10) / 10, Math.round(m * 10000) / 10000]);
    }
    csa.cur_pos[0] = x0;
    csa.cur_pos[1] = y0;
    await set_motor_pos(100);
    return samples;
}

// ask: tell the user what to prepare and confirm before the samples replace the config's (the
// button); the api asks nothing and applies them at once
async function cali_scale(ask=true) {
    if (!detect_for_parts())
        throw new Error(L("please set camera vision detect method!"));
    if (!document.getElementById('btn_stop').disabled)
        throw new Error(L("please stop smt first!"));
    if (ask && !confirm(`${L('Put a single part at')} ${L('Comp search')} #${get_comp_search()} ` +
                        `${L('and remove the others, so the camera can follow it to the edge of the frame. Start?')}`))
        throw new Error('cancelled');
    if (document.getElementById('camera_dev').value != '1' || !document.getElementById('camera_en').checked) {
        console.log("auto enable camera before run task");
        document.getElementById('camera_dev').value = 1;
        document.getElementById('camera_en').checked = true;
        await document.getElementById('camera_dev').onchange();
    }
    document.getElementById('btn_run').disabled = true;
    document.getElementById('btn_stop').disabled = false;
    csa.stop = false;
    
    let z_middle = Math.min(csa.cur_pos[2] + csa.cam_dz, -2);
    if (csa.cur_pos[2] < z_middle) {
        csa.cur_pos[2] = z_middle;
        await set_motor_pos(100);
    }
    
    // a part under the camera: the one nearest to a comp search position, as the run finds it
    let search = get_comp_search();
    let samples = null;
    for (let i = 0; i < csa.comp_search.length && !csa.stop; i++) {
        document.getElementById('camera_light1').checked = false;
        await document.getElementById('camera_light1').onchange();
        await z_keep_high(70);
        csa.cur_pos[0] = csa.comp_search[search][0];
        csa.cur_pos[1] = csa.comp_search[search][1];
        csa.cur_pos[3] = 0;
        if (csa.cur_pos[2] != csa.comp_top_z) {
            await set_motor_pos(70);
            csa.cur_pos[2] = csa.comp_top_z;
            await set_motor_pos(100);
        } else {
            await set_motor_pos(100);
        }
        if (await cam_comp_snap() < 0) {
            if (++search >= csa.comp_search.length)
                search = 0;
            set_comp_search(search);
            continue;
        }
        samples = await scale_measure();
        break;
    }
    console.log('cali_scale finished', samples);
    csa.stop = true;
    document.getElementById('btn_run').disabled = false;
    document.getElementById('btn_stop').disabled = true;
    
    if (!samples || samples.length < 8) {
        let msg = L('Camera scale calibration failed: no part found, or it was lost on the way') +
                  (samples ? ` (${samples.length} ${L('samples')})` : '');
        if (ask)
            alert(msg);
        throw new Error(msg);
    }
    let info = scale_info_of(samples);
    let edge = (info.edge_pct >= 0 ? '+' : '') + info.edge_pct.toFixed(2);
    let msg = `${L('Update cam scale')}: ${info.a.toFixed(6)} mm/px, ${L('edge')} ${edge}%, ${info.samples} ${L('samples')}, ` +
              `${L('max error')} ${info.max_err} mm`;
    if (ask && !confirm(msg))
        return { applied: false, ...info, list: samples };
    scale_set(samples);
    csa_to_page_input();
    await input_change();   // the Save button turns yellow, as for any config change
    console.log('cam scale updated');
    return { applied: true, ...info, list: samples };
}

document.getElementById('btn_cali_scale').onclick = async function() {
    try {
        await cali_scale(true);
    } catch (err) {
        console.log('cali_scale:', err.message);
        if (err.message != 'cancelled' && !document.getElementById('btn_stop').disabled)  // refused before it started
            alert(err.message);
    }
};


document.getElementById('btn_cali_cam2').onclick = async function() {
    if (!detect_for_parts()) {
        alert(L("please set camera vision detect method!"));
        return;
    }
    if (!document.getElementById('btn_stop').disabled) {
        alert(L("please stop smt first!"));
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
    csa.comp_height = null;
    document.getElementById('cur_height').innerText = `--`;
    
    let z_middle = Math.min(csa.cur_pos[2] + csa.cam_dz, -2);
    if (csa.cur_pos[2] < z_middle) {
        csa.cur_pos[2] = z_middle;
        await set_motor_pos(100);
    }
    
    set_step(1);
    let angle_avg = null;
    
    while (true) {
        let step = get_step_safe();
        let search = get_comp_search();
        console.log(`step: ${step}, search: ${search}`);
        
        if (csa.stop)
            break;
        if (document.getElementById('pause_en').checked) {
            console.log(`enter wait`);
            while (document.getElementById('pause_en').checked)
                await sleep(100);
            console.log(`exit wait`);
            continue;
        }
        
        if (step == 0 || step == 5) {
            set_step(1);
            continue;
        }
        
        if (step == 1) { // goto_comp
            console.log('fsm goto_comp');
            document.getElementById('camera_light1').checked = false;
            await document.getElementById('camera_light1').onchange();
            await z_keep_high(70);
            csa.cur_pos[0] = csa.comp_search[search][0];
            csa.cur_pos[1] = csa.comp_search[search][1];
            csa.cur_pos[3] = 0;
            if (csa.cur_pos[2] != csa.comp_top_z) {
                await set_motor_pos(70);
                csa.cur_pos[2] = csa.comp_top_z;
                await set_motor_pos(100);
            } else {
                await set_motor_pos(100);
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
                if (++search >= csa.comp_search.length)
                    search = 0;
                set_comp_search(search);
                set_step(1);
            } else {
                set_step(3);
                console.log(`csa.cur_pos: ${csa.cur_pos}`);
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
            
            set_step(4); // 2nd check
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
            
            let ret = await cam_comp_snap();
            csa.cur_pos[3] -= csa.cv_cur_r;
            await set_motor_pos(100);
            
            if (!document.getElementById('putdown_en').checked) {
                document.getElementById('pause_en').checked = true;
            } else {
                await sleep(800);
            }
            while (document.getElementById('pause_en').checked)
                await sleep(100);
            if (csa.stop)
                break;

            let x_bk = csa.cur_pos[0];
            let y_bk = csa.cur_pos[1];
            console.log(`csa.cur_pos: ${csa.cur_pos}`);
            
            let cv = await get_cv_cur();
            console.log(`cv 0,0: ${cv[0]}, ${cv[1]}`);

            csa.cur_pos[0] = x_bk - 4;
            csa.cur_pos[1] = y_bk;
            await set_motor_pos(100);
            await sleep(1000);
            cv = await get_cv_cur();
            console.log(`cv -4,0: ${cv[0]}, ${cv[1]}`);
            let x1 = [cv[0], -cv[1]];

            csa.cur_pos[0] = x_bk + 4;
            csa.cur_pos[1] = y_bk;
            await set_motor_pos(100);
            await sleep(1000);
            cv = await get_cv_cur();
            console.log(`cv 4,0: ${cv[0]}, ${cv[1]}`);
            let x2 = [cv[0], -cv[1]];

            csa.cur_pos[0] = x_bk;
            csa.cur_pos[1] = y_bk + 4;
            await set_motor_pos(100);
            await sleep(1000);
            cv = await get_cv_cur();
            console.log(`cv 0,4: ${cv[0]}, ${cv[1]}`);
            let y1 = [cv[0], -cv[1]];

            csa.cur_pos[0] = x_bk;
            csa.cur_pos[1] = y_bk - 4;
            await set_motor_pos(100);
            await sleep(1000);
            cv = await get_cv_cur();
            console.log(`cv 0,-4: ${cv[0]}, ${cv[1]}`);
            let y2 = [cv[0], -cv[1]];
            
            csa.cur_pos[0] = x_bk;
            csa.cur_pos[1] = y_bk;
            await set_motor_pos(100);
            await sleep(1000);
            
            let xv = [x2[0]-x1[0], x2[1]-x1[1]];
            let yv = [y2[0]-y1[0], y2[1]-y1[1]];
            
            let xa = Math.atan2(xv[1], xv[0]) / Math.PI * 180;
            let ya = Math.atan2(yv[1], yv[0]) / Math.PI * 180 - 90;
            angle_avg = (xa + ya) / 2;
            
            console.log(`xv: ${xv}`);
            console.log(`yv: ${yv}`);
            console.log(`xa: ${xa}`);
            console.log(`ya: ${ya}`);
            console.log(`avg: ${angle_avg}`);

            document.getElementById('camera_dev').value = 1;
            document.getElementById('camera_detect').value = detect_bk;
            document.getElementById('camera_light2').checked = false;
            await document.getElementById('camera_dev').onchange();
            
            csa.cur_pos[0] = csa.comp_search[search][0] - csa.grab_ofs[0];
            csa.cur_pos[1] = csa.comp_search[search][1] - csa.grab_ofs[1];
            csa.cur_pos[3] = 0;
            await set_motor_pos(100);
            
            set_step(6);
            continue;
        }

        if (step == 6) { // putdown
            console.log('fsm putdown');
            if (csa.comp_height != null)
                csa.cur_pos[2] = csa.comp_base_z + csa.comp_height + 1; // 1mm space
            await set_motor_pos(100);

            await sleep(800);
            await enable_force();
            csa.cur_pos[2] = csa.pcb_base_z - 1;
            await set_motor_pos(100, csa.motor_speed >= 0.6 ? 12000 : 6000);
            await set_pump(csa.pump_hw_ver == 'v1' ? 1 : 0);
            await sleep(500);
            await z_keep_high(70);
            set_step(1);
            await set_pump(0);
            
            csa.cur_pos[0] = csa.comp_search[search][0];
            csa.cur_pos[1] = csa.comp_search[search][1];
            csa.cur_pos[3] = 0;
            await set_motor_pos(100);
            break;
        }
        
    }
    console.log('cali_offset finished');
    csa.stop = true;
    document.getElementById('btn_run').disabled = false;
    document.getElementById('btn_stop').disabled = true;
    csa.comp_height = null;
    document.getElementById('cur_height').innerText = `--`;
    csa.cur_pos[3] = 0;
    document.getElementById('btn_pld_clear').onclick();
    await set_motor_pos();
    set_step(1);
    
    if (angle_avg != null) {
        let is_confirm = confirm(`Update cam2 angle err: ${readable_float(angle_avg)}`);
        if (is_confirm) {
            csa.cam_angle[1] = angle_avg;
            csa_to_page_input();
            await input_change();
            console.log('cam2 angle updated');
        }
    }
};


// ------------------------------------------------------------ fiducials

const FID_BACK = 0.5;       // mm, the last move always comes from -x, -y: the same side of the lead screw
const FID_TOL = 0.03;       // mm, one more approach when ending farther off the center than this
const FID_NEAR = 8;         // mm, how far off the center a fiducial is looked for by hand
const FID_NEAR_ALL = 3;     // mm, with Lock all, the old position is close and a pad can pass for a circle

// median position of the fiducial nearest to the center over n new frames, mm from the center; null when it
// is not seen. The first new frame may be from the move, one farther than max_mm is not the one looked for
async function fid_offset(n, max_mm) {
    let seq = -1, first = true, l = [];
    for (let t = 0; l.length < n; t++) {
        if (t > n * 40)
            return null;
        let r = await get_cv_comps();
        if (!r || r.seq == seq || !r.detect.startsWith('fid')) {
            await sleep(40);
            continue;
        }
        seq = r.seq;
        if (first) {
            first = false;
        } else if (r.cur) {
            let mm = px2mm(r.cur[0] - 300, r.cur[1] - 400);
            if (Math.hypot(mm[0], mm[1]) <= max_mm)
                l.push(mm);
        }
    }
    let median = i => {
        let v = l.map(p => p[i]).sort((a, b) => a - b);
        return (v[(n - 1) >> 1] + v[n >> 1]) / 2;
    };
    return [median(0), median(1)];
}

// the position of the fiducial under the camera: where the axes stopped, plus what is left in the frame
async function fid_approach(max_mm) {
    await sleep(900);
    let o = await fid_offset(2, max_mm);
    if (!o)
        return null;
    for (let i = 0; i < 3; i++) {
        let tgt = [csa.cur_pos[0] + o[0], csa.cur_pos[1] + o[1]];
        csa.cur_pos[0] = tgt[0] - FID_BACK;
        csa.cur_pos[1] = tgt[1] - FID_BACK;
        await set_motor_pos(100);
        csa.cur_pos[0] = tgt[0];
        csa.cur_pos[1] = tgt[1];
        await set_motor_pos(100, 60000);
        await sleep(900);
        o = await fid_offset(5, 1);
        if (!o)
            return null;
        if (Math.hypot(o[0], o[1]) <= FID_TOL)
            break;
    }
    return [csa.cur_pos[0] + o[0], csa.cur_pos[1] + o[1]];
}

let fid_answer_set = null;
window.fid_answer = a => { if (fid_answer_set) fid_answer_set(a); };

// waits for the user, who can jog the head meanwhile; 'stop' when the Stop button ends a Lock all
// found: false: nothing to accept, always: offer Always yes, ok: false: found, but looks wrong
async function fid_ask(text, found, watch_stop, always, ok=true) {
    let btn = (a, t) => `<button class="button is-small" onclick="fid_answer('${a}')">${L(t)}</button>`;
    show_banner('fid_banner', `${text}\n` + (found ? btn('ok', 'Accept') + ' ' : '') + (found && always ? btn('always', 'Always yes') + ' ' : '') +
                btn('manual', 'Use the current position') + ' ' + btn('retry', 'Detect again') + ' ' + btn('skip', 'Skip'), 'is-warning', found && ok ? '#ABEBC680' : undefined);
    let answer = null;
    fid_answer_set = a => { answer = a; };
    while (!answer && !(watch_stop && csa.stop))
        await sleep(50);
    fid_answer_set = null;
    show_banner('fid_banner', '');
    return answer || 'stop';
}

// [x, y] of one point as found, or as the user placed it; null: not found, or skipped
// auto: for Lock all, {on: Always yes was pressed, dev: p => mm off from the other points}
async function fid_confirm(title, max_mm, ask, watch_stop, auto=null) {
    while (true) {
        let p = await fid_approach(max_mm);
        if (!ask)
            return p;
        let dev = p && auto ? auto.dev(p) : 0, limit = csa.fiducial_pos_err;
        if (p && auto && auto.on && dev <= limit)
            return p;
        let text = p ? L('Found: check that the crosshair is on the fiducial, or jog it there and use the current position')
                     : L('Not found: jog the crosshair onto the fiducial and use the current position');
        if (dev > limit)
            text = `${L('Shifted more than the other points by')} ${dev.toFixed(2)} mm. ${text}`;
        let a = await fid_ask(title ? `${title}: ${text}` : text, p != null, watch_stop, auto && !auto.on, !(dev > limit));
        if (a == 'always') {
            auto.on = true;
            return p;
        }
        if (a == 'ok')
            return p;
        if (a == 'manual')
            return [csa.cur_pos[0], csa.cur_pos[1]];
        if (a != 'retry')
            return null;
    }
}

// the Fiducial entry of the detect box is selected meanwhile, so what the camera does shows on the page
async function fid_session(fn) {
    if (!fid_mode())
        throw new Error(L('Fiducial size: a diameter, or W x H of a rectangular pad, in mm'));
    let dev = document.getElementById('camera_dev'), en = document.getElementById('camera_en');
    if (dev.value != '1' || !en.checked) {
        dev.value = 1;
        en.checked = true;
        await dev.onchange();
    }
    let light = document.getElementById('camera_light1'), light_bk = light.checked;
    let detect = document.getElementById('camera_detect'), detect_bk = detect.value;
    light.checked = true;
    detect.value = 'fiducial';
    await light.onchange();         // sends both
    try {
        return await fn();
    } finally {
        light.checked = light_bk;
        detect.value = detect_bk;
        await light.onchange();
    }
}

// x, y of the fiducial near the center of the frame, the head stays there; null: skipped by the user
async function fid_lock(ask=false, title='') {
    let p = await fid_session(async () => {
        if (csa.cur_pos[2] != csa.pcb_top_z) {
            csa.cur_pos[2] = csa.pcb_top_z;
            await set_motor_pos(100);
        }
        return await fid_confirm(title, FID_NEAR, ask, false);
    });
    if (!p && !ask)
        throw new Error(L('No fiducial found near the center: check that it is in view, and its size'));
    return p;
}

// every point of every board; one not found or skipped keeps its old value and the others go on
async function fid_lock_all(ask=false) {
    if (!csa.fiducial_cam.length)
        throw new Error(L('No fiducial to lock'));
    let ret = { total: 0, locked: 0, failed: [], max_move: 0, moves: [], stopped: false };
    let shifts = [], auto = { on: false, dev: null };   // shifts: of the points accepted so far
    let median = l => { l = [...l].sort((a, b) => a - b); return l[l.length >> 1]; };
    for (let row of csa.fiducial_cam)
        ret.total += row.length;
    document.getElementById('btn_run').disabled = true;
    document.getElementById('btn_stop').disabled = false;
    csa.stop = false;
    try {
        await fid_session(async () => {
            for (let b = 0; b < csa.fiducial_cam.length; b++) {
                for (let j = 0; j < csa.fiducial_cam[b].length; j++) {
                    while (document.getElementById('pause_en').checked)
                        await sleep(100);
                    if (csa.stop) {
                        ret.stopped = true;
                        return;
                    }
                    let old = csa.fiducial_cam[b][j];
                    let low = csa.cur_pos[2] != csa.pcb_top_z;
                    if (low) {
                        let z_middle = Math.min(Math.max(csa.pcb_top_z, csa.cur_pos[2]) + csa.cam_dz, -2);
                        if (csa.cur_pos[2] < z_middle) {
                            csa.cur_pos[2] = z_middle;
                            await set_motor_pos(100);
                        }
                    }
                    csa.cur_pos[0] = old[0];
                    csa.cur_pos[1] = old[1];
                    csa.cur_pos[3] = 0;
                    await set_motor_pos(100);
                    if (low) {
                        csa.cur_pos[2] = csa.pcb_top_z;
                        await set_motor_pos(100);
                    }
                    auto.dev = p => {
                        let l = shifts.filter(s => s.b == b);   // a board placed apart moves on its own
                        l = l.length ? l : shifts;
                        return l.length ? Math.hypot(p[0] - old[0] - median(l.map(s => s.x)), p[1] - old[1] - median(l.map(s => s.y))) : 0;
                    };
                    let p = await fid_confirm(`#${b}.${j + 1}`, FID_NEAR_ALL, ask, true, auto);
                    if (csa.stop) {
                        ret.stopped = true;
                        return;
                    }
                    if (!p) {
                        ret.failed.push([b, j]);
                        continue;
                    }
                    shifts.push({ b, x: p[0] - old[0], y: p[1] - old[1] });
                    let m = Math.hypot(p[0] - old[0], p[1] - old[1]);
                    ret.moves.push([b, j, Math.round(m * 1000) / 1000]);
                    ret.max_move = Math.max(ret.max_move, m);
                    ret.locked++;
                    csa.fiducial_cam[b][j] = [Math.round(p[0] * 1e6) / 1e6, Math.round(p[1] * 1e6) / 1e6];
                    csa_to_page_input();
                }
            }
        });
    } finally {
        csa.stop = true;
        document.getElementById('btn_run').disabled = false;
        document.getElementById('btn_stop').disabled = true;
    }
    return ret;
}

// from the fiducials of the selected board, needs nothing but what is in the boxes
async function cali_skew(ask=true) {
    let f = fid_fit(csa.fiducial_pcb, csa.fiducial_cam[get_board_safe()] || []);
    if (!f || f.collinear) {
        let msg = L('XY skew needs 3 or 4 fiducials not on a line, in Fiducial pcb and in the selected board');
        if (ask)
            alert(msg);
        throw new Error(msg);
    }
    let info = { skew: f.skew, n: f.n, max_err: f.max_err, scale_diff: f.scale_diff };
    let msg = `${L('Update XY skew')}: ${f.skew.toFixed(4)}°, ${f.n} ${L('points')}, X/Y ${f.scale_diff.toFixed(3)}%, ` +
              (f.n > 3 ? `${L('max error')} ${f.max_err.toFixed(3)} mm` : L('3 points have no check, 4 are better'));
    if (ask && !confirm(msg))
        return { applied: false, ...info };
    csa.xy_skew = Math.round(f.skew * 1e6) / 1e6;
    csa_to_page_input();
    await input_change();
    return { applied: true, ...info };
}

document.getElementById('btn_cali_skew').onclick = async function() {
    try {
        await cali_skew(true);
    } catch (err) {
        console.log('cali_skew:', err.message);
    }
};


export { cali_scale, fid_lock, fid_lock_all, cali_skew };
