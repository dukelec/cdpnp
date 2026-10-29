#!/usr/bin/env python3
#
# Software License Agreement (MIT License)
#
# Author: Duke Fong <d@d-l.io>
#
# Static asset caching: pages (.html) are always revalidated (no-cache), and every url they
# use for our own css / js carries ?v=<version-content hash> (the ?v=__V__ placeholder in the
# source is filled in when the file is sent), such urls are cached for a year as immutable.
# Change any front end file and the hash changes -> the urls change -> the browser is bound to
# fetch the new files, and it can never pair an old script with a new page.
# The version is rechecked on every request, so editing a front end file takes effect on the next
# reload without restarting the tool: were it pinned at startup, an edited file would keep the old
# ?v= url and the browser would go on using its cached copy of the file before the edit.
# Third party files under libs/ carry their version in the file name, they are immutable as they
# are (a new version means a new file name).
#

import os
import re
import hashlib
import functools
import asyncio
import mimetypes
import umsgpack
import logging
import websockets
from urllib.parse import parse_qs
from websockets.asyncio.server import serve
from websockets.http11 import Response
from websockets.datastructures import Headers
from http import HTTPStatus
from cd_ws import CDWebSocket, CDWebSocketNS

ws_ns = CDWebSocketNS('server')
logger = logging.getLogger(f'cdpnp.web')

WS_CLOSE_DUPLICATE = 4001 # close code: the same page is already opened in another window

HTML = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'html'))
VERSION_FILE = 'index.js' # VERSION = '...' is read from this file under html/
TOKEN = '__V__'         # the version placeholder in our own front end files (written as ?v=__V__)
IMMUTABLE = 'public, max-age=31536000, immutable'
INJECT_EXT = ('.html', '.js')   # our own files the placeholder is filled in for (libs/ excluded)


def own_files():
    # all our own front end files, libs/ excluded (those are versioned by their file name)
    paths = []
    for root, dirs, files in os.walk(HTML):
        dirs[:] = [d for d in dirs if d != 'libs']
        paths += [os.path.join(root, f) for f in files]
    return sorted(paths)


_ver_cache = {'sig': None, 'ver': '0'}

def get_asset_ver():
    # "version-content hash", e.g. v3.0-1a2b3c4d5e: the version comes from VERSION in html/index.js,
    # the hash from the content of all our own front end files. Called for every request, but all it
    # normally does is stat them; the hash is recomputed only once something really changed, so the
    # version follows the files right away without making the browser re-download an unchanged one.
    try:
        paths = own_files()
        sig = []
        for p in paths:
            st = os.stat(p)
            sig.append((p, st.st_mtime_ns, st.st_size))
        sig = tuple(sig)
        if sig != _ver_cache['sig']:
            h = hashlib.sha1()
            for p in paths:
                with open(p, 'rb') as fh:
                    h.update(os.path.relpath(p, HTML).encode() + fh.read())
            with open(os.path.join(HTML, VERSION_FILE), encoding='utf-8') as f:
                m = re.search(r"VERSION\s*=\s*'([^']+)'", f.read())
            v = m.group(1) if m else '0'
            _ver_cache['sig'] = sig
            _ver_cache['ver'] = f'{v}-{h.hexdigest()[:10]}'
    except OSError:
        pass        # a file is being written right now, keep the version we had
    return _ver_cache['ver']


# the static files, sent from the websocket server's process_request hook: a request that is
# not an upgrade gets a plain http response and the connection is closed after it
def http_reply(status, headers, body=b''):
    return Response(status.value, status.phrase, Headers(headers), body)

async def http_file_server(connection, request, origins):
    if "upgrade" in request.headers.get("Connection", "").lower():
        # only a page this server served may connect, see own_origins(). Checked here rather than
        # with the origins= of serve(), which logs every refusal as an error with a traceback
        origin = request.headers.get('Origin')
        if origin not in origins:
            logger.warning(f'ws: refused origin {origin} for {request.path}')
            return connection.respond(HTTPStatus.FORBIDDEN, 'this page is not served by cdpnp\n')
        return None
    path, _, query = request.path.partition('?')
    if path.endswith('/'):
        path += 'index.html'
    response_headers = [
        ('Connection', 'close'),
    ]
    full_path = os.path.realpath(os.path.join(HTML, path[1:]))
    log_str = f'GET {path}'

    # Validate the path
    if os.path.commonpath((HTML, full_path)) != HTML or \
            not os.path.exists(full_path) or not os.path.isfile(full_path):
        logger.warning(f'{log_str} 404 NOT FOUND')
        body = b'404 NOT FOUND'
        response_headers += [('Content-Length', str(len(body))), ('Content-Type', 'text/plain')]
        return http_reply(HTTPStatus.NOT_FOUND, response_headers, body)

    in_libs = os.path.relpath(full_path, HTML).split(os.sep)[0] == 'libs'
    ext = os.path.splitext(full_path)[1]
    if not in_libs and ext in INJECT_EXT:
        # our own html / js: fill in the version placeholder before sending
        with open(full_path, encoding='utf-8') as f:
            body = f.read().replace(TOKEN, get_asset_ver()).encode()
        content_type = ('text/html' if ext == '.html' else 'text/javascript') + '; charset=utf-8'
    else:
        with open(full_path, 'rb') as f:
            body = f.read()
        content_type = mimetypes.MimeTypes().guess_type(full_path)[0] or 'application/octet-stream'

    # a url with ?v= only ever serves one content, so it may be cached for good; pages are
    # revalidated every time, an unchanged one costs a 304 without the body
    response_headers.append(('Cache-Control', IMMUTABLE if (in_libs or 'v' in parse_qs(query)) else 'no-cache'))
    etag = f'"{hashlib.sha1(body).hexdigest()[:20]}"'
    response_headers.append(('ETag', etag))
    if etag in [t.strip() for t in request.headers.get('If-None-Match', '').split(',')]:
        logger.info(f'{log_str} 304 NOT MODIFIED')
        return http_reply(HTTPStatus.NOT_MODIFIED, response_headers)

    logger.info(f'{log_str} 200 OK')
    response_headers.append(('Content-Length', str(len(body))))
    response_headers.append(('Content-Type', content_type))
    return http_reply(HTTPStatus.OK, response_headers, body)


async def ws_handler(ws):
    path = ws.request.path
    logger.info(f'ws: connect, path: {path}')
    if path in ws_ns.connections:
        logger.warning(f'ws: only allow one connection for: {path}')
        await ws.close(WS_CLOSE_DUPLICATE, 'duplicate connection')
        return
    ws_ns.connections[path] = ws
    try:
        while True:
            msg_ = await ws.recv()
            msg = umsgpack.unpackb(msg_)
            if msg['dst'][0] != 'server':
                logger.warning('ws: addr error')
                return
            # a page may address a service this run does not have: drop the message, killing
            # the connection over it would take the whole page down with it
            if msg['dst'][1] not in ws_ns.sockets:
                logger.warning(f'ws: drop msg for unknown port: {msg["dst"][1]}')
                continue
            sock = ws_ns.sockets[msg['dst'][1]]
            sock.recv_q.put_nowait((msg['dat'], msg['src']))
    
    except websockets.exceptions.ConnectionClosed:
        pass
    #except:
    #    pass
    
    finally:
        # always give the path up again, or the next page for it is refused as a duplicate
        del ws_ns.connections[path]
        logger.info(f'ws: disconnect, path: {path}')


# The browser sends the origin of the page on every websocket handshake, so only a page this
# server served gets to connect: any other website open in the same browser could otherwise open
# ws://localhost:8900/ and drive the machine through it. A client that is not a browser
# sends no Origin (None) and is let in, it is a local process.
def own_origins(port):
    return [f'http://{h}:{port}' for h in ('localhost', '127.0.0.1', '[::1]')] + [None]


async def start_web(addr='localhost', port=8900):
    process = functools.partial(http_file_server, origins=own_origins(port))
    async with serve(ws_handler, addr, port, process_request=process, max_size=None) as server:
        await server.serve_forever()
