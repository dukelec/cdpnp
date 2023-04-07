/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { readable_float, sleep } from './utils/helper.js';
import { set_camera_cfg, set_motor_pos, set_pump, cam_comp_snap, pcb2xyz } from './dev_cmd.js';
import { get_comp_search } from './pos_list.js';
import { csa } from './index.js';


function pld_get_grid(idx)
{
    if (idx == 0)
        return [0, 0];
    idx -= 1;
    let layer = 1;
    while (true) {
        let width = (layer + 1) * 2 - 1;
        let amount = (width - 1) * 4;
        if (idx < amount) {
            let wire = Math.floor(idx / (width - 1));
            let w_idx = idx - wire * (width - 1);
            switch (wire) {
            case 0: return [-layer + w_idx, -layer];
            case 1: return [layer, -layer + w_idx];
            case 2: return [layer - w_idx, layer];
            default: return [-layer, layer - w_idx];
            }
        }
        layer += 1;
        idx -= amount;
    }
}

function pld_csa_to_page()
{
    document.getElementById(`pld_search`).value = `${readable_float(csa.pld_search[0])}, ${readable_float(csa.pld_search[1])}`;
    document.getElementById('pld_base_z').value = `${readable_float(csa.pld_base_z)}`;
    csa.pld_top_z = csa.pld_base_z + csa.cam_dz;
    
    document.getElementById('pld_comp_offset').value = csa.pld_comp_offset;
    document.getElementById('pld_comp_space').value = csa.pld_comp_space;
    document.getElementById('pld_start_at').value = csa.pld_start_at;
    
    document.getElementById(`pld_tgt_grid`).value = `${csa.pld_tgt_grid[0]}, ${csa.pld_tgt_grid[1]}`;
    document.getElementById('pld_rotate').value = csa.pld_rotate;
    
    document.getElementById('preload_en').checked = csa.pld_enable;
    document.getElementById('preload_en').onclick();
}

function pld_csa_from_page()
{
    let xy_str = document.getElementById(`pld_search`).value;
    csa.pld_search = [Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])];
    csa.pld_base_z = Number(document.getElementById('pld_base_z').value);
    csa.pld_top_z = csa.pld_base_z + csa.cam_dz;
    
    csa.pld_comp_offset = Number(document.getElementById('pld_comp_offset').value);
    csa.pld_comp_space = Number(document.getElementById('pld_comp_space').value);
    csa.pld_start_at = Number(document.getElementById('pld_start_at').value);
    
    xy_str = document.getElementById(`pld_tgt_grid`).value;
    csa.pld_tgt_grid = [Number(xy_str.split(',')[0]), Number(xy_str.split(',')[1])];
    csa.pld_rotate = Number(document.getElementById('pld_rotate').value);
    
    csa.pld_enable = document.getElementById('preload_en').checked;
}


document.getElementById('preload_en').onclick = async function() {
    
    let content = document.getElementById('preload_en').parentElement.nextElementSibling
    
    content.style.display = document.getElementById('preload_en').checked ? "block" : "none";
    document.getElementById('pld_count').value = 0;
};


document.getElementById('btn_pld_run').onclick = async function() {
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
    document.getElementById('btn_pld_run').disabled = true;
    document.getElementById('btn_pld_stop').disabled = false;
    csa.pld_stop = false;
    
    let z_middle = Math.min(csa.cur_pos[2] + csa.cam_dz, -2);
    if (csa.cur_pos[2] < z_middle) {
        csa.cur_pos[2] = z_middle;
        await set_motor_pos(true);
    }
    
    let pcb = [ [0, 0], [0, 4] ];
    let cam = [ null, null ];
    
    for (let i = 0; !csa.pld_stop && i < 2; i++) {
        console.log(`detect circle ${i}`);
        document.getElementById('camera_light1').checked = false;
        await set_camera_cfg(i ? 'pld_last' : 'pld_first');
        csa.cur_pos[0] = csa.pld_search[0];
        csa.cur_pos[1] = csa.pld_search[1];
        csa.cur_pos[3] = 0;
        await set_motor_pos(true);
        if (csa.cur_pos[2] != csa.pld_top_z) {
            csa.cur_pos[2] = csa.pld_top_z;
            await set_motor_pos(true);
        }
        await sleep(800);
        
        console.log('fsm snap');
        await cam_comp_snap(1);
        await set_camera_cfg();
        await sleep(200);
        let ret = await cam_comp_snap();
        if (ret < 0) {
            console.log("no comp found!");
            break;
        } else {
            cam[i] = [csa.cur_pos[0], csa.cur_pos[1]];
        }
        continue;
    }
    
    if (cam[0] != null && cam[1] != null) {
        let cam_delta = [cam[1][0]-cam[0][0], cam[1][1]-cam[0][1]];
        let count = Math.round(cam_delta[1]/4) + 1;
        console.log(`count: ${count} (${cam_delta[1]/4} + 1)`);
        pcb[1][1] = (count - 1) * 4;
        
        /*
        for (let i = 0; i < count * 2; i++) {
            let comp_xyz = await pcb2xyz(pcb, cam, 3.5, 2 * i);
            csa.cur_pos[0] = comp_xyz[0];
            csa.cur_pos[1] = comp_xyz[1];
            await set_motor_pos(true);
            await sleep(200); // 800
        } */
        
        let amount = Math.round(count / csa.pld_comp_space);
        let amount_input = Number(document.getElementById('pld_amount').value);
        if (amount_input > 0)
            amount = amount_input;
        
        for (let i = 0; !csa.pld_stop && i < amount; i++) {
            let comp_xyz = await pcb2xyz(pcb, cam, csa.pld_comp_offset, 4 * (csa.pld_comp_space * i + csa.pld_start_at));
            let top_z = csa.pld_base_z + Math.abs(csa.pld_base_z - csa.comp_base_z) * 2 + 1;
            csa.cur_pos[0] = comp_xyz[0] - csa.grab_ofs0[0];
            csa.cur_pos[1] = comp_xyz[1] - csa.grab_ofs0[1];
            csa.cur_pos[2] = top_z;
            csa.cur_pos[3] = 0;
            await set_motor_pos(true);
            
            csa.cur_pos[2] = csa.pld_base_z - 0.5;
            await set_motor_pos(true);
            await set_pump(1);
            await sleep(600);
            csa.cur_pos[2] = top_z;
            await set_motor_pos(true);
            
            let tgt_count = Number(document.getElementById('pld_count').value);
            let tgt_grid = pld_get_grid(tgt_count);
            let tgt = [tgt_grid[0] * csa.pld_tgt_grid[0], tgt_grid[1] * csa.pld_tgt_grid[1]];
            let search = get_comp_search();
            csa.cur_pos[0] = csa.comp_search[search][0] - csa.grab_ofs0[0] + tgt[0];
            csa.cur_pos[1] = csa.comp_search[search][1] - csa.grab_ofs0[1] + tgt[1];
            csa.cur_pos[3] = csa.pld_rotate;
            await set_motor_pos(true);
            
            csa.cur_pos[2] = csa.comp_base_z + Math.abs(csa.pld_base_z - csa.comp_base_z) - 0.5;
            await set_motor_pos(true);
            await set_pump(0);
            
            csa.cur_pos[2] = top_z;
            await set_motor_pos(true);
            
            document.getElementById('pld_count').value = tgt_count + 1;
            if (csa.pld_stop)
                break;
        }
    }
    
    csa.cur_pos[0] = csa.pld_search[0];
    csa.cur_pos[1] = csa.pld_search[1];
    csa.cur_pos[2] = csa.pld_top_z;
    csa.cur_pos[3] = 0;
    await set_motor_pos(true);
    
    console.log('preload finished');
    csa.pld_stop = true;
    document.getElementById('btn_pld_run').disabled = false;
    document.getElementById('btn_pld_stop').disabled = true;
};

document.getElementById('btn_pld_stop').onclick = function() {
    csa.pld_stop = true;
    document.getElementById('btn_pld_stop').disabled = true;
};

document.getElementById('btn_pld_clear').onclick = function() {
    document.getElementById('pld_count').value = 0;
};


export {
    pld_csa_to_page, pld_csa_from_page
};
