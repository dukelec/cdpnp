/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

let trans_hk = {
    'OK': '好',
    'Switching APP to new version.': '切換 APP 至新版本'
};

// cat lang.js | cconv -f UTF8 -t UTF8-CN
let trans_cn = {
    'OK': '好',
    'Switching APP to new version.': '切换 APP 至新版本'
};


let lang = 'en';
if (navigator.language.startsWith('zh')) {
    lang = 'hk';
    if (navigator.language.includes('CN'))
        lang = 'cn';
}

function L(ori, mark=null) {
    if (lang == 'en')
        return ori;
    if (!mark)
        mark = ori;
    let ret = lang == 'hk' ? trans_hk[mark] : trans_cn[mark];
    return ret || ori;
}

export { L };
