/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 *
 * Two things the run learns from camera 1 while it picks components:
 *
 * The parts seen at a comp search position. One frame taken there is recorded as a list
 * of candidates, each with its machine position and its size, and the following picks go
 * straight to the best remaining one instead of back to the search position every time.
 * A candidate is scored by its distance to the frame center (the detection is more
 * reliable there) and by how well its size agrees with the others, or with a part
 * already picked, so a speck of dirt is tried last. The list is recorded only at the
 * search position, and dropped when the run starts, whenever it resumes from a pause (the
 * tray may have been changed meanwhile), when the model changes, and when a search
 * position is selected by hand.
 *
 * The mm per pixel of camera 1. The Calibration button next to Cam scale (calibration.js)
 * moves the head to known offsets around a part and notes where the part shows up: one
 * sample of pixel radius against mm each. The lens is not linear from the center to the
 * edge, so the samples are fitted as mm = a*r + b*r^3 (the first term of a radial
 * distortion), and the fit converts every pixel offset of camera 1. The samples are the
 * config value cam_scale_samples, saved with the Save button like the rest.
 */

import { L } from './utils/lang.js?v=__V__';
import { sleep } from './utils/helper.js?v=__V__';
import { csa } from './index.js?v=__V__';


// ------------------------------------------------------------ the scale of camera 1

const SCALE_DFT = 10 / 344;     // mm per pixel at the working height, without a calibration
const FRAME_CORNER = 500;       // pixel radius of the corner of the 600 x 800 frame
const CAM1_SIZE = [600, 800];   // width, height of the annotated image of camera 1

let fit = { src: null, n: -1, a: SCALE_DFT, b: 0 };

// mm = a*r + b*r^3, least squares over the samples; a alone until there are enough samples
// far enough out to tell the cubic term, the default when the samples make no sense
function fit_samples(s) {
    let fit = { src: s, n: s.length, a: SCALE_DFT, b: 0 };
    if (s.length < 3)
        return fit;
    let srr = 0, srm = 0, sr4 = 0, sr6 = 0, sr3m = 0, rmax = 0;
    for (let [r, m] of s) {
        let r2 = r * r;
        srr += r2; srm += r * m; sr4 += r2 * r2; sr6 += r2 * r2 * r2; sr3m += r2 * r * m;
        rmax = Math.max(rmax, r);
    }
    let a = srm / srr, b = 0;
    if (s.length >= 8 && rmax >= 150) {
        let det = srr * sr6 - sr4 * sr4;
        if (det > 0) {
            let a2 = (srm * sr6 - sr3m * sr4) / det;
            let b2 = (srr * sr3m - sr4 * srm) / det;
            // the cubic term stays a correction: at most 20% at the corner of the frame
            if (a2 > 0 && Math.abs(b2) * FRAME_CORNER * FRAME_CORNER <= 0.2 * a2) {
                a = a2;
                b = b2;
            }
        }
    }
    if (Math.abs(a / SCALE_DFT - 1) > 0.2)
        return fit;
    fit.a = a;
    fit.b = b;
    return fit;
}

// the fit of the samples in the config, redone only when they change
function scale_fit() {
    let s = csa.cam_scale_samples;
    if (fit.src !== s || fit.n != s.length)
        fit = fit_samples(s);
    return fit;
}

// what a fit says, with how well it explains the samples it was made of
function fit_info(f, s) {
    let max_err = 0;
    for (let [r, m] of s)
        max_err = Math.max(max_err, Math.abs(f.a * r + f.b * r * r * r - m));
    return { a: f.a, b: f.b, samples: s.length, mm_per_pixel: f.a,
             edge_pct: Math.round(f.b * FRAME_CORNER * FRAME_CORNER / f.a * 10000) / 100,  // more (+) or less at the corner
             max_err: Math.round(max_err * 10000) / 10000 };
}

// a pixel offset from the center of camera 1 -> mm
function px2mm(px, py) {
    let f = scale_fit();
    let s = f.a + f.b * (px * px + py * py);
    return [px * s, py * s];
}

function scale_info() {
    return fit_info(scale_fit(), csa.cam_scale_samples);
}

// the info of a sample set that is not (yet) the config's, e.g. a calibration's
function scale_info_of(samples) {
    return fit_info(fit_samples(samples), samples);
}

// replace the samples by a calibration's; the caller marks the config as changed
function scale_set(samples) {
    csa.cam_scale_samples = [...samples];
    scale_show();
    return scale_info();
}

function scale_show() {
    let elem = document.getElementById('cam_scale');
    if (!elem)
        return;
    let i = scale_info();
    let edge = (i.edge_pct >= 0 ? '+' : '') + i.edge_pct.toFixed(2);
    elem.innerText = `${i.a.toFixed(6)} mm/px, ${L('edge')} ${edge}%, ${i.samples} ${L('samples')}`;
}

function scale_reset() {
    csa.cam_scale_samples = [];
    scale_show();
}


// ------------------------------------------------------------ the parts seen at a search position

const SAME_PART_MM = 1.5;       // a snap this close to a candidate is that candidate
const FRAME_HALF_DIAG_MM = 14.5; // of camera 1, to normalize the distance score
const ODD_SIZE_ERR = 0.5;       // a size this far off the reference is counted as odd

// {pos: [x, y] machine coordinates of the camera center over the part, px: [dx, dy] pixel
//  offset in the frame it was seen in, dist: mm from that frame's center, size: [long, short]
//  pixels, angle, state: new | try | snap | picked | lost | fail}
let cands = [];
let cur = null;         // the candidate the run is on
let scan_pos = null;    // where the frame was taken
let ref_size = null;    // size of a part picked with success, the model's true size

function cand_sizes(cv) {
    return cv && cv.length > 5 ? [cv[4], cv[5]] : null;
}

// the size the others are measured against: a picked part, else the median of the list
function size_ref() {
    if (ref_size)
        return ref_size;
    if (!cands.length)
        return null;
    let l = cands.map(c => c.size[0]).sort((a, b) => a - b);
    let s = cands.map(c => c.size[1]).sort((a, b) => a - b);
    return [l[l.length >> 1], s[s.length >> 1]];
}

// relative, with 1 px per side forgiven: the sides are whole pixels and jitter by one
function size_err(c, ref) {
    let dl = Math.max(Math.abs(c.size[0] - ref[0]) - 1, 0);
    let ds = Math.max(Math.abs(c.size[1] - ref[1]) - 1, 0);
    return (dl + ds) / (ref[0] + ref[1]);
}

// lower is better: 1 for the corner of the frame, 4 for a size 100% off
function cand_score(c, ref) {
    return c.dist / FRAME_HALF_DIAG_MM + 4 * (ref ? size_err(c, ref) : 0);
}

// record what camera 1 sees from where the head is now, replacing the list
async function cands_scan(get_cv_comps) {
    cands = [];
    cur = null;
    scan_pos = [csa.cur_pos[0], csa.cur_pos[1]];
    await sleep(600);   // a frame taken after the move settled, as the snap waits
    let ret = await get_cv_comps();
    for (let c of (ret && ret.dev == 1 && ret.comps) || []) {
        let px = [c[0] - CAM1_SIZE[0] / 2, c[1] - CAM1_SIZE[1] / 2];
        let mm = px2mm(px[0], px[1]);
        cands.push({ pos: [scan_pos[0] + mm[0], scan_pos[1] + mm[1]], px: px, dist: Math.hypot(mm[0], mm[1]),
                     size: cand_sizes(c) || [0, 0], angle: c[2], state: 'new' });
    }
    console.log(`cands scan at ${scan_pos}: ${cands.length} found`, cands);
    cands_show();
    return cands.length;
}

// the best candidate not tried yet, now the one the run is on, or null
function cands_next() {
    let ref = size_ref();
    let best = null, best_score = Infinity;
    for (let c of cands) {
        if (c.state != 'new')
            continue;
        let score = cand_score(c, ref);
        if (score < best_score) {
            best = c;
            best_score = score;
        }
    }
    cur = best;
    if (best) {
        best.state = 'try';
        console.log(`cands next: score ${best_score.toFixed(2)}`, best);
    }
    cands_show();
    return best;
}

function cands_cur() {
    return cur;
}

// the snap centered the camera at pos: that is the part the run is on, whichever candidate it was
function cands_snapped(pos) {
    let near = null, near_d = SAME_PART_MM;
    for (let c of cands) {
        if (c.state != 'new' && c.state != 'try')
            continue;
        let d = Math.hypot(c.pos[0] - pos[0], c.pos[1] - pos[1]);
        if (d < near_d) {
            near = c;
            near_d = d;
        }
    }
    if (near && near !== cur) {
        if (cur)
            cur.state = 'lost';
        cur = near;
    }
    if (cur)
        cur.state = 'snap';
    cands_show();
}

function cands_lost() {
    if (cur)
        cur.state = 'lost';
    cur = null;
    cands_show();
}

function cands_fail() {
    if (cur)
        cur.state = 'fail';
    cur = null;
    cands_show();
}

// picked with success: its size, as the snap saw it last, is what the model really looks like
function cands_picked(size) {
    if (cur)
        cur.state = 'picked';
    cur = null;
    if (size)
        ref_size = size;
    cands_show();
}

function cands_clear() {
    cands = [];
    cur = null;
    scan_pos = null;
    cands_show();
}

// a new footprint: the size of the old one says nothing about it
function cands_reset_ref() {
    ref_size = null;
    cands_show();
}

function cands_state() {
    let ref = size_ref();
    let n = { total: cands.length, new: 0, picked: 0, lost: 0, fail: 0, odd: 0 };
    for (let c of cands) {
        if (c.state in n)
            n[c.state]++;
        if (ref && size_err(c, ref) > ODD_SIZE_ERR)
            n.odd++;
    }
    return { ...n, ref_size: ref, ref_from_pick: !!ref_size, scan_pos: scan_pos,
             list: cands.map(c => ({ pos: [Math.round(c.pos[0] * 1000) / 1000, Math.round(c.pos[1] * 1000) / 1000],
                                     size: c.size, angle: c.angle, state: c.state,
                                     score: ref ? Math.round(cand_score(c, ref) * 100) / 100 : null })) };
}

// the frame as seen at the search position, in small: a dot per part, colored by its state,
// the center cross of the frame, and where the camera center is now (updated with every move)
const CAND_COLORS = { new: '#3273dc', try: '#ff9800', snap: '#ff9800', picked: '#23d160', lost: '#b5b5b5', fail: '#ff3860' };

function cands_draw() {
    let cv = document.getElementById('cand_map');
    if (!cv)
        return;
    if (!cands.length) {
        cv.style.display = 'none';
        return;
    }
    cv.style.display = '';
    let ctx = cv.getContext('2d');
    let W = cv.width, H = cv.height, k = W / CAM1_SIZE[0];   // canvas px per frame px
    ctx.clearRect(0, 0, W, H);
    ctx.lineWidth = 1;
    ctx.strokeStyle = '#8c8';
    ctx.beginPath();
    ctx.moveTo(W/2 - 8, H/2); ctx.lineTo(W/2 + 8, H/2);
    ctx.moveTo(W/2, H/2 - 8); ctx.lineTo(W/2, H/2 + 8);
    ctx.stroke();
    for (let c of cands) {
        let x = W/2 + c.px[0] * k, y = H/2 + c.px[1] * k;
        ctx.fillStyle = CAND_COLORS[c.state] || '#000';
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, 2 * Math.PI);
        ctx.fill();
        if (c === cur) {
            ctx.strokeStyle = CAND_COLORS[c.state];
            ctx.beginPath();
            ctx.arc(x, y, 8, 0, 2 * Math.PI);
            ctx.stroke();
        }
    }
    if (scan_pos) {   // the camera center now, in the pixels of that frame (the center scale is near enough)
        let a = scale_fit().a;
        let x = W/2 + (csa.cur_pos[0] - scan_pos[0]) / a * k, y = H/2 + (csa.cur_pos[1] - scan_pos[1]) / a * k;
        if (x >= -6 && x <= W + 6 && y >= -6 && y <= H + 6) {
            ctx.strokeStyle = '#000';
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(x - 7, y); ctx.lineTo(x + 7, y);
            ctx.moveTo(x, y - 7); ctx.lineTo(x, y + 7);
            ctx.stroke();
        }
    }
}

function cands_show() {
    cands_draw();
    let elem = document.getElementById('cand_state');
    if (!elem)
        return;
    if (!cands.length) {
        elem.innerText = '--';
        return;
    }
    let n = cands_state();
    let parts = [`${n.total} ${L('found')}`, `${n.new} ${L('left')}`, `${n.picked} ${L('picked')}`];
    if (n.lost)
        parts.push(`${n.lost} ${L('lost')}`);
    if (n.fail)
        parts.push(`${n.fail} ${L('fail')}`);
    if (n.odd)
        parts.push(`${n.odd} ${L('odd size')}`);
    let ref = n.ref_size ? ` | ${L('ref size')}: ${n.ref_size[0]} x ${n.ref_size[1]} px${n.ref_from_pick ? '' : ' (' + L('median') + ')'}` : '';
    elem.innerText = parts.join(', ') + ref;
}


export {
    px2mm, scale_info, scale_info_of, scale_set, scale_show, scale_reset,
    cands_scan, cands_next, cands_cur, cands_snapped, cands_lost, cands_fail, cands_picked, cands_clear, cands_reset_ref,
    cands_state, cands_show, cands_draw, cand_sizes
};
