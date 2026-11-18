/* The shared WebGL layer: grown from Kinect Studio's point-cloud renderer. Matrices, an orbit
   controller, lit primitives (box, cylinder, sphere), articulated bodies from 33 room-frame
   joints, floor grids, point clouds and meshes. The room frame (x to the picture's right, y up,
   z away from the Kinect) is left-handed, so a camera at the Kinect drawn with an ordinary
   right-handed look-at shows the room as a mirror: your right hand on the screen's right.
   Colours are read from the stylesheet's custom properties, never written here. */
"use strict";

const GL3 = (() => {
  // -- colours from tokens
  const probe = document.createElement("i");
  const cache = {};
  function rgba(name, alpha = 1) {
    const key = `${name}|${alpha}`;
    if (cache[key]) return cache[key];
    probe.style.color = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
    document.body.appendChild(probe);
    const m = getComputedStyle(probe).color.match(/[\d.]+/g).map(Number);
    probe.remove();
    return (cache[key] = [m[0] / 255, m[1] / 255, m[2] / 255, (m[3] === undefined ? 1 : m[3]) * alpha]);
  }

  // -- 4x4 matrices, column-major (WebGL's order)
  const M = {
    id: () => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    mul(a, b) {
      const o = new Array(16).fill(0);
      for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) for (let k = 0; k < 4; k++) o[j * 4 + i] += a[k * 4 + i] * b[j * 4 + k];
      return o;
    },
    perspective(fovy, aspect, near, far) {
      const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
      return [f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0];
    },
    lookAt(e, c, up = [0, 1, 0]) {
      let z = [e[0] - c[0], e[1] - c[1], e[2] - c[2]];
      const zl = Math.hypot(...z); z = z.map((v) => v / zl);
      let x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]];
      const xl = Math.hypot(...x) || 1; x = x.map((v) => v / xl);
      const y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
      return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
        -(x[0] * e[0] + x[1] * e[1] + x[2] * e[2]), -(y[0] * e[0] + y[1] * e[1] + y[2] * e[2]), -(z[0] * e[0] + z[1] * e[1] + z[2] * e[2]), 1];
    },
    translate: (x, y, z) => [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1],
    scale: (x, y, z) => [x, 0, 0, 0, 0, y, 0, 0, 0, 0, z, 0, 0, 0, 0, 1],
    rotX: (a) => [1, 0, 0, 0, 0, Math.cos(a), Math.sin(a), 0, 0, -Math.sin(a), Math.cos(a), 0, 0, 0, 0, 1],
    rotY: (a) => [Math.cos(a), 0, -Math.sin(a), 0, 0, 1, 0, 0, Math.sin(a), 0, Math.cos(a), 0, 0, 0, 0, 1],
    // A unit +Y segment turned and stretched onto a -> b with radius r.
    segment(a, b, r) {
      const d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
      const len = Math.hypot(...d) || 1e-6;
      const y = d.map((v) => v / len);
      const ref = Math.abs(y[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0];
      let x = [y[1] * ref[2] - y[2] * ref[1], y[2] * ref[0] - y[0] * ref[2], y[0] * ref[1] - y[1] * ref[0]];
      const xl = Math.hypot(...x); x = x.map((v) => v / xl);
      const z = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]];
      return [x[0] * r, x[1] * r, x[2] * r, 0, y[0] * len, y[1] * len, y[2] * len, 0, z[0] * r, z[1] * r, z[2] * r, 0, a[0], a[1], a[2], 1];
    },
    apply(m, p) {
      const x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12], y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
      const z = m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14], w = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
      return [x / w, y / w, z / w, w];
    },
  };

  // -- geometry: unit primitives as (position, normal) triangles
  function box() {
    const p = [], n = [];
    const faces = [[0, 1, 2], [0, -1, 2], [1, 0, 2], [-1, 0, 2], [2, 0, 1], [-2, 0, 1]];
    for (const [ax, sgn] of [[0, 1], [0, -1], [1, 1], [1, -1], [2, 1], [2, -1]]) {
      const u = (ax + 1) % 3, v = (ax + 2) % 3;
      const corner = (a, b) => { const q = [0, 0, 0]; q[ax] = 0.5 * sgn; q[u] = a * 0.5; q[v] = b * 0.5; return q; };
      const quad = [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, -1), corner(1, 1), corner(-1, 1)];
      const nn = [0, 0, 0]; nn[ax] = sgn;
      for (const q of quad) { p.push(...q); n.push(...nn); }
    }
    void faces;
    return { p, n };
  }
  function cylinder(seg = 14) {
    const p = [], n = [];
    for (let i = 0; i < seg; i++) {
      const a0 = (i / seg) * Math.PI * 2, a1 = ((i + 1) / seg) * Math.PI * 2;
      const c0 = [Math.cos(a0), Math.sin(a0)], c1 = [Math.cos(a1), Math.sin(a1)];
      const quad = [[c0, 0], [c1, 0], [c1, 1], [c0, 0], [c1, 1], [c0, 1]];
      for (const [c, y] of quad) { p.push(c[0], y, c[1]); n.push(c[0], 0, c[1]); }
    }
    return { p, n };
  }
  function sphere(lat = 8, lon = 12) {
    const p = [], n = [];
    const pt = (i, j) => { const t = (i / lat) * Math.PI, f = (j / lon) * Math.PI * 2; return [Math.sin(t) * Math.cos(f), Math.cos(t), Math.sin(t) * Math.sin(f)]; };
    for (let i = 0; i < lat; i++) for (let j = 0; j < lon; j++) {
      for (const q of [pt(i, j), pt(i + 1, j), pt(i + 1, j + 1), pt(i, j), pt(i + 1, j + 1), pt(i, j + 1)]) { p.push(...q); n.push(...q); }
    }
    return { p, n };
  }
  function cone(seg = 14) {
    const p = [], n = [];
    for (let i = 0; i < seg; i++) {
      const a0 = (i / seg) * Math.PI * 2, a1 = ((i + 1) / seg) * Math.PI * 2;
      p.push(Math.cos(a0), 0, Math.sin(a0), Math.cos(a1), 0, Math.sin(a1), 0, 1, 0);
      n.push(Math.cos(a0), 0.5, Math.sin(a0), Math.cos(a1), 0.5, Math.sin(a1), 0, 1, 0);
    }
    return { p, n };
  }

  const MESH_VS = `attribute vec3 pos; attribute vec3 nor; uniform mat4 proj; uniform mat4 view; uniform mat4 model;
    varying vec3 vn; varying vec3 vw;
    void main() { vec4 w = model * vec4(pos, 1.0); vw = w.xyz; vn = mat3(model) * nor; gl_Position = proj * view * w; }`;
  const MESH_FS = `precision mediump float; uniform vec4 col; uniform vec3 light; uniform float lit; uniform vec3 fogc; uniform float fog;
    uniform vec3 eye; varying vec3 vn; varying vec3 vw;
    void main() { vec3 n = normalize(vn); float d = abs(dot(n, normalize(light)));
      vec3 c = col.rgb * mix(1.0, 0.38 + 0.72 * d, lit);
      float f = fog > 0.0 ? clamp((distance(vw, eye) - fog) / (fog * 2.0), 0.0, 0.85) : 0.0;
      gl_FragColor = vec4(mix(c, fogc, f), col.a); }`;
  const LINE_VS = `attribute vec3 pos; uniform mat4 proj; uniform mat4 view; void main() { gl_Position = proj * view * vec4(pos, 1.0); }`;
  const LINE_FS = `precision mediump float; uniform vec4 col; void main() { gl_FragColor = col; }`;
  const PT_VS = `attribute vec3 pos; attribute vec3 rgb; uniform mat4 proj; uniform mat4 view; uniform mat4 model; uniform float size;
    uniform int mode; uniform vec3 nearC; uniform vec3 midC; uniform vec3 farC; uniform vec4 col; varying vec4 v;
    void main() { vec4 w = model * vec4(pos, 1.0); gl_Position = proj * view * w; gl_PointSize = size;
      if (mode == 1) { float t = clamp((pos.z - 0.4) / 3.6, 0.0, 1.0); v = vec4(t < 0.5 ? mix(nearC, midC, t * 2.0) : mix(midC, farC, t * 2.0 - 1.0), 1.0); }
      else if (mode == 2) { v = col; } else { v = vec4(rgb, 1.0); } }`;
  const PT_FS = `precision mediump float; varying vec4 v; void main() { vec2 c = gl_PointCoord - 0.5; if (dot(c, c) > 0.25) discard; gl_FragColor = v; }`;

  function program(gl, vs, fs) {
    const sh = (type, src) => {
      const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const p = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
    const u = {}, a = {};
    const nu = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < nu; i++) { const info = gl.getActiveUniform(p, i); u[info.name] = gl.getUniformLocation(p, info.name); }
    const na = gl.getProgramParameter(p, gl.ACTIVE_ATTRIBUTES);
    for (let i = 0; i < na; i++) { const info = gl.getActiveAttrib(p, i); a[info.name] = gl.getAttribLocation(p, info.name); }
    return { p, u, a };
  }

  // MediaPipe's 33-joint skeleton: bones and their thickness (m).
  const BONES = [[11, 13, 0.045], [13, 15, 0.038], [12, 14, 0.045], [14, 16, 0.038], [23, 25, 0.06], [25, 27, 0.048],
    [24, 26, 0.06], [26, 28, 0.048], [27, 31, 0.035], [28, 32, 0.035], [11, 12, 0.05], [23, 24, 0.055]];

  // -- one renderer per canvas
  function create(canvas, opts = {}) {
    const gl = canvas.getContext("webgl", { antialias: true, alpha: false, premultipliedAlpha: false });
    if (!gl) return null;
    const mesh = program(gl, MESH_VS, MESH_FS), line = program(gl, LINE_VS, LINE_FS), pts = program(gl, PT_VS, PT_FS);
    const buf = (data) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW); return b; };
    const prims = {};
    for (const [name, g] of Object.entries({ box: box(), cyl: cylinder(), sphere: sphere(), cone: cone() })) {
      prims[name] = { p: buf(g.p), n: buf(g.n), count: g.p.length / 3 };
    }
    const lineBuf = gl.createBuffer(), ptPos = gl.createBuffer(), ptCol = gl.createBuffer();
    let ptCount = 0, meshBuf = null;
    const modelBuf = new Float32Array(16);
    const r = {
      gl, canvas, proj: M.id(), view: M.id(), eye: [0, 1.5, -1], w: 1, h: 1, fog: 0, fogc: [0, 0, 0],
      light: [0.4, 1.0, -0.6], frames: 0, fps: 0, _t: performance.now(),
      resize() {
        const d = Math.min(2, window.devicePixelRatio || 1);
        const w = Math.max(1, Math.round(canvas.clientWidth * d)), h = Math.max(1, Math.round(canvas.clientHeight * d));
        if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
        r.w = w; r.h = h; r.dpr = d;
        gl.viewport(0, 0, w, h);
      },
      viewport(x, y, w, h) { gl.viewport(x, y, w, h); gl.enable(gl.SCISSOR_TEST); gl.scissor(x, y, w, h); r.vw = [x, y, w, h]; },
      full() { gl.disable(gl.SCISSOR_TEST); gl.viewport(0, 0, r.w, r.h); r.vw = [0, 0, r.w, r.h]; },
      clear(col) {
        const c = col || rgba("window");
        gl.clearColor(c[0], c[1], c[2], 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        gl.enable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        r.fogc = c.slice(0, 3);
        r.camVersion += 1;
        const now = performance.now(); r.frames++;
        if (now - r._t > 1000) { r.fps = (r.frames * 1000) / (now - r._t); r.frames = 0; r._t = now; }
      },
      camVersion: 0,
      camera(eye, target, fov = 0.85, aspect) {
        r.eye = eye;
        r.camVersion += 1;
        const vw = r.vw || [0, 0, r.w, r.h];
        r.proj = M.perspective(fov, aspect || vw[2] / Math.max(1, vw[3]), 0.05, 60);
        r.view = M.lookAt(eye, target);
      },
      setView(view, proj) { r.view = view; if (proj) r.proj = proj; r.camVersion += 1; },
      // A room point -> canvas pixels (CSS px), for labels drawn over the scene.
      project(p) {
        const q = M.apply(M.mul(r.proj, r.view), p);
        const vw = r.vw || [0, 0, r.w, r.h];
        if (q[3] <= 0) return null;
        return [(vw[0] + (q[0] * 0.5 + 0.5) * vw[2]) / r.dpr, (r.h - (vw[1] + (q[1] * 0.5 + 0.5) * vw[3])) / r.dpr, q[3]];
      },
      draw(name, model, col, lit = 1) {
        const pr = prims[name], g = mesh;
        gl.useProgram(g.p);
        gl.bindBuffer(gl.ARRAY_BUFFER, pr.p); gl.enableVertexAttribArray(g.a.pos); gl.vertexAttribPointer(g.a.pos, 3, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, pr.n); gl.enableVertexAttribArray(g.a.nor); gl.vertexAttribPointer(g.a.nor, 3, gl.FLOAT, false, 0, 0);
        // Camera uniforms only when the camera changed since this program last drew.
        if (g.cam !== r.camVersion) {
          g.cam = r.camVersion;
          gl.uniformMatrix4fv(g.u.proj, false, new Float32Array(r.proj)); gl.uniformMatrix4fv(g.u.view, false, new Float32Array(r.view));
          gl.uniform3fv(g.u.light, r.light); gl.uniform3fv(g.u.fogc, r.fogc); gl.uniform1f(g.u.fog, r.fog); gl.uniform3fv(g.u.eye, r.eye);
        }
        modelBuf.set(model);
        gl.uniformMatrix4fv(g.u.model, false, modelBuf); gl.uniform4fv(g.u.col, col); gl.uniform1f(g.u.lit, lit);
        gl.depthMask(col[3] >= 0.99);
        gl.drawArrays(gl.TRIANGLES, 0, pr.count);
        gl.depthMask(true);
      },
      lines(points, col) {
        if (!points.length) return;
        const g = line;
        gl.useProgram(g.p);
        gl.bindBuffer(gl.ARRAY_BUFFER, lineBuf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(points), gl.DYNAMIC_DRAW);
        gl.enableVertexAttribArray(g.a.pos); gl.vertexAttribPointer(g.a.pos, 3, gl.FLOAT, false, 0, 0);
        gl.uniformMatrix4fv(g.u.proj, false, new Float32Array(r.proj)); gl.uniformMatrix4fv(g.u.view, false, new Float32Array(r.view));
        gl.uniform4fv(g.u.col, col);
        gl.drawArrays(gl.LINES, 0, points.length / 3);
      },
      // A floor grid (1 m cells by default) and the Kinect's view on it.
      grid(x0, x1, z0, z1, step = 0.5, col) {
        const c = col || rgba("grid-2"), p = [];
        for (let x = Math.ceil(x0 / step) * step; x <= x1 + 1e-6; x += step) p.push(x, 0, z0, x, 0, z1);
        for (let z = Math.ceil(z0 / step) * step; z <= z1 + 1e-6; z += step) p.push(x0, 0, z, x1, 0, z);
        r.lines(p, c);
      },
      // An articulated body from 33 room-frame joints ([x, y, z, state] or null).
      body(joints, col, opts = {}) {
        if (!joints) return;
        const s = opts.scale || 1, solid = col, faint = [col[0], col[1], col[2], col[3] * 0.45];
        const jp = (i) => joints[i] && [joints[i][0], joints[i][1], joints[i][2]];
        for (const [a, b, rad] of BONES) {
          const p = jp(a), q = jp(b);
          if (!p || !q) continue;
          const seen = (joints[a][3] ?? 2) === 2 && (joints[b][3] ?? 2) === 2;
          r.draw("cyl", M.segment(p, q, rad * s), seen ? solid : faint);
        }
        // The torso: shoulders' middle to hips' middle, thick.
        const sh = jp(11) && jp(12) && [(joints[11][0] + joints[12][0]) / 2, (joints[11][1] + joints[12][1]) / 2, (joints[11][2] + joints[12][2]) / 2];
        const hp = jp(23) && jp(24) && [(joints[23][0] + joints[24][0]) / 2, (joints[23][1] + joints[24][1]) / 2, (joints[23][2] + joints[24][2]) / 2];
        if (sh && hp) r.draw("cyl", M.segment(hp, sh, 0.11 * s), solid);
        for (const i of [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]) {
          const p = jp(i);
          if (!p) continue;
          const rad = (i === 15 || i === 16 ? 0.045 : 0.05) * s;
          r.draw("sphere", M.mul(M.translate(...p), M.scale(rad, rad, rad)), (joints[i][3] ?? 2) === 2 ? solid : faint);
        }
        const nose = jp(0);
        if (nose && sh) {
          const head = [sh[0] + (nose[0] - sh[0]) * 1.0, nose[1] + 0.02, (nose[2] + sh[2]) / 2];
          r.draw("cyl", M.segment(sh, head, 0.045 * s), solid);
          r.draw("sphere", M.mul(M.translate(...head), M.scale(0.105 * s, 0.12 * s, 0.105 * s)), solid);
        }
        if (opts.shadow !== false && hp) {
          r.draw("cyl", M.mul(M.translate(hp[0], 0.002, hp[2]), M.scale(0.32 * s, 0.004, 0.32 * s)), rgba("shade"), 0);
        }
      },
      // Point clouds: xyz Float32Array (camera frame, y down), rgb Uint8Array.
      setPoints(xyz, rgb) {
        gl.bindBuffer(gl.ARRAY_BUFFER, ptPos); gl.bufferData(gl.ARRAY_BUFFER, xyz, gl.DYNAMIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, ptCol); gl.bufferData(gl.ARRAY_BUFFER, rgb || new Uint8Array(xyz.length), gl.DYNAMIC_DRAW);
        ptCount = xyz.length / 3;
      },
      points(model, size, mode = 0, col) {
        if (!ptCount) return 0;
        const g = pts;
        gl.useProgram(g.p);
        gl.bindBuffer(gl.ARRAY_BUFFER, ptPos); gl.enableVertexAttribArray(g.a.pos); gl.vertexAttribPointer(g.a.pos, 3, gl.FLOAT, false, 0, 0);
        if (g.a.rgb !== undefined && g.a.rgb >= 0) {
          gl.bindBuffer(gl.ARRAY_BUFFER, ptCol); gl.enableVertexAttribArray(g.a.rgb); gl.vertexAttribPointer(g.a.rgb, 3, gl.UNSIGNED_BYTE, true, 0, 0);
        }
        gl.uniformMatrix4fv(g.u.proj, false, new Float32Array(r.proj)); gl.uniformMatrix4fv(g.u.view, false, new Float32Array(r.view));
        gl.uniformMatrix4fv(g.u.model, false, new Float32Array(model || M.id()));
        gl.uniform1f(g.u.size, size * (r.dpr || 1)); gl.uniform1i(g.u.mode, mode);
        gl.uniform3fv(g.u.nearC, rgba("warn").slice(0, 3)); gl.uniform3fv(g.u.midC, rgba("cyan").slice(0, 3));
        gl.uniform3fv(g.u.farC, rgba("indigo").slice(0, 3)); gl.uniform4fv(g.u.col, col || rgba("accent"));
        gl.drawArrays(gl.POINTS, 0, ptCount);
        return ptCount;
      },
      // A triangle mesh (vertices Float32Array xyz, triangles Uint32/16 -> expanded), lit.
      setMesh(vertices, triangles) {
        const p = new Float32Array(triangles.length * 3), n = new Float32Array(triangles.length * 3);
        for (let t = 0; t < triangles.length; t += 3) {
          const ia = triangles[t] * 3, ib = triangles[t + 1] * 3, ic = triangles[t + 2] * 3;
          const a = [vertices[ia], vertices[ia + 1], vertices[ia + 2]], b = [vertices[ib], vertices[ib + 1], vertices[ib + 2]], c = [vertices[ic], vertices[ic + 1], vertices[ic + 2]];
          const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
          const nn = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
          for (let k = 0; k < 3; k++) { p.set(k === 0 ? a : k === 1 ? b : c, (t + k) * 3); n.set(nn, (t + k) * 3); }
        }
        meshBuf = { p: gl.createBuffer(), n: gl.createBuffer(), count: triangles.length };
        gl.bindBuffer(gl.ARRAY_BUFFER, meshBuf.p); gl.bufferData(gl.ARRAY_BUFFER, p, gl.STATIC_DRAW);
        gl.bindBuffer(gl.ARRAY_BUFFER, meshBuf.n); gl.bufferData(gl.ARRAY_BUFFER, n, gl.STATIC_DRAW);
        prims.mesh = meshBuf;
      },
      clearMesh() { delete prims.mesh; meshBuf = null; },
      hasMesh: () => !!prims.mesh,
      rgba,
    };
    r.resize();
    return r;
  }

  // -- orbit controls: drag turns, right-drag / shift-drag moves, wheel zooms (Studio's)
  function orbit(canvas, init = {}) {
    const v = { yaw: 0, pitch: 0.18, dist: 2.4, target: [0, 0, 1.6], spin: false, ...init };
    const start = { ...v, target: [...v.target] };
    let drag = null;
    canvas.addEventListener("contextmenu", (e) => e.preventDefault());
    canvas.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey }; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      if (drag.pan) { v.target[0] -= dx * 0.002 * v.dist * Math.cos(v.yaw); v.target[2] += dx * 0.002 * v.dist * Math.sin(v.yaw); v.target[1] += dy * 0.002 * v.dist; }
      else { v.yaw += dx * 0.008; v.pitch = Math.max(-1.45, Math.min(1.45, v.pitch + dy * 0.008)); }
    });
    canvas.addEventListener("pointerup", () => { drag = null; });
    canvas.addEventListener("wheel", (e) => { e.preventDefault(); v.dist = Math.max(0.25, Math.min(12, v.dist * (1 + e.deltaY * 0.0012))); }, { passive: false });
    return {
      v,
      reset() { Object.assign(v, { ...start, target: [...start.target] }); },
      eye(dt = 0) {
        if (v.spin) v.yaw += dt * 0.4;
        const c = Math.cos(v.pitch);
        // Looking towards +z from the Kinect's side by default (yaw 0 = from the Kinect).
        return [v.target[0] - v.dist * c * Math.sin(v.yaw), v.target[1] + v.dist * Math.sin(v.pitch), v.target[2] - v.dist * c * Math.cos(v.yaw)];
      },
    };
  }

  return { create, orbit, M, rgba, BONES };
})();
