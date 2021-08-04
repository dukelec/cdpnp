/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { Queue } from './helper.js'

// packet format:
//   {
//       src: [addr, port], dst: [addr, port],
//       dat: ...
//   }


class CDWebSocket {
    constructor(ns, port) {
        this.ns = ns;
        this.port = port;
        this.recv_q = new Queue();
        console.assert(!(this.port in this.ns.sockets));
        this.ns.sockets[this.port] = this;
    }
    
    delete_() {
        delete this.ns.sockets[this.port];
    }
    
    async sendto(dat, s_addr) {
        let msg = msgpack.serialize({'src': [this.ns.addr, this.port], 'dst': s_addr, 'dat': dat});
        if (s_addr[0] in this.ns.connections)
            await this.ns.connections[s_addr[0]].send(msg);
        else if (this.ns.def_route && (this.ns.def_route in this.ns.connections))
            await this.ns.connections[this.ns.def_route].send(msg);
    }
    
    async recvfrom(timeout=null) {
        return await this.recv_q.get(timeout=timeout);
    }
    
    flush() {
        this.recv_q.flush();
    }
}


class CDWebSocketNS {
    constructor(addr, def_route=null) {
        this.addr = addr;
        this.def_route = def_route;
        this.connections = {};
        this.sockets = {};
    }
}

export { CDWebSocket, CDWebSocketNS };
