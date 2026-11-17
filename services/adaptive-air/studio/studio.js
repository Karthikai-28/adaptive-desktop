'use strict';
// Kinect Studio: the page. Served by services/adaptive-air/kinect_hub.py on 127.0.0.1:8792.
//
// Each view asks the hub for the frame after the one it last drew (/frame/<kind>.jpg?after=seq),
// so a view runs as fast as the Kinect and the page can, never faster. The point cloud is binary
// (/cloud.bin: u32 count, u32 seq, float32 xyz * n, uint8 rgb * n) drawn as WebGL points.
// Colours come from the stylesheet's custom properties (no colour is written here).

const $ = id => document.getElementById(id);
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function rgbOf(name) {
    const probe = document.createElement('i');
    probe.style.color = css(name);
    document.body.appendChild(probe);
    const m = getComputedStyle(probe).color.match(/[\d.]+/g).map(Number);
    probe.remove();
    return [m[0] / 255, m[1] / 255, m[2] / 255];
}
const post = (name, value) => fetch(`/api/${name}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }),
}).catch(() => {});

let status = null;
let visible = !document.hidden;
document.addEventListener('visibilitychange', () => { visible = !document.hidden; });

// The hub stays up while this page is open (and stops itself a little after it closes).
function presence() {
    const ws = new WebSocket(`ws://${location.host}/presence`);
    ws.onclose = () => setTimeout(presence, 2000);
}
presence();

// ------------------------------------------------------------------ camera views

function streamView(kind, canvas, meta) {
    const ctx = canvas.getContext('2d');
    let seq = 0, count = 0, since = performance.now();
    async function loop() {
        while (true) {
            if (!visible) { await new Promise(r => setTimeout(r, 300)); continue; }
            try {
                const res = await fetch(`/frame/${kind}.jpg?after=${seq}`, { cache: 'no-store' });
                if (res.status !== 200) { await new Promise(r => setTimeout(r, 500)); continue; }
                seq = Number(res.headers.get('X-Seq')) || seq;
                const bitmap = await createImageBitmap(await res.blob());
                ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
                bitmap.close();
                count++;
                const now = performance.now();
                if (now - since > 1000) {
                    meta.textContent = `${(count * 1000 / (now - since)).toFixed(0)} fps · 640×480`;
                    count = 0; since = now;
                }
            } catch (e) {
                await new Promise(r => setTimeout(r, 1000));
            }
        }
    }
    loop();
}
streamView('video', $('video'), $('video-meta'));
streamView('depth', $('depth'), $('depth-meta'));

// ------------------------------------------------------------------ point cloud (WebGL)

const cloud = (() => {
    const canvas = $('cloud');
    const gl = canvas.getContext('webgl', { antialias: true });
    if (!gl) {
        $('cloud-meta').textContent = 'WebGL is not available here';
        return null;
    }
    const vs = `
        attribute vec3 pos; attribute vec3 col;
        uniform mat4 mvp; uniform float size; uniform int byDepth;
        uniform vec3 nearC; uniform vec3 midC; uniform vec3 farC;
        varying vec3 v;
        void main() {
            gl_Position = mvp * vec4(pos.x, -pos.y, -pos.z, 1.0);
            gl_PointSize = size;
            if (byDepth == 1) {
                float t = clamp((pos.z - 0.4) / 3.6, 0.0, 1.0);
                v = t < 0.5 ? mix(nearC, midC, t * 2.0) : mix(midC, farC, t * 2.0 - 1.0);
            } else {
                v = col;
            }
        }`;
    const fs = `precision mediump float; varying vec3 v;
        void main() { vec2 c = gl_PointCoord - 0.5; if (dot(c, c) > 0.25) discard; gl_FragColor = vec4(v, 1.0); }`;
    const shader = (type, src) => {
        const s = gl.createShader(type);
        gl.shaderSource(s, src);
        gl.compileShader(s);
        return s;
    };
    const prog = gl.createProgram();
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, vs));
    gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(prog);
    gl.useProgram(prog);
    const loc = name => gl.getUniformLocation(prog, name);
    const posBuf = gl.createBuffer(), colBuf = gl.createBuffer();
    const aPos = gl.getAttribLocation(prog, 'pos'), aCol = gl.getAttribLocation(prog, 'col');
    gl.uniform3fv(loc('nearC'), rgbOf('--warn'));
    gl.uniform3fv(loc('midC'), rgbOf('--cyan'));
    gl.uniform3fv(loc('farC'), rgbOf('--indigo'));
    gl.enable(gl.DEPTH_TEST);
    const ground = rgbOf('--ground');

    const view = { yaw: 0, pitch: 0, dist: 0.1, tx: 0, ty: 0, tz: -1.6, spin: false };
    const reset = () => Object.assign(view, { yaw: 0, pitch: 0, dist: 0.1, tx: 0, ty: 0, tz: -1.6 });
    let n = 0, seq = 0, byDepth = 0, size = 2, step = 4, last = performance.now();

    function perspective(fovy, aspect, near, far) {
        const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
        return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
    }
    function mul(a, b) {
        const o = new Array(16).fill(0);
        for (let i = 0; i < 4; i++)
            for (let j = 0; j < 4; j++)
                for (let k = 0; k < 4; k++) o[j * 4 + i] += a[k * 4 + i] * b[j * 4 + k];
        return o;
    }
    const translate = (x, y, z) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1];
    const rotX = a => [1, 0, 0, 0, 0, Math.cos(a), Math.sin(a), 0, 0, -Math.sin(a), Math.cos(a), 0, 0, 0, 0, 1];
    const rotY = a => [Math.cos(a), 0, -Math.sin(a), 0, 0, 1, 0, 0, Math.sin(a), 0, Math.cos(a), 0, 0, 0, 0, 1];

    function draw() {
        const dpr = window.devicePixelRatio || 1;
        const w = Math.round(canvas.clientWidth * dpr), h = Math.round(canvas.clientHeight * dpr);
        if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
        gl.viewport(0, 0, w, h);
        gl.clearColor(ground[0], ground[1], ground[2], 1);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        const now = performance.now();
        if (view.spin) view.yaw += (now - last) / 1000 * 0.4;
        last = now;
        // Orbit around a point 1.6 m in front of the Kinect.
        let m = translate(view.tx, view.ty, -view.dist - 1.6);
        m = mul(m, rotX(view.pitch));
        m = mul(m, rotY(view.yaw));
        m = mul(m, translate(0, 0, 1.6));
        const mvp = mul(perspective(0.9, w / Math.max(1, h), 0.05, 20), m);
        gl.uniformMatrix4fv(loc('mvp'), false, new Float32Array(mvp));
        gl.uniform1f(loc('size'), size * dpr);
        gl.uniform1i(loc('byDepth'), byDepth);
        if (n) gl.drawArrays(gl.POINTS, 0, n);
        requestAnimationFrame(draw);
    }

    async function fetchLoop() {
        let count = 0, since = performance.now();
        while (true) {
            if (!visible) { await new Promise(r => setTimeout(r, 300)); continue; }
            try {
                const res = await fetch(`/cloud.bin?step=${step}&after=${seq}`, { cache: 'no-store' });
                if (res.status !== 200) { await new Promise(r => setTimeout(r, 500)); continue; }
                const buf = await res.arrayBuffer();
                const head = new Uint32Array(buf, 0, 2);
                const count0 = head[0];
                seq = head[1];
                const xyz = new Float32Array(buf, 8, count0 * 3);
                const rgb = new Uint8Array(buf, 8 + count0 * 12, count0 * 3);
                gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
                gl.bufferData(gl.ARRAY_BUFFER, xyz, gl.DYNAMIC_DRAW);
                gl.enableVertexAttribArray(aPos);
                gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0);
                gl.bindBuffer(gl.ARRAY_BUFFER, colBuf);
                gl.bufferData(gl.ARRAY_BUFFER, rgb, gl.DYNAMIC_DRAW);
                gl.enableVertexAttribArray(aCol);
                gl.vertexAttribPointer(aCol, 3, gl.UNSIGNED_BYTE, true, 0, 0);
                n = count0;
                count++;
                const now = performance.now();
                if (now - since > 1000) {
                    $('cloud-meta').textContent = `${n.toLocaleString()} points · ${(count * 1000 / (now - since)).toFixed(0)} fps`;
                    count = 0; since = now;
                }
            } catch (e) {
                await new Promise(r => setTimeout(r, 1000));
            }
        }
    }

    // Mouse: drag turns, right-drag / shift-drag moves, wheel zooms.
    let drag = null;
    canvas.addEventListener('contextmenu', e => e.preventDefault());
    canvas.addEventListener('pointerdown', e => {
        drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey };
        canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener('pointermove', e => {
        if (!drag) return;
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        drag.x = e.clientX; drag.y = e.clientY;
        if (drag.pan) {
            view.tx += dx * 0.003 * (1 + view.dist);
            view.ty -= dy * 0.003 * (1 + view.dist);
        } else {
            view.yaw += dx * 0.008;
            view.pitch = Math.max(-1.5, Math.min(1.5, view.pitch + dy * 0.008));
        }
    });
    canvas.addEventListener('pointerup', () => { drag = null; });
    canvas.addEventListener('wheel', e => {
        e.preventDefault();
        view.dist = Math.max(-1.4, Math.min(8, view.dist + e.deltaY * 0.002));
    }, { passive: false });

    requestAnimationFrame(draw);
    fetchLoop();
    return {
        setColour: v => { byDepth = v === 'depth' ? 1 : 0; },
        setSize: v => { size = v; },
        setStep: v => { step = v; },
        toggleSpin: () => (view.spin = !view.spin),
        reset,
    };
})();

document.querySelectorAll('[data-colour]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-colour]').forEach(x => x.classList.toggle('on', x === b));
    if (cloud) cloud.setColour(b.dataset.colour);
}));
$('size').addEventListener('input', e => cloud && cloud.setSize(Number(e.target.value)));
$('step').addEventListener('change', e => cloud && cloud.setStep(Number(e.target.value)));
$('spin').addEventListener('click', e => cloud && e.target.classList.toggle('on', cloud.toggleSpin()));
$('reset').addEventListener('click', () => cloud && cloud.reset());

// ------------------------------------------------------------------ controls

document.querySelectorAll('[data-video]').forEach(b => b.addEventListener('click', () => post('video', b.dataset.video)));
document.querySelectorAll('[data-led]').forEach(b => b.addEventListener('click', () => post('led', b.dataset.led)));
document.querySelectorAll('[data-tilt]').forEach(b => b.addEventListener('click', () => {
    $('tilt-set').value = b.dataset.tilt;
    post('tilt', Number(b.dataset.tilt));
}));
$('tilt-set').addEventListener('change', e => post('tilt', Number(e.target.value)));
$('webcam').addEventListener('change', e => post('webcam', e.target.checked));

// ------------------------------------------------------------------ people (over the camera view)
//
// /api/people (long poll, ?after=seq) is everyone in view, from the hub's people.py: posture,
// whether they stand straight, their height in cm once it has held for a second, a silhouette
// (64 points from the top of the head round), the skeleton, the head and the floor point under it
// (the ruler) and a ring on the floor. Each person glides from one answer to the next here at
// the screen's rate; nothing is drawn from a guess.

const SKELETON = [[11, 12], [11, 23], [12, 24], [23, 24], [11, 13], [13, 15], [12, 14], [14, 16],
    [23, 25], [25, 27], [24, 26], [26, 28], [27, 31], [28, 32], [0, 11], [0, 12]];
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const easeOut = t => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
const sleep = ms => new Promise(r => setTimeout(r, ms));

const people = (() => {
    const video = $('video'), canvas = $('overlay'), ctx = canvas.getContext('2d');
    const palette = [1, 2, 3, 4, 5, 6].map(i => css(`--p${i}`));
    const warn = css('--warn'), warnText = css('--warn-text'), okC = css('--ok'), white = css('--white');
    const black = css('--black'), pane = css('--pane'), text = css('--text'), muted = css('--muted');
    let on = true;
    try { on = localStorage.getItem('studio.people') !== 'off'; } catch (e) { /* private window */ }
    let seq = 0, state = null, lastCount = -1, lastT = performance.now();
    const shown = new Map();            // id -> what is on screen now, gliding towards the latest
    const colour = p => palette[p.colour % palette.length];

    // ---- following the hub
    async function poll() {
        while (true) {
            if (!on || !visible) { await sleep(300); continue; }
            try {
                const res = await fetch(`/api/people?after=${seq}`, { cache: 'no-store' });
                const s = await res.json();
                seq = s.seq || seq;
                take(s);
            } catch (e) {
                await sleep(1000);
            }
        }
    }

    const copy = v => JSON.parse(JSON.stringify(v));
    function take(s) {
        state = s;
        const now = performance.now(), ids = new Set();
        for (const p of s.people || []) {
            ids.add(p.id);
            let d = shown.get(p.id);
            if (!d) {
                d = { born: now, gone: null, cur: copy(p), grow: 0, measuring: 0, lockedAt: null, from: 0 };
                shown.set(p.id, d);
            }
            d.gone = null;
            if (p.height_cm != null && (d.p == null || d.p.height_cm == null)) {
                d.lockedAt = now;
                d.from = d.p ? Math.min(d.p.live_cm, p.height_cm) * 0.6 : 0;
            }
            if (p.height_cm == null) d.lockedAt = null;
            d.p = p;
        }
        for (const d of shown.values()) if (!ids.has(d.p.id) && d.gone == null) d.gone = now;
        sidebar(s);
    }

    // ---- the words around the picture
    function sidebar(s) {
        const crowd = s.people || [];
        const n = crowd.length, standing = s.standing || 0;
        const measured = crowd.filter(p => p.height_cm != null).length;
        $('people-count').hidden = !on;
        if (n !== lastCount) {
            const b = $('count-n');
            b.textContent = n;
            b.classList.remove('bump'); void b.offsetWidth; b.classList.add('bump');
            lastCount = n;
        }
        $('count-text').textContent = `${n === 1 ? 'person' : 'people'} · ${standing} standing` +
            (measured ? ` · ${measured} measured` : '');
        const banner = $('banner');
        let msg = null, kind = '';
        if (s.error) { msg = s.error; kind = 'ask'; }
        else if (s.running === false) msg = null;
        else if (!n) msg = 'Step in front of the Kinect: 2 to 4 m away, all of you in view';
        else if (measured === n) { msg = n === 1 ? 'Measured' : `Everyone measured`; kind = 'done'; }
        else {
            const waiting = crowd.filter(p => p.height_cm == null);
            const one = waiting.length === 1 ? waiting[0] : null;
            if (n === 1) msg = one.posture === 'standing' ? `${one.hint}, facing the Kinect`
                : 'Please stand up straight, facing the Kinect, arms down';
            else if (one) msg = `Person ${one.id}: ${one.posture === 'standing' ? one.hint.toLowerCase() : 'please stand up straight'}, facing the Kinect`;
            else if (waiting.length === n) msg = 'Everyone: stand up straight, facing the Kinect, arms down';
            else msg = `People ${waiting.map(p => p.id).join(', ').replace(/, (\d+)$/, ' and $1')}: stand up straight, facing the Kinect`;
            kind = 'ask';
        }
        if (banner.textContent !== (msg || '') || banner.className !== `banner ${kind}`) {
            banner.textContent = msg || '';
            banner.className = `banner ${kind}`;
        }
        banner.hidden = !msg || !on;
        // The list: one row per person, kept (and only its words changed) while they stay in view.
        const list = $('people-list');
        const rows = new Map([...list.querySelectorAll('li[data-id]')].map(li => [Number(li.dataset.id), li]));
        list.querySelectorAll('li.empty').forEach(li => li.remove());
        for (const p of crowd) {
            let li = rows.get(p.id);
            if (!li) {
                li = document.createElement('li');
                li.dataset.id = p.id;
                li.innerHTML = '<span class="tag"></span><div class="what"><strong></strong><span></span></div><b></b>';
                list.append(li);
            }
            rows.delete(p.id);
            const tag = li.querySelector('.tag');
            tag.style.background = colour(p); tag.textContent = p.id;
            li.querySelector('strong').textContent = p.label;
            const sub = li.querySelector('.what span');
            sub.textContent = p.height_cm != null ? (p.distance != null ? `${p.distance.toFixed(1)} m away` : '') : p.hint;
            sub.className = p.height_cm != null ? '' : 'ask';
            const h = li.querySelector('b');
            const want = p.height_cm != null ? `${p.height_cm}` : '–';
            if (h.dataset.v !== want) {
                h.dataset.v = want;
                h.textContent = want;
                if (p.height_cm != null) { const u = document.createElement('small'); u.textContent = 'cm'; h.append(u); }
            }
        }
        for (const li of rows.values()) li.remove();
        if (!n) {
            const li = document.createElement('li');
            li.className = 'empty';
            li.textContent = on ? 'Nobody in view.' : 'People is off.';
            list.append(li);
        }
        $('you-meta').textContent = s.floor ? `floor ${s.floor.seen ? 'seen' : 'assumed'} · Kinect ${s.floor.camera_height.toFixed(2)} m up` : '';
    }

    // ---- gliding
    const lerp = (a, b, k) => a + (b - a) * k;
    function glidePts(cur, tgt, k) {
        if (!tgt || !tgt.length) return tgt;
        if (!cur || cur.length !== tgt.length) return copy(tgt);
        return cur.map((c, i) => c.map((v, j) => lerp(v, tgt[i][j], k)));
    }
    function glide(d, dt) {
        const k = 1 - Math.exp(-dt * 14), c = d.cur, t = d.p;
        c.outline = glidePts(c.outline, t.outline, k);
        c.skeleton = glidePts(c.skeleton, t.skeleton, k);
        c.ring = glidePts(c.ring, t.ring, k);
        c.box = glidePts([c.box], [t.box], k)[0];
        c.head = t.head && c.head ? glidePts([c.head], [t.head], k)[0] : t.head;
        c.foot = t.foot && c.foot ? glidePts([c.foot], [t.foot], k)[0] : t.foot;
        d.measuring = lerp(d.measuring, t.measuring || 0, 1 - Math.exp(-dt * 6));
    }

    // ---- drawing
    function fit() {
        const dpr = window.devicePixelRatio || 1;
        const w = video.clientWidth, h = video.clientHeight;
        if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
            canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
        }
        const size = (state && state.size) || [640, 480];
        const s = Math.min(w / size[0], h / size[1]);           // the picture is letterboxed (contain)
        return { dpr, s, ox: (w - size[0] * s) / 2, oy: (h - size[1] * s) / 2, w, h };
    }

    function path(points, r) {
        ctx.beginPath();
        points.forEach(([x, y], i) => (i ? ctx.lineTo : ctx.moveTo).call(ctx, r.ox + x * r.s, r.oy + y * r.s));
        ctx.closePath();
    }

    const FONT_BIG = '700 20px Inter, Cantarell, system-ui, sans-serif';
    const FONT_SMALL = '600 11px Inter, Cantarell, system-ui, sans-serif';
    function pillSize(lines) {
        ctx.font = FONT_BIG;
        const w1 = ctx.measureText(lines[0]).width;
        ctx.font = FONT_SMALL;
        const w2 = lines[1] ? ctx.measureText(lines[1]).width : 0;
        return [Math.max(w1, w2) + 52, lines[1] ? 46 : 32];
    }

    // Labels never cover each other: each sits over its person's head, and one that would land
    // on another is lifted above it (or put under it at the top of the picture).
    function layout(labels, r, dt) {
        const placed = [];
        const top = r.oy + 4, right = r.ox + 640 * r.s - 4;
        labels.sort((a, b) => a.ay - b.ay || a.ax - b.ax);
        for (const L of labels) {
            const [w, h] = pillSize(L.lines);
            const x = Math.min(Math.max(L.ax - w / 2, r.ox + 4), right - w);
            let y = Math.max(L.ay - h - 16, top);
            for (let pass = 0; pass < placed.length + 1; pass++) {
                const hit = placed.find(P => x < P.x + P.w + 6 && P.x < x + w + 6 && y < P.y + P.h + 6 && P.y < y + h + 6);
                if (!hit) break;
                y = hit.y - h - 6 >= top ? hit.y - h - 6 : hit.y + hit.h + 6;
            }
            placed.push({ x, y, w, h });
            const d = L.d, k = 1 - Math.exp(-dt * 10);
            d.lx = d.lx == null ? x : d.lx + (x - d.lx) * k;
            d.ly = d.ly == null ? y : d.ly + (y - d.ly) * k;
            pill(d.lx, d.ly, w, h, L);
        }
    }

    function pill(px, py, w, h, { lines, c, ask, scale, alpha, ax, ay }) {
        ctx.save();
        ctx.globalAlpha = alpha;
        // a thin lead from the label down to the head, when the label had to move away
        if (Math.abs(py + h - (ay - 16)) > 8) {
            ctx.strokeStyle = c; ctx.lineWidth = 1.5; ctx.globalAlpha = alpha * 0.7;
            ctx.beginPath(); ctx.moveTo(Math.min(Math.max(ax, px + 14), px + w - 14), py + h); ctx.lineTo(ax, ay - 4); ctx.stroke();
            ctx.globalAlpha = alpha;
        }
        ctx.translate(px + w / 2, py + h / 2);
        ctx.scale(scale, scale);
        ctx.translate(-w / 2, -h / 2);
        ctx.shadowColor = black; ctx.shadowBlur = 18;
        ctx.fillStyle = pane; ctx.globalAlpha = alpha * 0.88;
        ctx.beginPath(); if (ctx.roundRect) ctx.roundRect(0, 0, w, h, 14); else ctx.rect(0, 0, w, h); ctx.fill();
        ctx.shadowBlur = 0; ctx.globalAlpha = alpha;
        ctx.lineWidth = 1.5; ctx.strokeStyle = ask ? warn : c; ctx.stroke();
        // the person's number in their colour
        ctx.fillStyle = c; ctx.beginPath(); ctx.arc(19, h / 2, 10, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = black; ctx.font = '700 11px Inter, Cantarell, system-ui, sans-serif';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(lines[2], 19, h / 2 + 0.5);
        ctx.textAlign = 'left';
        ctx.font = FONT_BIG;
        ctx.fillStyle = ask ? warnText : text;
        ctx.fillText(lines[0], 38, lines[1] ? 17 : h / 2 + 1);
        if (lines[1]) {
            ctx.font = FONT_SMALL;
            ctx.fillStyle = ask ? warnText : muted;
            ctx.fillText(lines[1], 38, 35);
        }
        ctx.restore();
    }

    function ruler(d, c, alpha, now, r) {
        const { head, foot, box } = d.cur, p = d.p;
        if (!head || !foot) return;
        const cm = p.height_cm != null ? p.height_cm : p.live_cm;
        let g = p.height_cm != null ? easeOut((now - (d.lockedAt || 0)) / 800) : d.measuring;
        if (g <= 0.01) return;
        const right = r.ox + (box[2] + 14) * r.s, left = r.ox + (box[0] - 14) * r.s;
        const x = right + 40 < r.ox + 640 * r.s ? right : left;
        const hx = r.ox + head[0] * r.s, hy = r.oy + head[1] * r.s;
        const fy = r.oy + foot[1] * r.s, fx = r.ox + foot[0] * r.s;
        const topY = fy + (hy - fy) * g;
        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = c; ctx.fillStyle = c; ctx.lineWidth = 2;
        ctx.shadowColor = c; ctx.shadowBlur = 8;
        ctx.beginPath(); ctx.moveTo(x, fy); ctx.lineTo(x, topY); ctx.stroke();
        ctx.shadowBlur = 0;
        ctx.font = '600 10px Inter, Cantarell, system-ui, sans-serif';
        ctx.textBaseline = 'middle';
        ctx.textAlign = x === right ? 'left' : 'right';
        for (let k = 10; k < cm; k += 10) {
            const y = fy + (hy - fy) * (k / cm);
            if (y < topY) break;
            const big = k % 50 === 0;
            ctx.globalAlpha = alpha * (big ? 1 : 0.7);
            ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + (x === right ? 1 : -1) * (big ? 9 : 5), y); ctx.stroke();
            if (big && r.s > 0.8) ctx.fillText(k, x + (x === right ? 12 : -12), y);
        }
        ctx.globalAlpha = alpha;
        // the foot of the ruler on the floor, the top level with the head
        ctx.beginPath(); ctx.moveTo(fx, fy); ctx.lineTo(x, fy); ctx.setLineDash([3, 4]); ctx.stroke();
        if (g > 0.98) { ctx.beginPath(); ctx.moveTo(hx, hy); ctx.lineTo(x, hy); ctx.stroke(); }
        ctx.setLineDash([]);
        ctx.beginPath(); ctx.moveTo(x - 6, topY); ctx.lineTo(x + 6, topY); ctx.lineWidth = 3; ctx.stroke();
        ctx.restore();
    }

    function drawPerson(d, now, r) {
        const p = d.p, c = colour(p), cur = d.cur;
        const appear = easeOut((now - d.born) / 550);
        const alpha = d.gone != null ? 1 - (now - d.gone) / 450 : 1;
        if (alpha <= 0) return null;
        const ask = p.height_cm == null && !p.straight;
        const measuring = p.straight && p.height_cm == null;
        const locked = d.lockedAt != null ? (now - d.lockedAt) : null;

        // the ring on the floor, turning
        if (cur.ring && cur.ring.length > 2) {
            ctx.save();
            ctx.globalAlpha = alpha * appear;
            path(cur.ring, r);
            ctx.fillStyle = c; ctx.globalAlpha = alpha * appear * 0.14; ctx.fill();
            ctx.globalAlpha = alpha * appear * 0.9;
            ctx.strokeStyle = ask ? warn : c; ctx.lineWidth = 2;
            ctx.setLineDash([10, 7]);
            ctx.lineDashOffset = reduceMotion ? 0 : -now / 45;
            ctx.stroke();
            ctx.restore();
        }

        // the silhouette: tinted, its outline drawn on as they appear, glowing
        if (cur.outline && cur.outline.length > 3) {
            ctx.save();
            path(cur.outline, r);
            ctx.globalAlpha = alpha * appear * (ask ? 0.12 : 0.18);
            ctx.fillStyle = c; ctx.fill();
            ctx.globalAlpha = alpha;
            ctx.lineWidth = 2.5; ctx.lineJoin = 'round';
            ctx.strokeStyle = c; ctx.shadowColor = c; ctx.shadowBlur = 14;
            if (appear < 1) { ctx.setLineDash([appear * 4000, 4000]); }
            else if (ask && !reduceMotion) { ctx.globalAlpha = alpha * (0.65 + 0.35 * Math.sin(now / 260)); }
            ctx.stroke();
            ctx.restore();

            // the scan: a band sweeping from the feet to the head while measuring
            if (measuring && cur.head && cur.foot && !reduceMotion) {
                const fy = r.oy + cur.foot[1] * r.s, hy = r.oy + cur.head[1] * r.s;
                const phase = (now / 1100) % 1, y = fy + (hy - fy) * phase;
                ctx.save();
                path(cur.outline, r); ctx.clip();
                const band = ctx.createLinearGradient(0, y - 22, 0, y + 22);
                band.addColorStop(0, 'transparent'); band.addColorStop(0.5, c); band.addColorStop(1, 'transparent');
                ctx.globalAlpha = alpha * 0.55; ctx.fillStyle = band;
                ctx.fillRect(r.ox, y - 22, 640 * r.s, 44);
                ctx.globalAlpha = alpha; ctx.fillStyle = white;
                ctx.fillRect(r.ox, y - 0.75, 640 * r.s, 1.5);
                ctx.restore();
            }
        }

        // the skeleton
        if (cur.skeleton) {
            ctx.save();
            ctx.globalAlpha = alpha * appear * 0.75;
            ctx.strokeStyle = c; ctx.lineWidth = 2; ctx.lineCap = 'round';
            const pt = i => [r.ox + cur.skeleton[i][0] * 640 * r.s, r.oy + cur.skeleton[i][1] * 480 * r.s];
            ctx.beginPath();
            for (const [a, b] of SKELETON) {
                if (cur.skeleton[a][2] < 0.5 || cur.skeleton[b][2] < 0.5) continue;
                const A = pt(a), B = pt(b);
                ctx.moveTo(A[0], A[1]); ctx.lineTo(B[0], B[1]);
            }
            ctx.stroke();
            ctx.fillStyle = white;
            for (const i of [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]) {
                if (cur.skeleton[i][2] < 0.5) continue;
                const A = pt(i);
                ctx.beginPath(); ctx.arc(A[0], A[1], 2.6, 0, Math.PI * 2); ctx.fill();
            }
            ctx.restore();
        }

        ruler(d, c, alpha * appear, now, r);

        // the moment a height locks: rings from the head, and the label pops
        if (locked != null && locked < 1000 && cur.head) {
            const hx = r.ox + cur.head[0] * r.s, hy = r.oy + cur.head[1] * r.s;
            ctx.save();
            for (const lag of [0, 180]) {
                const t = (locked - lag) / 800;
                if (t <= 0 || t >= 1) continue;
                ctx.globalAlpha = alpha * (1 - t);
                ctx.strokeStyle = okC; ctx.lineWidth = 3 * (1 - t) + 1;
                ctx.beginPath(); ctx.arc(hx, hy, 8 + easeOut(t) * 70, 0, Math.PI * 2); ctx.stroke();
            }
            ctx.restore();
        }

        // the label over the head
        const anchor = cur.head || [cur.box[0] / 2 + cur.box[2] / 2, cur.box[1]];
        const ax = r.ox + anchor[0] * r.s, ay = r.oy + Math.min(anchor[1], cur.box[1]) * r.s;
        let lines;
        if (p.height_cm != null) {
            const t = locked != null ? easeOut(locked / 900) : 1;
            const shown = Math.round(d.from + (p.height_cm - d.from) * t);
            lines = [`${shown} cm`, p.posture === 'standing' ? (p.straight ? 'Standing straight ✓' : p.hint)
                : `${p.label} · measured standing`];
        } else if (measuring) {
            lines = [`Measuring ${Math.round(d.measuring * 100)}%`, 'Hold still'];
        } else {
            lines = [p.label, p.hint];
        }
        lines.push(String(p.id));
        const pop = locked != null && locked < 500 ? 1 + 0.14 * Math.sin(Math.PI * locked / 500) : 1;
        return { d, ax, ay, lines, c, ask, scale: pop * (0.85 + 0.15 * appear), alpha: alpha * appear };
    }

    function frame() {
        requestAnimationFrame(frame);
        const now = performance.now(), dt = Math.min(0.1, (now - lastT) / 1000);
        lastT = now;
        const r = fit();
        ctx.setTransform(r.dpr, 0, 0, r.dpr, 0, 0);
        ctx.clearRect(0, 0, r.w, r.h);
        if (!on) return;
        const labels = [];
        for (const [id, d] of shown) {
            glide(d, dt);
            const label = drawPerson(d, now, r);
            if (label) labels.push(label); else shown.delete(id);
        }
        layout(labels, r, dt);              // labels last, over every silhouette
    }

    function toggle(v) {
        on = v;
        try { localStorage.setItem('studio.people', on ? 'on' : 'off'); } catch (e) { /* private window */ }
        $('people-toggle').classList.toggle('on', on);
        if (!on) { shown.clear(); lastCount = -1; }
        sidebar(on && state ? state : { people: [], standing: 0, running: false });
    }
    $('people-toggle').addEventListener('click', () => toggle(!on));
    toggle(on);
    requestAnimationFrame(frame);
    poll();
    return { take };
})();

$('measure').addEventListener('click', async () => {
    $('measure').disabled = true;
    $('you-text').textContent = 'Stand up straight, facing the Kinect, arms down… measuring';
    try {
        const r = await (await fetch('/api/measure', { cache: 'no-store' })).json();
        $('you-text').textContent = r.sentence || r.error || '';
    } catch (e) {
        $('you-text').textContent = 'The Kinect hub did not answer.';
    }
    $('measure').disabled = false;
});

// ------------------------------------------------------------------ sensors

function horizon(pitch, roll) {
    const c = $('horizon'), ctx = c.getContext('2d');
    const s = c.width, r = s / 2 - 6;
    ctx.clearRect(0, 0, s, s);
    ctx.save();
    ctx.translate(s / 2, s / 2);
    ctx.beginPath(); ctx.arc(0, 0, r, 0, 2 * Math.PI); ctx.clip();
    ctx.fillStyle = css('--card'); ctx.fillRect(-s, -s, 2 * s, 2 * s);
    ctx.rotate(-roll * Math.PI / 180);
    const off = Math.max(-r, Math.min(r, pitch / 45 * r));
    ctx.fillStyle = css('--accent'); ctx.globalAlpha = 0.35;
    ctx.fillRect(-s, off, 2 * s, s);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = css('--cyan'); ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(-r, off); ctx.lineTo(r, off); ctx.stroke();
    ctx.restore();
    ctx.strokeStyle = css('--line-2'); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(s / 2, s / 2, r, 0, 2 * Math.PI); ctx.stroke();
    ctx.strokeStyle = css('--white'); ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(s / 2 - 34, s / 2); ctx.lineTo(s / 2 - 12, s / 2);
    ctx.moveTo(s / 2 + 12, s / 2); ctx.lineTo(s / 2 + 34, s / 2); ctx.stroke();
}

function bars(canvas, values, colour) {
    const ctx = canvas.getContext('2d'), w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = colour;
    const bw = w / values.length;
    values.forEach((v, i) => ctx.fillRect(i * bw + 1, h - v * h, bw - 2, v * h));
}

const fpsHistory = [];
function spark(fps) {
    fpsHistory.push(fps);
    if (fpsHistory.length > 60) fpsHistory.shift();
    const c = $('spark'), ctx = c.getContext('2d'), w = c.width, h = c.height;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = css('--accent'); ctx.lineWidth = 2;
    ctx.beginPath();
    fpsHistory.forEach((v, i) => {
        const x = i / 59 * w, y = h - 3 - Math.min(1, v / 32) * (h - 6);
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    });
    ctx.stroke();
}

const mm = v => (v == null ? '–' : `${(v / 1000).toFixed(2)} m`);
function setAxis(id, raw) {
    const g = raw / 819;
    const el = $(id);
    const half = Math.min(50, Math.abs(g) * 50);
    el.style.left = g >= 0 ? '50%' : `${50 - half}%`;
    el.style.width = `${half}%`;
    $(`${id}v`).textContent = `${g.toFixed(2)} g`;
}

async function poll() {
    try {
        status = await (await fetch('/api/status', { cache: 'no-store' })).json();
    } catch (e) {
        status = null;
    }
    const pill = $('state');
    pill.className = 'pill';
    if (!status) {
        $('state-text').textContent = 'The Kinect hub is not running';
        pill.classList.add('bad');
    } else {
        const live = status.status === 'streaming';
        pill.classList.add(live ? 'live' : status.status === 'starting' ? 'warn' : 'bad');
        $('state-text').textContent = live
            ? `Kinect ${status.kinect.model} · ${status.fps.toFixed(0)} fps · ${status.mode === 'ir' ? 'infrared' : 'colour'}${status.video === 'auto' ? ' (auto)' : ''}`
            : ({ unpowered: 'Kinect has no power', 'no-kinect': 'No Kinect on USB', starting: 'Starting…' }[status.status] || 'Kinect error');
        const video = status.video || status.mode;
        document.querySelectorAll('.seg [data-video]').forEach(b => b.classList.toggle('on', b.dataset.video === video));
        $('video-title').textContent = (status.mode === 'ir' ? 'Infrared' : 'Colour') +
            (video === 'auto' ? (status.mode === 'ir' ? ' · auto: the room is dark' : ' · auto') : '');
        setAxis('ax', status.accel[0]); setAxis('ay', status.accel[1]); setAxis('az', status.accel[2]);
        $('g').textContent = `${status.g.toFixed(2)} g`;
        $('pitch').textContent = `${status.pitch.toFixed(1)}°`;
        $('roll').textContent = `${status.roll.toFixed(1)}°`;
        horizon(status.pitch, status.roll);
        $('tilt').textContent = status.tilt == null ? '–' : `${status.tilt > 0 ? '+' : ''}${status.tilt.toFixed(1)}°`;
        $('tilt-status').textContent = status.tilt_status || '';
        $('led-now').textContent = status.led || '';
        document.querySelectorAll('[data-led]').forEach(b => b.classList.toggle('on', b.dataset.led === status.led));
        const d = status.depth;
        if (d) {
            $('near').textContent = mm(d.nearest);
            $('median').textContent = mm(d.median);
            $('far').textContent = mm(d.farthest);
            $('valid').textContent = `${d.valid.toFixed(0)}% of pixels`;
            bars($('hist'), d.hist, css('--cyan'));
        }
        $('fps').textContent = `${status.fps.toFixed(1)} fps`;
        spark(status.fps);
        $('frames').textContent = status.seq ? (status.seq / 2).toLocaleString() : '–';
        const cam = status.webcam;
        if (document.activeElement !== $('webcam')) $('webcam').checked = cam.on;
        $('webcam-state').textContent = cam.streaming ? `on · ${cam.device}` : cam.on ? 'starting…' : 'off';
        $('air').textContent = status.air ? 'reading frames' : 'off';
        const dark = video === 'rgb' && status.light != null && status.light < 0.04
            ? 'Too dark for the colour camera (and for finding hands): Auto switches to infrared, which brings its own light.' : null;
        $('dark').hidden = !dark;
        const note = cam.error || (status.status !== 'streaming' ? status.error : null);
        $('note').hidden = !note;
        $('note').textContent = note || '';
    }
    setTimeout(poll, visible ? 250 : 1000);
}
poll();
