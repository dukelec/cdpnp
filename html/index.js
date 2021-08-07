/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { L } from './lang/lang.js'
import { sleep, escape_html, date2num, timestamp, val2hex, dat2str, dat2hex, hex2dat,
         read_file, download, readable_size, blob2dat, csv_parser, readable_float } from './utils/helper.js';
//import { konva_zoom, konva_responsive } from './utils/konva_helper.js';
import { CDWebSocket, CDWebSocketNS } from './utils/cd_ws.js';
import { Idb } from './utils/idb.js';
import { search_comp_parents, search_next_comp, search_current_comp, search_first_comp, select_comp,
         pos_to_page, pos_from_page, csv_to_pos,
         set_board, get_board_safe, set_step, get_step_safe, set_comp_search, get_comp_search, get_comp_safe } from './pos_list.js';
import { csa_to_page_pos, csa_to_page_input, csa_from_page_input  } from './input_ctrl.js';

let csa = {
    shortcuts: false,
    cur_pos: [0, 0, 0, 0],
    aux_pos: [0, 0, 0, 0],
    
    grab_ofs: [-33.9, -7.0],
    comp_search: [[50, 165], [50, 185]],
    comp_top_z: -85.5,
    pcb_top_z: -84.5,
    comp_base_z: -89.3,
    pcb_base_z: -88.2,
    fiducial_pcb: [[-26.375, 21.35], [-6.3, 4.75]],
    fiducial_cam: [[[89.673, 175.000], [109.861, 158.607]], [[120.720, 175.347], [140.849, 158.856]]],
};

let db = null;
let ws_ns = new CDWebSocketNS('/');
let cmd_sock = new CDWebSocket(ws_ns, 'cmd');


document.getElementById('btn_run').onclick = async function() {
    let comp = get_comp_safe();
    if (!comp) {
        alert("list empty!");
        return;
    }
    
    while (true) {
        let comp = get_comp_safe();
        if (!comp)
            break;
        let board = get_board_safe();
        let step = get_step_safe();
        let search = get_comp_search();
        console.log(`comp: ${comp}, board: ${board}, step: ${step}, search: ${search}`);
        await sleep(500);
        
        if (step == 0) { // show_target
            console.log('show target');
            set_step(1);
            continue;
        }
        
        if (step == 1) { // goto_comp
            console.log('show target');
            set_step(2);
            continue;
        }
        
        if (step == 2) { // snap
            console.log('show target');
            set_step(3);
            continue;
        }
        
        if (step == 3) { // pickup
            console.log('pickup');
            set_step(4);
            continue;
        }
        
        if (step == 4) { // goto_pcb
            console.log('goto_pcb');
            set_step(5);
            continue;
        }
        
        if (step == 5) { // putdown
            console.log('putdown');
            set_step(0);
        }
        
        if (++board >= csa.fiducial_cam.length) {
            set_board(0);
            let next = search_next_comp(comp);
            select_comp(next);
            if (!next)
                break;
        } else {
            set_board(board);
        }
    }
    console.log('all comp finished');
};


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
