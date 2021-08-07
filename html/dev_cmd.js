/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { escape_html, date2num, timestamp, val2hex, dat2str, dat2hex, hex2dat,
         read_file, download, readable_size, blob2dat, csv_parser, readable_float } from './utils/helper.js';
import { csa, cmd_sock } from './index.js';



async function set_motor_pos(wait=false, pos=null) {
    if (pos)
        csa.cur_pos = pos;
    console.log('set_motor_pos:', csa.cur_pos);
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_motor_pos', 'pos': csa.cur_pos, 'wait': wait}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(20000);
    console.log('set_motor_pos ret', dat);
}

async function set_pump(val) {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'set_pump', 'val': val}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(2000);
    console.log(`set_pump ${pump_en} ret`, dat);
}

async function update_coeffs() {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'update_coeffs', 'pcb': csa.fiducial_pcb, 'cam': csa.fiducial_cam}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(1500);
    console.log('update_coeffs ret', dat);
}

async function pcb2xyz(idx, x, y) {
    cmd_sock.flush();
    await cmd_sock.sendto({'action': 'pcb2xyz', 'idx': idx, 'x': x, 'y': y}, ['server', 'dev']);
    let dat = await cmd_sock.recvfrom(1000);
    console.log('pcb2xyz ret', dat);
    return dat ? dat[0] : null;
}

async function z_keep_high() {
    let min_z = Math.max(csa.pcb_top_z, csa.comp_top_z);
    if (csa.cur_pos[2] < min_z) {
        csa.cur_pos[2] = min_z;
        await set_motor_pos(true);
    }
}


export {
    set_motor_pos, set_pump, update_coeffs, pcb2xyz, z_keep_high
};
