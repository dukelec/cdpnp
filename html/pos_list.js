/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { csv_parser, read_file, readable_float } from './utils/helper.js';
import { set_motor_pos, pcb2xyz } from './dev_cmd.js';
import { csa, db } from './index.js';
import { disable_goto_btn } from './input_ctrl.js';


function get_comp_values(comp)
{
    let pos_list = document.getElementById('pos_list');
    let comp_list = pos_list.getElementsByClassName('list_comp');
    for (let elm of comp_list) {
        let subs = elm.querySelectorAll('td');
        if (subs[0].innerText == comp)
            return [Number(subs[1].innerText), Number(subs[2].innerText), Number(subs[3].innerText)];
    }
    return null;
}

function search_comp_parents(comp, set_color=false, color='')
{
    let parents = [null, null];
    let pos_list = document.getElementById('pos_list');
    let comp_elm = null;
    
    let comp_list = pos_list.getElementsByClassName('list_comp');
    for (let elm of comp_list) {
        let sub0 = elm.querySelector('td');
        if (sub0.innerText == comp) {
            comp_elm = elm;
            if (set_color)
                elm.style.backgroundColor = color;
            break;
        }
    }
    
    let footprint_list = pos_list.getElementsByClassName('list_footprint');
    for (let elm of footprint_list) {
        if (elm.contains(comp_elm)) {
            let subs = elm.querySelectorAll('td');
            parents[0] = subs[0].innerText;
            if (set_color) {
                subs[0].style.backgroundColor = color;
                subs[1].style.backgroundColor = color;
            }
            break;
        }
    }
    
    let value_list = pos_list.getElementsByClassName('list_value');
    for (let elm of value_list) {
        if (elm.contains(comp_elm)) {
            let sub0 = elm.querySelector('td');
            parents[1] = sub0.innerText;
            if (set_color)
                sub0.style.backgroundColor = color;
            break;
        }
    }
    
    return parents;
}

function search_next_comp(comp)
{
    let pos_list = document.getElementById('pos_list');
    let comp_elm = null;
    let comp_next = null;
    
    let comp_list = pos_list.getElementsByClassName('list_comp');
    for (let elm of comp_list) {
        let sub0 = elm.querySelector('td');
        if (comp_elm != null && elm.querySelector('td').innerText != comp) {
            comp_next = elm.querySelector('td').innerText;
            break;
        }
        if (sub0.innerText == comp)
            comp_elm = elm;
    }
    
    return comp_next;
}

function search_current_comp()
{
    let pos_list = document.getElementById('pos_list');    
    let comp_list = pos_list.getElementsByClassName('list_comp');
    for (let elm of comp_list) {
        if (elm.style.backgroundColor) {
            let sub0 = elm.querySelector('td');
            return sub0.innerText;
        }
    }
    return null;
}

function search_first_comp()
{
    let pos_list = document.getElementById('pos_list');    
    let comp_list = pos_list.getElementsByClassName('list_comp');
    if (comp_list.length)
        return comp_list[0].querySelector('td').innerText;
    return null;
}

function get_comp_progress(comp)
{
    let progress = [0, 0];
    let pos = pos_from_page();    
    let parents = search_comp_parents(comp);
    let comps = pos[parents[0]][parents[1]];
    for (let i = 0; i < comps.length; i++) {
        if (comp == comps[i][0]) {
            progress[0] = i + 1;
            break;
        }
    }
    progress[1] = comps.length;
    return progress;
}


function select_comp(comp) {
    let pre_comp = search_current_comp();
    let pre_parents = [null, null];
    let cur_parents = [null, null];
    if (pre_comp)
        pre_parents = search_comp_parents(pre_comp, true, "");
    if (comp) {
        cur_parents = search_comp_parents(comp, true, "#D5F5E3");
        document.getElementById('cur_comp').innerText = `${cur_parents[0]} ${cur_parents[1]} ${comp}`;
        let progress = get_comp_progress(comp);
        document.getElementById('cur_progress').innerText = `${progress[0]} / ${progress[1]}`
        if (csa.fiducial_cam.length > 1) {
            let total_num = progress[1] * csa.fiducial_cam.length;
            let total_cnt = (progress[0] - 1) * csa.fiducial_cam.length + get_board_safe() + 1;
            document.getElementById('cur_progress').innerText += ` (total ${total_cnt} / ${total_num})`
        }
        
        let next = comp;
        let next_parents;
        while (true) {
            next = search_next_comp(next);
            if (next == null)
                break;
            next_parents = search_comp_parents(next);
            if (next_parents[0] != cur_parents[0] || next_parents[1] != cur_parents[1])
                break;
        }
        if (next) {
            let progress = get_comp_progress(next);
            let parents = search_comp_parents(next);
            document.getElementById('next_comp').innerText = `${next_parents[0]} ${next_parents[1]}`;
            document.getElementById('next_total').innerText = `${progress[1]}`;
            if (csa.fiducial_cam.length > 1)
                document.getElementById('next_total').innerText += ` (total ${progress[1] * csa.fiducial_cam.length})`;
        } else {
            document.getElementById('next_comp').innerText = "-- --";
            document.getElementById('next_total').innerText = "--";
        }
    } else {
        document.getElementById('cur_comp').innerText = "-- -- --";
        document.getElementById('cur_progress').innerText = "-- / --";
    }
    if (cur_parents[0] != pre_parents[0]) {
        csa.comp_height = null;
        document.getElementById('cur_height').innerText = "--";
    }
}

async function move_to_comp(comp) {
    if (document.getElementsByClassName('goto_btn')[0].disabled)
        return;
    select_comp(comp);
    if (comp && (document.getElementById('pause_en').checked || document.getElementById('btn_stop').disabled)) {
        disable_goto_btn(true);
        set_step(1); // step: goto_comp
        let comp_val = get_comp_values(comp);
        let board = get_board_safe();
        let comp_xyz = await pcb2xyz(csa.fiducial_pcb, csa.fiducial_cam[board], comp_val[0], comp_val[1]);
        if (csa.cur_pos[2] != csa.pcb_top_z) {
            let z = csa.pcb_top_z;
            let z_middle = Math.min(Math.max(z, csa.cur_pos[2]) + csa.cam_dz, -2);
            if (csa.cur_pos[2] < z_middle) {
                csa.cur_pos[2] = z_middle;
                await set_motor_pos(true);
            }
            csa.cur_pos[0] = comp_xyz[0];
            csa.cur_pos[1] = comp_xyz[1];
            csa.cur_pos[3] = 0;
            await set_motor_pos(true);
            csa.cur_pos[2] = z;
            await set_motor_pos(true);
        } else {
            csa.cur_pos[0] = comp_xyz[0];
            csa.cur_pos[1] = comp_xyz[1];
            csa.cur_pos[3] = 0;
            await set_motor_pos(true);
        }
        disable_goto_btn(false);
    }
}
window.move_to_comp = move_to_comp;


function pos_to_page(pos) {
    let pos_list = document.getElementById('pos_list');
    pos_list.innerHTML = '';
    
    for (let footprint in pos) {
        let html_value = '';
        for (let value in pos[footprint]) {
            let html_comp = '';
            for (let comp of pos[footprint][value]) {
                html_comp += `
                    <tr class='list_comp' onclick=move_to_comp('${comp[0]}');>
                        <td style="width: 10em;">${comp[0]}</td>
                        <td style="width: 7em;">${readable_float(comp[1])}</td>
                        <td style="width: 7em;">${readable_float(comp[2])}</td>
                        <td style="width: 7em;">${readable_float(comp[3])}</td>
                    </tr>`;
            }
            html_value += `
                <tr class='list_value'>
                    <td style="width: 20em;">${value}</td>
                    <td>
                        <table>
                            <tbody class="js-sortable-table">
                                ${html_comp}
                            </tbody>
                        </table>
                    </td>
                </tr>`;
        }
        let html = `
            <tr class='list_footprint'>
                <td>${footprint}</td>
                <td>--</td>
                <td colspan="5">
                    <table>
                        <tbody class="js-sortable-table">
                            ${html_value}
                        </tbody>
                    </table>
                </td>
            </tr>`;
        pos_list.insertAdjacentHTML('beforeend', html);
    }
    
    sortable('.js-sortable-table');
    for (let s of sortable('.js-sortable-table')) {
        s.addEventListener('sortupdate', async function(e) {
            console.log('update list to db');
            await db.set('tmp', 'list', pos_from_page());
            select_comp(search_current_comp());
        });
    }
}

function pos_from_page() {
    let pos = {};
    let pos_list = document.getElementById('pos_list');
    let footprint_list = pos_list.getElementsByClassName('list_footprint');
    for (let footprint_elm of footprint_list) {
        let footprint = footprint_elm.querySelector('td').innerText;
        pos[footprint] = {};
        let value_list = footprint_elm.getElementsByClassName('list_value');
        for (let value_elm of value_list) {
            let value = value_elm.querySelector('td').innerText;
            pos[footprint][value] = [];
            let comp_list = value_elm.getElementsByClassName('list_comp');
            for (let comp_elm of comp_list) {
                let comp_tds = comp_elm.querySelectorAll('td');
                pos[footprint][value].push([comp_tds[0].innerText,
                    Number(comp_tds[1].innerText), Number(comp_tds[2].innerText), Number(comp_tds[3].innerText)]);
            }
        }
    }
    return pos;
}

function csv_to_pos(csv)
{
    let csv_list = csv_parser(csv);
    let ref_cnt = {};
    let pos = {};
    for (let row of csv_list) {
        if (!isFinite(row[5]) || !row[0].length)
            continue;
        // avoid same reference name
        let ref = row[0];
        if (ref in ref_cnt) {
            ref_cnt[ref] += 1;
            ref += `_${ref_cnt[row[0]]}`;
        } else {
            ref_cnt[ref] = 0;
        }
        
        let row_ = [ref, Number(row[3].replace('mm', '')), -Number(row[4].replace('mm', '')), Number(row[5])];
        if (row[6].toLowerCase().startsWith('b')) // bottom layer
            row_[3] = 180 - row_[3];
        if (row_[3] > 180.0)
            row_[3] = -(360 - row_[3]);
        
        if (row[2] in pos) {
            if (row[1] in pos[row[2]])
                pos[row[2]][row[1]].push(row_);
            else
                pos[row[2]][row[1]] = [row_];
        } else {
            pos[row[2]] = {};
            pos[row[2]][row[1]] = [row_];
        }
    }
    return pos;
}


document.getElementById('btn_load_csv').onclick = async function() {
    console.log('load_csv');
    
    //let input = document.createElement('input');
    //cpy(input, {type: 'file', accept: '*.cdg'}, ['type', 'accept']);
    let input = document.getElementById('input_file');
    input.accept = '.csv';
    input.onchange = async function () {
        var files = this.files;
        if (files && files.length) {
            let file = files[0];
            let data = await read_file(file);
            let data_str = new TextDecoder().decode(data);
            let pos = csv_to_pos(data_str);
            console.log('load pos:', pos);
            pos_to_page(pos);
            await db.set('tmp', 'list', pos);
        }
        this.value = '';
    };
    input.click();
};


function set_board(idx) {
    for (let i = 0; i < 10; i++)
        document.getElementById(`btn_board${i}`).style.backgroundColor = '';
    document.getElementById(`btn_board${idx}`).style.backgroundColor = '#D5F5E3';
    document.getElementById(`cur_board`).innerText = `#${idx}`;
}

function get_board_safe() {
    for (let i = 0; i < 10; i++)
        if (document.getElementById(`btn_board${i}`).style.backgroundColor)
            return i;
    document.getElementById(`btn_board0`).style.backgroundColor = '#D5F5E3';
    document.getElementById(`cur_board`).innerText = `#0`;
    return 0;
}

function set_step(idx) {
    for (let i = 0; i < 6; i++)
        document.getElementById(`btn_step${i}`).style.backgroundColor = '';
    document.getElementById(`btn_step${idx}`).style.backgroundColor = '#D5F5E3';
}

function get_step_safe() {
    for (let i = 0; i < 6; i++)
        if (document.getElementById(`btn_step${i}`).style.backgroundColor)
            return i;
    let idx = Number(!document.getElementById('show_target').checked);
    document.getElementById(`btn_step${idx}`).style.backgroundColor = '#D5F5E3';
    return idx;
}

function set_comp_search(idx) {
    for (let i = 0; i < 8; i++)
        document.getElementById(`btn_comp_search${i}`).style.backgroundColor = '';
    document.getElementById(`btn_comp_search${idx}`).style.backgroundColor = '#D5F5E3';
}

function get_comp_search() {
    for (let i = 0; i < 8; i++)
        if (document.getElementById(`btn_comp_search${i}`).style.backgroundColor)
            return i;
    document.getElementById(`btn_comp_search0`).style.backgroundColor = '#D5F5E3';
    return 0;
}


function get_comp_safe() {
    let comp = search_current_comp();
    if (!comp) {
        comp = search_first_comp();
        if (!comp)
            return null;
        select_comp(comp);
    }
    return comp;
}


window.btn_select_search = function (idx) {
    if (idx >= csa.comp_search.length)
        return;
    set_comp_search(idx);
};

window.btn_select_step = function (idx) {
    set_step(idx);
};

window.btn_select_board = async function (idx) {
    if (idx >= csa.fiducial_cam.length)
        return;
    set_board(idx);
    await select_comp(search_current_comp());
};


export {
    search_comp_parents, search_next_comp, search_current_comp, search_first_comp, select_comp, move_to_comp,
    get_comp_values, pos_to_page, pos_from_page, csv_to_pos,
    set_board, get_board_safe, set_step, get_step_safe, set_comp_search, get_comp_search, get_comp_safe
};
