/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

import { trans_zh_hk }  from './trans/zh_hk.js?v=__V__'
import { trans_zh_cn }  from './trans/zh_cn.js?v=__V__'
//import { trans_ja }     from './trans/ja.js?v=__V__'
//import { trans_ko }     from './trans/ko.js?v=__V__'
//import { trans_de }     from './trans/de.js?v=__V__'

// the language picker offers these, '' means follow the browser
const LANGS = [['', 'Auto'], ['en', 'English'], ['zh-CN', '简体中文'], ['zh-HK', '繁體中文']];

// the lang item in localStorage wins over the browser language (picker in the nav bar)
function lang_pref() { try { return localStorage.getItem('lang') || ''; } catch { return ''; } }
function set_lang(v) { try { v ? localStorage.setItem('lang', v) : localStorage.removeItem('lang'); } catch {} }

const lang = lang_pref() || navigator.language;

let trans = null;
if (lang.startsWith('zh')) {
    trans = trans_zh_hk;
    if (lang.includes('CN') || lang.includes('Hans'))
        trans = trans_zh_cn;
}
//if (lang.startsWith('ja')) // Japanese
//    trans = trans_ja;
//if (lang.startsWith('ko')) // Korean
//    trans = trans_ko;
//if (lang.startsWith('de')) // German
//    trans = trans_de;

function L(ori, mark=null) {
    if (trans == null)
        return ori;
    if (!mark)
        mark = ori;
    return trans[mark] || ori;
}

export { L, LANGS, lang_pref, set_lang };
