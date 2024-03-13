/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function read_file(file) {
    return await new Promise((resolve, reject) => {
        let reader = new FileReader();

        reader.onload = () => {
            resolve(new Uint8Array(reader.result));
        };
        reader.onerror = reject;
        reader.readAsArrayBuffer(file);
    })
}

async function load_img(img, url) {
    let ret = -1;
    await new Promise(resolve => {
        img.src = url;
        img.onload = () => { ret = 0; resolve(); };
        img.onerror = () => { console.error(`load_img: ${url}`); resolve(); };
    });
    return ret;
}

function date2num() {
    let d = (new Date()).toLocaleString('en-GB');
    let s = d.split(/[^0-9]/);
    return `${s[2]}${s[1]}${s[0]}${s[4]}${s[5]}${s[6]}`;
}

function timestamp() {
    let date = new Date();
    let time = date.toLocaleString('en-GB');
    return time.split(' ')[1] + '.' + String(date.getMilliseconds()).padStart(3, '0');
}

async function sha256(dat) {
    const hashBuffer = await crypto.subtle.digest('SHA-256', dat);
    return new Uint8Array(hashBuffer);
}

async function aes256(dat, key, type='encrypt') {
    let iv = new Uint8Array(16); // zeros
    let _key = await crypto.subtle.importKey('raw', key, {name: 'AES-CBC'}, false, ['encrypt', 'decrypt']);

    if (type == 'encrypt')
        return new Uint8Array(await crypto.subtle.encrypt({name: 'AES-CBC', iv: iv}, _key, dat));
    else
        return new Uint8Array(await crypto.subtle.decrypt({name: 'AES-CBC', iv: iv}, _key, dat));
}

function dat2hex(dat, join='', le=false) {
    let dat_array = Array.from(dat);
    if (le)
        dat_array = dat_array.reverse();
    return dat_array.map(b => b.toString(16).padStart(2, '0')).join(join);
}

function hex2dat(hex, le=false) {
    hex = hex.replace('0x', '').replace(/\s/g,'')
    let ret = new Uint8Array(hex.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
    if (le)
        return ret.reverse();
    return ret;
}

function dat2str(dat) {
    return new TextDecoder().decode(dat);
}

function str2dat(str) {
    let encoder = new TextEncoder();
    return encoder.encode(str);
}

function val2hex(val, fixed=4, prefix=false, upper=false, float=false) {
    let sign = Math.sign(val);
    val = Math.abs(val);
    let str = upper ? val.toString(16).toUpperCase() : val.toString(16);
    let arr = str.split('.');
    if (arr[0].length < fixed)
        arr[0] = '0'.repeat(fixed - arr[0].length) + arr[0];
    if (prefix)
        arr[0] = '0x' + arr[0];
    if (sign == -1)
        arr[0] = '-' + arr[0];
    if (float && arr.length == 1)
        arr.push('0');
    return arr.join('.');
}

// list: ['x', 'y']
// map: {'rotation': 'r'}
function cpy(dst, src, list, map = {}) {
    for (let i of list) {
        if (i in src)
            dst[i] = src[i];
    }
    for (let i in map) {
        if (i in src)
            dst[map[i]] = src[i];
    }
}

class Queue {
    constructor() {
        this.fifo = [];
        this.wakeup = null;
    }
    
    put(t) {
        this.fifo.push(t);
        if (this.wakeup)
            this.wakeup();
    }
    
    async get(timeout=null) {
        if (this.fifo.length)
            return this.fifo.shift();
        if (timeout == 0)
            return null;
        
        let p = new Promise(resolve => { this.wakeup = resolve; });
        let t;
        if (timeout)
            t = setTimeout(() => { this.wakeup(); }, timeout, null); // unit: ms
        
        await p;
        
        this.wakeup = null;
        if (timeout)
            clearTimeout(t);
        if (this.fifo.length)
            return this.fifo.shift();
        return null;
    }
    
    // now some utilities:
    size() {
        return this.fifo.length;
    }
    flush() {
        this.fifo = [];
        if (this.wakeup)
            this.wakeup();
        this.wakeup = null;
    }
}

function download_url(data, fileName) {
    var a;
    a = document.createElement('a');
    a.href = data;
    a.download = fileName;
    document.body.appendChild(a);
    a.style = 'display: none';
    a.click();
    a.remove();
};

function download(data, fileName='dat.bin', mimeType='application/octet-stream') {
    var blob, url;
    blob = new Blob([data], {type: mimeType});
    url = window.URL.createObjectURL(blob);
    download_url(url, fileName);
    setTimeout(function() { return window.URL.revokeObjectURL(url); }, 1000);
};

function escape_html(unsafe) {
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

function readable_size(bytes, fixed=3, si=true) {
    var thresh = si ? 1000 : 1024;
    if(Math.abs(bytes) < thresh) {
        return bytes + ' B';
    }
    var units = si
        ? ['kB','MB','GB','TB','PB','EB','ZB','YB']
        : ['KiB','MiB','GiB','TiB','PiB','EiB','ZiB','YiB'];
    var u = -1;
    do {
        bytes /= thresh;
        ++u;
    } while(Math.abs(bytes) >= thresh && u < units.length - 1);
    return bytes.toFixed(fixed)+' '+units[u];
}

function readable_float(num, fixed=6, double=true) {
    if (!isFinite(num))
        return num.toString();
    if (!double)
        num = parseFloat(num.toPrecision(7)); // for 32-bit float
    let n = num.toFixed(fixed);
    if (n.indexOf('e') != -1)
        return n;
    for (let i = 0; i < fixed / 3; i++) {
        if (n.endsWith('000'))
            n = n.slice(0, n.length - 3);
        else
            break;
    }
    if (n.endsWith('.'))
        n += '0';
    return n;
}

async function blob2dat(blob) {
    let ret;
    await new Promise(resolve => {
        new Response(blob).arrayBuffer().then(buf => {
            ret = new Uint8Array(buf);
            resolve();
        });
    });
    return ret;
}

function deep_merge(target, ...sources) {
    for (let source of sources) {
        for (let k in source) {
            let vs = source[k], vt = target[k]
            if (Object(vs) == vs && Object(vt) === vt) {
                target[k] = deep_merge(vt, vs)
                continue;
            }
            target[k] = source[k];
        }
    }
    return target
}

// https://stackoverflow.com/questions/1293147
function csv_parser(str, delimiter ){
    delimiter = (delimiter || ",");
    let objPattern = new RegExp((
            // Delimiters.
            "(\\" + delimiter + "|\\r?\\n|\\r|^)" +
            // Quoted fields.
            "(?:\"([^\"]*(?:\"\"[^\"]*)*)\"|" +
            // Standard fields.
            "([^\"\\" + delimiter + "\\r\\n]*))"
        ), "gi" );
    let arrData = [[]];
    let arrMatches = null;
    while (arrMatches = objPattern.exec(str)) {
        let strMatchedDelimiter = arrMatches[1];
        if (strMatchedDelimiter.length && strMatchedDelimiter !== delimiter)
            arrData.push([]);
        let strMatchedValue;
        if (arrMatches[2])
            strMatchedValue = arrMatches[2].replace(new RegExp( "\"\"", "g" ), "\"");
        else
            strMatchedValue = arrMatches[3];
        arrData[arrData.length - 1].push(strMatchedValue);
    }
    return arrData;
}

// https://stackoverflow.com/questions/26246601
function wildcard_test(str, wildcard) {
    let w = wildcard.replace(/[.+^${}()|[\]\\]/g, '\\$&'); // regexp escape 
    const re = new RegExp(`^${w.replace(/\*/g,'.*').replace(/\?/g,'.')}$`);
    return re.test(str);
}

export {
    sleep, read_file, load_img, date2num, timestamp,
    sha256, aes256,
    dat2hex, hex2dat, dat2str, str2dat, val2hex,
    cpy, Queue,
    download,
    escape_html, readable_size, readable_float,
    blob2dat, deep_merge,
    csv_parser, wildcard_test
};
