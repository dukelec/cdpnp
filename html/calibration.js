/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { readable_float, sleep } from './utils/helper.js';
import { get_camera_cfg, get_motor_pos, set_motor_pos, set_pump,
         z_keep_high, enable_force, cam_comp_snap, set_camera_cfg } from './dev_cmd.js';
import { set_step, get_step_safe, set_comp_search, get_comp_search } from './pos_list.js';
import { csa_to_page_input, input_change } from './input_ctrl.js';
import { csa } from './index.js';


document.getElementById('btn_cali_offset').onclick = async function() {
    if (!document.getElementById('camera_detect').value) {
        alert("please set camera vision detect method!");
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
        await set_motor_pos(true);
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
            parents_pre = null;
            continue;
        }
        
        if (step == 0 || step == 4) {
            set_step(1);
            continue;
        }
        
        if (step == 1) { // goto_comp
            console.log('fsm goto_comp');
            document.getElementById('camera_light1').checked = false;
            await document.getElementById('camera_light1').onchange();
            await z_keep_high();
            if (cali_dat.length) {
                csa.cur_pos[0] = cali_dat[cali_dat.length-1][0];
                csa.cur_pos[1] = cali_dat[cali_dat.length-1][1];
            } else {
                csa.cur_pos[0] = csa.comp_search[search][0];
                csa.cur_pos[1] = csa.comp_search[search][1];
            }
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
            csa.cur_pos[0] -= csa.grab_ofs0[0];
            csa.cur_pos[1] -= csa.grab_ofs0[1];
            if (csa.comp_height != null)
                csa.cur_pos[2] = csa.comp_base_z + csa.comp_height + 1; // 1mm space
            await set_motor_pos(true);
            await sleep(800);
            await enable_force();
            csa.cur_pos[2] = csa.comp_base_z - 1;
            await set_motor_pos(true, csa.motor_speed >= 0.6 ? 12000 : 6000);
            await set_pump(1);
            if (csa.comp_height == null) {
                await get_motor_pos();
                csa.comp_height = Math.max(parseFloat((csa.cur_pos[2] - csa.comp_base_z).toFixed(3)), 0);
                document.getElementById('cur_height').innerText = `${csa.comp_height}`;
            }
            await sleep(600);
            await z_keep_high();
            csa.grap_err = null;
            
            csa.cur_pos[3] = 180;
            await set_motor_pos(true);
            set_step(5);
            continue;
        }
        
        if (step == 5) { // putdown
            console.log('fsm putdown');
            if (csa.comp_height != null) {
                csa.cur_pos[2] = csa.comp_base_z + csa.comp_height + 1; // 1mm space
                await set_motor_pos(true);
            }

            await sleep(800);
            await enable_force();
            csa.cur_pos[2] = csa.pcb_base_z - 1;
            await set_motor_pos(true, csa.motor_speed >= 0.6 ? 12000 : 6000);
            await set_pump(0);
            await z_keep_high();
            set_step(1);
        }
        
    }
    console.log('cali_offset finished');
    csa.stop = true;
    document.getElementById('btn_run').disabled = false;
    document.getElementById('btn_stop').disabled = true;
    csa.comp_height = null;
    csa.grap_err = null;
    document.getElementById('cur_height').innerText = `--`;
    csa.cur_pos[3] = 0;
    document.getElementById('btn_pld_clear').onclick();
    await set_motor_pos();
    set_step(1);
    
    let delta_x = (cali_dat[1][0] - cali_dat[0][0]) / 2;
    let delta_y = (cali_dat[1][1] - cali_dat[0][1]) / 2;
    
    let is_confirm = confirm(`Add offset: ${readable_float(delta_x)}, ${readable_float(delta_y)}`);
    if (is_confirm) {
        csa.grab_ofs0[0] += delta_x;
        csa.grab_ofs0[1] += delta_y;
        csa_to_page_input();
        await input_change();
        console.log('offset added');
    }
};


export { };
