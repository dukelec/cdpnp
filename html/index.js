/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { L } from './lang/lang.js'
import { escape_html, date2num, timestamp, val2hex, dat2str, dat2hex, hex2dat,
         read_file, download, readable_size, blob2dat, csv_parser } from './utils/helper.js';
//import { konva_zoom, konva_responsive } from './utils/konva_helper.js';
import { CDWebSocket, CDWebSocketNS } from './utils/cd_ws.js';
import { Idb } from './utils/idb.js';

let db = null;
let ws_ns = new CDWebSocketNS('/');
let cmd_sock = new CDWebSocket(ws_ns, 'cmd');
let dbg_sock = new CDWebSocket(ws_ns, 9);
let cfgs = null;


async function init_cfg_list() {
    let sel_ops = '<option value="">--</option>';
    for (let op of cfgs)
        sel_ops += `<option value="${op}">${op}</option>`;
    let list = document.getElementById('cfg_list');
    
    let devs = await db.get('tmp', 'dev_list');
    for (let i = 0; i < 10; i++) {
        let tgt = (devs && devs[i]) ? devs[i].tgt : `80:00:${val2hex(i+1,2)}`;
        let cfg = (devs && devs[i]) ? devs[i].cfg : '';
        let name = (devs && devs[i]) ? devs[i].name : '';
        let html = `
            <input type="text" placeholder="Name Label" value="${name}" id="cfg${i}.name">
            <input type="text" placeholder="CDNET IP" value="${tgt}" id="cfg${i}.tgt">
            <select id="cfg${i}.cfg" value="${cfg}">${sel_ops}</select>
            <button class="button is-small" id="cfg${i}.btn">Open Window</button> <br>
        `;
        
        list.insertAdjacentHTML('beforeend', html);
        document.getElementById(`cfg${i}.cfg`).value = `${cfg}`;
        
        document.getElementById(`cfg${i}.btn`).onclick = async () => {
            let t = document.getElementById(`cfg${i}.tgt`).value;
            let c = document.getElementById(`cfg${i}.cfg`).value;
            let n = document.getElementById(`cfg${i}.name`).value;
            console.log(`t: ${t}, c: ${c}`);
            if (!t || !c || !n) {
                alert('Empty not allowed');
                return;
            }
            window.open(`ctrl.html?tgt=${t}&cfg=${c}&name=${n}`, "_blank");
        };
        
        document.getElementById(`cfg${i}.name`).onchange =
                document.getElementById(`cfg${i}.tgt`).onchange =
                document.getElementById(`cfg${i}.cfg`).onchange = async () => {
            
            let devs = [];
            for (let n = 0; n < 10; n++) {
                devs.push({
                    tgt: document.getElementById(`cfg${n}.tgt`).value,
                    cfg: document.getElementById(`cfg${n}.cfg`).value,
                    name: document.getElementById(`cfg${n}.name`).value,
                });
            }
            await db.set('tmp', 'dev_list', devs);
        };
    }
}


function init_ws() {
    let ws_url = 'ws://' + window.location.hostname + ':8900';
    let ws = new WebSocket(ws_url);
    
    ws.onopen = async function(evt) {
        console.log("ws onopen");
        ws_ns.connections['server'] = ws;
        
    }
    ws.onmessage = async function(evt) {
        let dat = await blob2dat(evt.data);
        var msg = msgpack.deserialize(dat);
        //console.log("Received dat", msg);
        var sock = ws_ns.sockets[msg['dst'][1]];
        sock.recv_q.put([msg['dat'], msg['src']]);
    }
    ws.onerror = function(evt) {
        console.log("ws onerror: ", evt);
        document.body.style.backgroundColor = "gray";
    }
    ws.onclose = function(evt) {
        delete ws_ns.connections['server'];
        console.log('ws disconnected');
        document.body.style.backgroundColor = "gray";
    }
}


function pos_to_page(pos) {
    let pos_list = document.getElementById('pos_list');
    pos_list.innerHTML = '';
    
    for (let footprint in pos) {
        let html_value = '';
        for (let value in pos[footprint]) {
            let html_comp = '';
            for (let comp of pos[footprint][value]) {
                html_comp += `
                    <tr class='list_comp'>
                        <td>${comp[0]}</td>
                        <td>${comp[1]}</td>
                        <td>${comp[2]}</td>
                        <td>${comp[3]}</td>
                    </tr>`;
            }
            html_value += `
                <tr class='list_value'>
                    <td>${value}</td>
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
                pos[footprint][value].push([comp_tds[0].innerText, comp_tds[1].innerText, comp_tds[2].innerText, comp_tds[3].innerText]);
            }
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
            let csv_list = csv_parser(data_str);
            console.log('output dat:', csv_list);
            
            let pos = {};
            for (let row of csv_list) {
                if (row[0] == 'Ref' || !row[0].length)
                    continue;
                let row_ = [row[0], row[3].slice(0, -3), row[4].slice(0, -3), row[5].slice(0, -5)];
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
            
            console.log('pos_to_page:', pos);
            pos_to_page(pos);
            sortable('.js-sortable-table');
        }
        this.value = '';
        document.getElementById('btn_load_csv').disabled = false;
    };
    input.click();
};

document.getElementById('btn_update_csv').onclick = async function() {
    let p = pos_from_page();
    console.log('pos_from_page', p);
    pos_to_page(p);
};

window.addEventListener('load', async function() {
    console.log("load app");
    db = await new Idb();
    init_ws();
});

