/*
 * Software License Agreement (MIT License)
 *
 * Author: Duke Fong <d@d-l.io>
 */

// Least squares affine from pcb to machine, n >= 3 points: null below that, {n, collinear: true}
// when they are about on a line (the same limit as pnp_main.py).
// skew: deg away from 90 between the X and Y motions, scale_diff: X vs Y in %, max_err: mm
function fid_fit(pcb, cam) {
    let n = Math.min(pcb.length, cam.length);
    if (n < 3)
        return null;
    let mean = (l, i) => l.slice(0, n).reduce((s, p) => s + p[i], 0) / n;
    let [px, py, cx, cy] = [mean(pcb, 0), mean(pcb, 1), mean(cam, 0), mean(cam, 1)];
    let [sxx, sxy, syy, sxu, syu, sxv, syv] = [0, 0, 0, 0, 0, 0, 0];
    for (let i = 0; i < n; i++) {
        let [x, y, u, v] = [pcb[i][0] - px, pcb[i][1] - py, cam[i][0] - cx, cam[i][1] - cy];
        sxx += x * x; sxy += x * y; syy += y * y;
        sxu += x * u; syu += y * u; sxv += x * v; syv += y * v;
    }
    let det = sxx * syy - sxy * sxy;
    let l1 = (sxx + syy + Math.hypot(sxx - syy, 2 * sxy)) / 2;
    if (!(det / l1 >= l1 * 0.0025))
        return { n, collinear: true };
    let a = (sxu * syy - syu * sxy) / det, b = (sxx * syu - sxy * sxu) / det;
    let c = (sxv * syy - syv * sxy) / det, d = (sxx * syv - sxy * sxv) / det;
    let max_err = 0;
    for (let i = 0; i < n; i++) {
        let [x, y] = [pcb[i][0] - px, pcb[i][1] - py];
        max_err = Math.max(max_err, Math.hypot(a * x + b * y - (cam[i][0] - cx), c * x + d * y - (cam[i][1] - cy)));
    }
    let [g00, g11, g01] = [a * a + b * b, c * c + d * d, a * c + b * d];
    let tr = g00 + g11;
    return { n, collinear: false, A: [[a, b], [c, d]], skew: 2 * g01 / tr * 180 / Math.PI,
             scale_diff: (g00 - g11) / tr * 100, scale: Math.sqrt(Math.abs(a * d - b * c)), max_err };
}

export { fid_fit };
