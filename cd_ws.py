#!/usr/bin/env python3
#
# Software License Agreement (MIT License)
#
# Author: Duke Fong <d@d-l.io>
#

# Packet format:
#   {
#       src: (addr, port), dst: (addr, port),
#       dat: ...
#   }
#
# The addr and port format: any string (or number)
# The dat format: dict for convention

import umsgpack
import asyncio


class CDWebSocket():
    def __init__(self, ns, port):
        self.ns = ns
        self.port = port
        self.recv_q = asyncio.Queue()
        assert self.port not in self.ns.sockets
        self.ns.sockets[self.port] = self
    
    def delete(self):
        #await self.recv_q.join()
        del self.ns.sockets[self.port]
    
    async def sendto(self, dat, s_addr):
        msg = umsgpack.packb({'src': (self.ns.addr, self.port), 'dst': s_addr, 'dat': dat})
        if s_addr[0] in self.ns.connections:
            await self.ns.connections[s_addr[0]].send(msg)
            return None
        elif self.ns.def_route and (self.ns.def_route in self.ns.connections):
            await self.ns.connections[self.ns.def_route].send(msg)
            return None
        else:
            return 'no route'
    
    async def recvfrom(self, timeout=None):
        # throw asyncio.TimeoutError if timeout
        return await asyncio.wait_for(self.recv_q.get(), timeout=timeout)


class CDWebSocketNS():
    def __init__(self, addr, def_route=None):
        self.addr = addr
        self.def_route = def_route
        self.connections = {} # id: ws
        self.sockets = {}     # port: CDWebSocket


# cd_ws_def_ns = CDWebSocketNS('server')

