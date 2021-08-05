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
import { csa_to_page_pos, csa_to_page_input, csa_from_page_input  } from './input_ctrl.js';

let csa = {
    shortcuts: false,
    cur_pos: [0, 0, 0, 0],
    aux_pos: [0, 0, 0, 0],
    
    grab_ofs: [-33.9, -7.0],
    comp_search: [[50, 165], [50, 185], null],
    comp_top_z: -85.5,
    pcb_top_z: -84.5,
    comp_base_z: -89.3,
    pcb_base_z: -88.2,
    fiducial_pcb: [[-26.375, 21.35], [-6.3, 4.75]],
    fiducial_cam: [[[89.673, 175.000], [109.861, 158.607]], [[120.720, 175.347], [140.849, 158.856]], null],
};

let db = null;
let ws_ns = new CDWebSocketNS('/');
let cmd_sock = new CDWebSocket(ws_ns, 'cmd');


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
        
        cmd_sock.flush();
        await cmd_sock.sendto({'action': 'get_motor_pos'}, ['server', 'dev']);
        let dat = await cmd_sock.recvfrom(500);
        console.log('get_cur_pos ret', dat);
        csa.cur_pos = csa.aux_pos = dat[0];
        csa_to_page_pos();
        
        await cmd_sock.sendto({'action': 'get_init_home'}, ['server', 'dev']);
        dat = await cmd_sock.recvfrom(500);
        console.log('get_init_home ret', dat);
        if (dat[0])
            document.getElementById('btn_set_home').style.backgroundColor = '';
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
            sortable('.js-sortable-table');
        }
        this.value = '';
        document.getElementById('btn_load_csv').disabled = false;
    };
    input.click();
};

window.addEventListener('load', async function() {
    console.log("load app");
    db = await new Idb();
    init_ws();
    
    let csa_pre = await db.get('tmp', 'csa');
    if (csa_pre)
        csa = csa_pre;
    csa_to_page_input();
});

export {
    csa, cmd_sock, db
};
