/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { readable_float, sleep } from './utils/helper.js';
import { get_camera_cfg, get_motor_pos, set_motor_pos, set_pump,
         z_keep_high, enable_force, cam_comp_snap, set_camera_cfg, set_vision_cfg } from './dev_cmd.js';
import { set_step, get_step_safe, set_comp_search, get_comp_search } from './pos_list.js';
import { csa_to_page_input, input_change } from './input_ctrl.js';
import { csa } from './index.js';


document.getElementById('btn_cali_offset').onclick = async function() {
    if (!document.getElementById('camera_detect').value) {
        alert("please set camera vision detect method!");
        return;
    }
    if (!csa.stop) {
        alert("please stop smt first!");
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
            await set_pump(2);
            if (csa.comp_height == null) {
                await get_motor_pos();
                csa.comp_height = Math.max(parseFloat((csa.cur_pos[2] - csa.comp_base_z).toFixed(3)), 0);
                document.getElementById('cur_height').innerText = `${csa.comp_height}`;
            }
            await sleep(600);
            await z_keep_high(70, 260000);
            
            csa.cur_pos[3] = 180;
            await set_motor_pos(0);
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
            await set_pump(1);
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
        alert("please set camera vision detect method for nozzle calibration!");
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

export { };
