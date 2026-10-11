// The office floor plan: tiles, walls, furniture sprites, seats and walkable grid.
export const T = 16, W = 50, H = 32;

const floor = new Array(W * H).fill('grass');
export const blocked = new Uint8Array(W * H);
export const objects = [];        // {img, x, y, sortY, anim?(ctx,t)} — drawn sorted with characters
export const desks = {};          // id -> {x, y, facing, seat:{x,y,dir}, screen:{x,y}|null}
export const meetingSeats = [];   // {x, y, dir}
export const idleSpots = [];      // {x, y, dir, sit, name}
export const labels = [];         // {text, x, y} in tile units
export const spots = {};          // named points: spawn, meetingHead, ...

const at = (x, y) => y * W + x;
export const isWalkable = (x, y) => x >= 0 && y >= 0 && x < W && y < H && !blocked[at(x, y)];

function rect(x0, y0, x1, y1, type) {
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) floor[at(x, y)] = type;
}
function wallH(x0, x1, y) { for (let x = x0; x <= x1; x++) { floor[at(x, y)] = 'wall'; blocked[at(x, y)] = 1; } }
function wallV(x, y0, y1) { for (let y = y0; y <= y1; y++) { floor[at(x, y)] = 'wall'; blocked[at(x, y)] = 1; } }
function door(x, y, type) { floor[at(x, y)] = type; blocked[at(x, y)] = 0; }
function block(x0, y0, x1, y1) { for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) blocked[at(x, y)] = 1; }

function mk(w, h, fn) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const g = c.getContext('2d'); fn(g, (x, y, ww, hh, col) => { g.fillStyle = col; g.fillRect(x, y, ww, hh); });
  return c;
}
function place(img, x, y, sortY, anim) { objects.push({ img, x, y, sortY, anim }); }
function circle(g, cx, cy, r, col) {
  g.fillStyle = col;
  for (let y = -r; y <= r; y++) { const w = Math.round(Math.sqrt(r * r - y * y)); g.fillRect(cx - w, cy + y, w * 2, 1); }
}

// ------------------------------------------------------------------ layout
rect(4, 0, 49, 31, 'wood');
wallH(4, 49, 0); wallH(4, 49, 31); wallV(4, 0, 31); wallV(49, 0, 31);
wallV(15, 0, 31); wallH(4, 15, 10); wallH(4, 15, 20);
rect(5, 1, 14, 9, 'carpetB'); rect(5, 11, 14, 19, 'tile'); rect(5, 21, 14, 30, 'carpetP');
door(15, 5, 'wood'); door(15, 6, 'wood'); door(15, 15, 'wood'); door(15, 16, 'wood'); door(15, 25, 'wood'); door(15, 26, 'wood');
door(23, 31, 'wood'); door(24, 31, 'wood'); door(25, 31, 'wood');
// meeting room
wallH(33, 49, 20); wallV(33, 20, 31); rect(34, 21, 48, 30, 'meet');
door(36, 20, 'meet'); door(37, 20, 'meet');
// team areas
rect(18, 2, 30, 7, 'carpetG'); rect(34, 2, 47, 7, 'carpetG'); rect(34, 11, 47, 16, 'carpetG');
rect(19, 12, 30, 19, 'rug');
rect(7, 5, 12, 8, 'rugB'); rect(7, 24, 12, 28, 'rugP'); rect(22, 28, 26, 30, 'mat');

labels.push(
  { text: "Claude's office", x: 10, y: 0.25 }, { text: 'Kitchen', x: 10, y: 10.25 }, { text: 'Library', x: 10, y: 20.25 },
  { text: 'Product team', x: 24.5, y: 1.3 }, { text: 'Engineering', x: 41, y: 1.3 }, { text: 'Research', x: 41, y: 10.3 },
  { text: 'Lounge', x: 25, y: 11.3 }, { text: 'Meeting room', x: 42.5, y: 20.25 }, { text: 'Reception', x: 24.5, y: 20.6 },
);

// ------------------------------------------------------------------ furniture sprites
const C = {
  deskTop: '#f6f7fb', deskEdge: '#d6dae6', deskFace: '#c3c8d8', leg: '#8f96ad',
  bezel: '#262938', monBack: '#3d4256', monBack2: '#4b5169',
  chair: '#3b3f55', chairHi: '#4d5270',
  pot: '#c8724a', potDark: '#9c5536', leaf: '#4caf6a', leafDark: '#2f8a4e', leafHi: '#7dd08f',
  wood: '#a8754d', woodDark: '#7d5435', woodHi: '#c48d61',
};

function deskImg(facing) {
  return mk(48, 22, (g, p) => {
    p(0, 4, 48, 12, C.deskTop); p(0, 4, 48, 1, '#ffffff'); p(0, 15, 48, 1, C.deskEdge);
    p(0, 16, 48, 3, C.deskFace); p(2, 19, 2, 3, C.leg); p(44, 19, 2, 3, C.leg);
    if (facing === 'up') {          // screen faces the viewer
      p(15, 0, 18, 11, C.bezel); p(23, 11, 2, 2, '#596079'); p(20, 13, 8, 1, '#596079');
      p(17, 13, 14, 2, '#dfe3ec'); p(18, 13, 12, 1, '#c7ccd9');                          // keyboard
      p(36, 9, 6, 4, '#ffffff'); p(37, 10, 4, 2, '#b07a4f');                            // coffee mug
    } else {                        // monitor back faces the viewer
      p(3, 0, 15, 10, C.monBack); p(4, 1, 13, 8, C.monBack2); p(9, 10, 3, 3, '#596079');
      p(30, 7, 10, 6, '#e2e6ee'); p(31, 8, 8, 4, '#cfd5e2');                            // notebook
    }
  });
}
function chairImg(facing) {
  return mk(14, 14, (g, p) => {
    if (facing === 'up') { p(2, 1, 10, 6, C.chair); p(1, 6, 12, 6, '#2c2f41'); p(2, 6, 10, 1, C.chairHi); p(6, 12, 2, 2, '#22242f'); }
    else { p(1, 0, 12, 6, '#2c2f41'); p(2, 0, 10, 1, C.chairHi); p(2, 6, 10, 6, C.chair); p(6, 12, 2, 2, '#22242f'); }
  });
}
function plantImg(big) {
  const w = big ? 18 : 14, h = big ? 26 : 18;
  return mk(w, h, (g, p) => {
    const cx = w / 2, potW = big ? 10 : 8;
    p(cx - potW / 2, h - 7, potW, 7, C.pot); p(cx - potW / 2, h - 7, potW, 2, '#de8c5f'); p(cx - potW / 2 + 1, h - 1, potW - 2, 1, C.potDark);
    if (big) {
      circle(g, cx, 8, 6, C.leafDark); circle(g, cx - 4, 12, 5, C.leaf); circle(g, cx + 4, 12, 5, C.leaf);
      circle(g, cx, 6, 4, C.leaf); p(cx - 2, 3, 2, 2, C.leafHi); p(cx + 3, 10, 2, 2, C.leafHi); p(cx - 6, 11, 2, 2, C.leafHi);
    } else {
      circle(g, cx, 6, 5, C.leafDark); circle(g, cx - 3, 8, 3, C.leaf); circle(g, cx + 3, 7, 3, C.leaf); p(cx - 1, 3, 2, 2, C.leafHi);
    }
  });
}
function bambooImg() {
  return mk(16, 30, (g, p) => {
    p(2, 22, 12, 8, '#5f6b7a'); p(2, 22, 12, 2, '#76839a');
    for (const [x, hh] of [[4, 20], [7, 22], [10, 19], [12, 17]]) {
      p(x, 24 - hh, 2, hh, '#6fbf5a'); for (let k = 24 - hh; k < 24; k += 5) p(x, k, 2, 1, '#4c9a3d');
      p(x - 2, 24 - hh + 2, 3, 2, '#86d46f'); p(x + 2, 24 - hh + 6, 3, 2, '#86d46f');
    }
  });
}
function shelfImg(wt) {
  const books = ['#e56b6b', '#6c8cff', '#f4c95d', '#3fb68b', '#8e6cf0', '#ef8a3c', '#4fb3d9', '#e56b8a'];
  return mk(wt * 16, 28, (g, p) => {
    p(0, 0, wt * 16, 28, C.woodDark); p(1, 1, wt * 16 - 2, 26, C.wood);
    for (const sy of [2, 11, 20]) {
      p(2, sy, wt * 16 - 4, 7, '#6b4529');
      let x = 3, i = sy;
      while (x < wt * 16 - 4) { const bw = 2 + ((x * 7 + i) % 3); const bh = 5 + ((x + i) % 3) - 1; p(x, sy + 7 - bh, bw, bh, books[(x + i) % books.length]); x += bw + ((x % 5) ? 0 : 1); i++; }
      p(1, sy + 7, wt * 16 - 2, 2, C.woodHi);
    }
  });
}
function sofaImg(wt, col, colDark, facing) {
  return mk(wt * 16, 18, (g, p) => {
    const w = wt * 16;
    if (facing === 'down') { p(0, 0, w, 8, colDark); p(1, 1, w - 2, 2, col); p(0, 6, w, 9, col); p(0, 6, 4, 10, colDark); p(w - 4, 6, 4, 10, colDark); p(5, 8, w - 10, 1, '#ffffff33'); }
    else { p(0, 4, w, 9, col); p(0, 10, w, 8, colDark); p(1, 11, w - 2, 2, col); p(0, 3, 4, 10, colDark); p(w - 4, 3, 4, 10, colDark); }
    p(2, 17, w - 4, 1, 'rgba(0,0,0,.18)');
  });
}
function pingpongImg() {
  return mk(64, 36, (g, p) => {
    p(2, 2, 60, 28, '#2f7d55'); p(2, 2, 60, 2, '#3f9a6a'); p(2, 30, 60, 4, '#245f41');
    p(4, 4, 56, 1, '#e8f5ee'); p(4, 28, 56, 1, '#e8f5ee'); p(4, 4, 1, 25, '#e8f5ee'); p(59, 4, 1, 25, '#e8f5ee');
    p(4, 16, 56, 1, '#cfe9dc'); p(31, 1, 2, 30, '#f2f2f2'); p(31, 1, 2, 2, '#9aa'); p(6, 33, 3, 3, '#333'); p(55, 33, 3, 3, '#333');
    p(12, 9, 5, 5, '#d8473f'); p(14, 14, 1, 3, '#7a4a2a'); p(46, 20, 5, 5, '#3f6bd8'); p(48, 25, 1, 3, '#7a4a2a'); p(24, 11, 2, 2, '#ffffff');
  });
}
function tableImg(wt, ht, top, edge) {
  return mk(wt * 16, ht * 16 + 4, (g, p) => {
    const w = wt * 16, h = ht * 16;
    p(0, 0, w, h, edge); p(1, 1, w - 2, h - 3, top); p(1, 1, w - 2, 1, '#ffffff55'); p(0, h - 2, w, 4, edge);
    p(2, h + 2, 2, 2, '#00000033'); p(w - 4, h + 2, 2, 2, '#00000033');
  });
}
function counterImg(wt) {
  return mk(wt * 16, 24, (g, p) => {
    const w = wt * 16;
    p(0, 0, w, 9, '#cfd8de'); p(0, 0, w, 1, '#eef2f5'); p(0, 9, w, 15, '#8fa1ad');
    for (let x = 2; x < w - 4; x += 16) { p(x, 11, 14, 11, '#9fb2be'); p(x + 6, 15, 2, 2, '#5d6d78'); }
    p(20, 2, 12, 5, '#9bb3c2'); p(21, 3, 10, 3, '#7c98aa'); p(25, 0, 2, 3, '#c0c8cf');                    // sink
    p(44, -0, 10, 9, '#3a3a44'); p(46, 2, 6, 3, '#7a7a88'); p(48, 6, 2, 2, '#d8473f');                     // coffee machine
    p(70, 3, 6, 5, '#ffffff'); p(78, 3, 6, 5, '#f4c95d'); p(100, 1, 14, 7, '#e9b26a'); p(102, 0, 10, 2, '#c58b44'); // cups, bread
  });
}
function fridgeImg() {
  return mk(16, 30, (g, p) => {
    p(0, 0, 16, 30, '#d9e2e8'); p(1, 1, 14, 10, '#eef3f6'); p(1, 12, 14, 17, '#eef3f6'); p(12, 4, 2, 5, '#9aa8b2'); p(12, 15, 2, 7, '#9aa8b2');
    p(3, 3, 3, 3, '#e56b6b'); p(7, 5, 3, 2, '#6c8cff');
  });
}
function coolerImg() {
  return mk(12, 26, (g, p) => {
    p(2, 0, 8, 10, '#8fd0f3'); p(3, 1, 3, 7, '#c4ecff'); p(1, 10, 10, 15, '#e7ecf0'); p(1, 10, 10, 1, '#ffffff');
    p(4, 13, 2, 2, '#4f8fd9'); p(7, 13, 2, 2, '#d8473f'); p(2, 24, 8, 2, '#9aa8b2');
  });
}
function tvImg(wt) {
  return mk(wt * 16, 20, (g, p) => {
    const w = wt * 16;
    p(0, 0, w, 14, '#1b1d27'); p(1, 1, w - 2, 12, '#2c3e66'); p(3, 3, w / 3, 2, '#6c8cff88'); p(3, 7, w / 2, 2, '#3fb68b88');
    p(w / 2 - 2, 14, 4, 2, '#444'); p(4, 16, w - 8, 4, '#7d5435'); p(4, 16, w - 8, 1, '#a8754d');
  });
}
function whiteboardImg(wt) {
  return mk(wt * 16, 18, (g, p) => {
    const w = wt * 16;
    p(0, 0, w, 15, '#9aa3b5'); p(1, 1, w - 2, 13, '#fbfcff'); p(4, 4, w * 0.4, 1, '#6c8cff'); p(4, 7, w * 0.6, 1, '#e56b6b');
    p(4, 10, w * 0.3, 1, '#3fb68b'); p(w * 0.6, 3, 8, 8, '#f4c95d66'); p(2, 15, w - 4, 2, '#7a8396');
  });
}
function armchairImg(col, dark) {
  return mk(16, 16, (g, p) => { p(1, 2, 14, 12, col); p(0, 1, 16, 5, dark); p(0, 1, 3, 13, dark); p(13, 1, 3, 13, dark); p(4, 7, 8, 1, '#ffffff33'); p(2, 15, 12, 1, '#00000022'); });
}
function lampImg() {
  return mk(10, 26, (g, p) => { p(1, 0, 8, 6, '#f4e3b0'); p(2, 1, 6, 4, '#fff4d0'); p(4, 6, 2, 17, '#555'); p(2, 23, 6, 3, '#444'); });
}
function treeImg() {
  return mk(36, 44, (g, p) => {
    p(15, 30, 6, 12, '#7a4f31'); p(15, 30, 2, 12, '#8f6040');
    circle(g, 18, 18, 14, '#2f7d3f'); circle(g, 12, 22, 9, '#3b9a4c'); circle(g, 24, 22, 9, '#3b9a4c'); circle(g, 18, 12, 9, '#4cb35d');
    circle(g, 14, 10, 3, '#6fd07c'); circle(g, 24, 16, 2, '#6fd07c'); p(6, 42, 24, 2, 'rgba(0,0,0,.18)');
  });
}
function bushImg() { return mk(18, 12, (g) => { circle(g, 6, 7, 5, '#3b9a4c'); circle(g, 12, 6, 5, '#4cb35d'); circle(g, 9, 4, 3, '#6fd07c'); }); }
function receptionImg() {
  return mk(80, 26, (g, p) => {
    p(0, 4, 80, 10, '#f0f2f7'); p(0, 4, 80, 1, '#fff'); p(0, 14, 80, 12, '#6c5ca8'); p(0, 14, 80, 2, '#8d7fd0');
    p(30, 18, 20, 4, '#f4c95d'); p(10, 0, 14, 9, C.bezel); p(11, 1, 12, 6, '#2c3e66'); p(56, 6, 8, 5, '#ffffff'); p(66, 2, 6, 9, '#3fb68b');
  });
}
function beanbagImg(col) { return mk(16, 14, (g, p) => { circle(g, 8, 8, 6, col); p(4, 5, 4, 2, '#ffffff44'); p(3, 13, 10, 1, '#00000022'); }); }
function deskLampImg() { return mk(8, 10, (g, p) => { p(0, 0, 8, 3, '#f4c95d'); p(3, 3, 2, 6, '#555'); p(1, 9, 6, 1, '#444'); }); }

// ------------------------------------------------------------------ placements
const seatImgUp = chairImg('up'), seatImgDown = chairImg('down');
function addDesk(id, x, y, facing) {
  // desk occupies tiles x..x+2 on row y; the seat is above it (facing down) or below it (facing up)
  block(x, y, x + 2, y);
  const sy = facing === 'down' ? y - 1 : y + 1;
  const seat = { x: x + 1, y: sy, dir: facing };
  const img = deskImg(facing);
  const d = { id, x, y, facing, seat, screen: facing === 'up' ? { x: x * T + 16, y: y * T - 4 + 1 } : null,
              back: facing === 'down' ? { x: x * T + 3, y: y * T - 4 } : null, owner: null };
  desks[id] = d;
  if (facing === 'down') place(seatImgDown, seat.x * T + 1, sy * T + 1, sy * T + 4);
  place(img, x * T, y * T - 4, y * T + 16, (ctx, t) => drawScreen(ctx, d, t));
  if (facing === 'up') place(seatImgUp, seat.x * T + 1, sy * T + 3, sy * T + 17);
}

// Screens: owner state is set by the app each frame (working / idle / none)
function drawScreen(ctx, d, t) {
  if (d.back) {                    // monitor seen from behind: show its light on the person and a status LED
    const { x, y } = d.back, st = d.state || 'off';
    if (st === 'working') {
      const a = 0.18 + 0.08 * Math.sin(t / 300);
      ctx.fillStyle = `rgba(140,180,255,${a})`; ctx.fillRect(x + 1, y - 3, 13, 3);
      ctx.fillStyle = Math.floor(t / 400) % 2 ? '#7dffb0' : '#2fb67c'; ctx.fillRect(x + 12, y + 7, 2, 1);
    } else if (st === 'idle') { ctx.fillStyle = '#2fb67c'; ctx.fillRect(x + 12, y + 7, 2, 1); }
    else if (st === 'meeting') { ctx.fillStyle = '#f5a524'; ctx.fillRect(x + 12, y + 7, 2, 1); }
    return;
  }
  if (!d.screen) return;
  const { x, y } = d.screen, st = d.state || 'off';
  const col = st === 'working' ? '#14203a' : st === 'idle' ? '#2b3e66' : st === 'meeting' ? '#24304a' : '#161925';
  ctx.fillStyle = col; ctx.fillRect(x, y, 16, 9);
  if (st === 'working') {
    const cols = ['#6c8cff', '#3fb68b', '#f4c95d', '#e56b8a', '#a2b4ff'];
    const off = Math.floor(t / 260);
    for (let i = 0; i < 4; i++) {
      const k = (i + off) % 7, w = 3 + ((k * 5 + i * 3) % 10);
      ctx.fillStyle = cols[(k + i) % cols.length]; ctx.fillRect(x + 1 + (k % 3), y + 1 + i * 2, w, 1);
    }
    if (Math.floor(t / 500) % 2) { ctx.fillStyle = '#ffffff'; ctx.fillRect(x + 12, y + 7, 2, 1); }
  } else if (st === 'idle') {
    ctx.fillStyle = '#6c8cff55'; ctx.fillRect(x + 2, y + 2, 12, 5); ctx.fillStyle = '#ffffff66'; ctx.fillRect(x + 6, y + 4, 4, 1);
  } else if (st === 'meeting') {
    ctx.fillStyle = '#ffffff33'; ctx.fillRect(x + 5, y + 3, 6, 3);
  }
}

// Product team
addDesk('p1', 19, 4, 'down'); addDesk('p2', 23, 4, 'down'); addDesk('p3', 27, 4, 'down');
addDesk('p4', 19, 5, 'up'); addDesk('p5', 23, 5, 'up'); addDesk('p6', 27, 5, 'up');
// Engineering
addDesk('e1', 35, 4, 'down'); addDesk('e2', 39, 4, 'down'); addDesk('e3', 43, 4, 'down');
addDesk('e4', 35, 5, 'up'); addDesk('e5', 39, 5, 'up'); addDesk('e6', 43, 5, 'up');
// Research
addDesk('r1', 35, 13, 'down'); addDesk('r2', 39, 13, 'down'); addDesk('r3', 43, 13, 'down');
addDesk('r4', 35, 14, 'up'); addDesk('r5', 39, 14, 'up'); addDesk('r6', 43, 14, 'up');
// Claude's office
addDesk('boss', 8, 4, 'down');
place(deskLampImg(), 8 * T + 38, 4 * T - 6, 4 * T + 1);

function obj(img, tx, ty, opts = {}) {
  const x = tx * T + (opts.dx || 0), y = ty * T + (opts.dy || 0);
  place(img, x, y, opts.sortY ?? (y + img.height), opts.anim);
  if (opts.block) block(...opts.block);
}

// plants around pods and rooms
const big = plantImg(true), small = plantImg(false), bamboo = bambooImg();
obj(big, 17, 2, { dy: -10, block: [17, 2, 17, 2] }); obj(big, 31, 2, { dy: -10, block: [31, 2, 31, 2] });
obj(big, 33, 2, { dy: -10, block: [33, 2, 33, 2] }); obj(small, 47, 7, { dy: -4, block: [47, 7, 47, 7] });
obj(small, 17, 7, { dy: -4, block: [17, 7, 17, 7] }); obj(big, 47, 11, { dy: -10, block: [47, 11, 47, 11] });
obj(bamboo, 19, 12, { dy: -14, block: [19, 12, 19, 12] }); obj(bamboo, 30, 12, { dy: -14, block: [30, 12, 30, 12] });
obj(big, 13, 2, { dy: -10, block: [13, 2, 13, 2] }); obj(small, 5, 8, { dy: -4, block: [5, 8, 5, 8] });
obj(big, 16, 21, { dy: -10, block: [16, 21, 16, 21] }); obj(big, 32, 21, { dy: -10, block: [32, 21, 32, 21] });
obj(big, 47, 29, { dy: -10, block: [47, 29, 47, 29] }); obj(big, 34, 29, { dy: -10, block: [34, 29, 34, 29] });
obj(small, 5, 29, { dy: -4, block: [5, 29, 5, 29] }); obj(small, 31, 17, { dy: -4, block: [31, 17, 31, 17] });
obj(small, 34, 17, { dy: -4, block: [34, 17, 34, 17] }); obj(small, 16, 9, { dy: -4, block: [16, 9, 16, 9] });

// Claude's office: bookshelf, guest chairs, sofa
obj(shelfImg(3), 5, 1, { dy: -14, block: [5, 1, 7, 1] }); obj(shelfImg(2), 10, 1, { dy: -14, block: [10, 1, 11, 1] });
obj(armchairImg('#d97757', '#b25d40'), 8, 7, { block: [8, 7, 8, 7] }); obj(armchairImg('#d97757', '#b25d40'), 10, 7, { block: [10, 7, 10, 7] });
obj(sofaImg(3, '#7a8bd1', '#5d6db3', 'down'), 11, 4, { dy: -2, block: [11, 4, 13, 4] });

// Kitchen
obj(counterImg(7), 5, 11, { dy: -8, block: [5, 11, 11, 11] }); obj(fridgeImg(), 13, 11, { dy: -14, block: [13, 11, 13, 11] });
obj(coolerImg(), 13, 18, { dy: -10, block: [13, 18, 13, 18] });
obj(tableImg(3, 2, '#e9c99a', '#b88d5c'), 7, 14, { block: [7, 14, 9, 15] });
for (const [x, y, dir] of [[7, 13, 'down'], [9, 13, 'down'], [7, 16, 'up'], [9, 16, 'up']]) {
  obj(dir === 'down' ? seatImgDown : seatImgUp, x, y, { dx: 1, dy: dir === 'down' ? 1 : 3, sortY: y * T + (dir === 'down' ? 4 : 17) });
  idleSpots.push({ x, y, dir, sit: true, name: 'kitchen table' });
}
idleSpots.push({ x: 12, y: 18, dir: 'right', sit: false, name: 'water cooler' }, { x: 9, y: 12, dir: 'up', sit: false, name: 'coffee machine' });

// Library
obj(shelfImg(4), 5, 21, { dy: -14, block: [5, 21, 8, 21] }); obj(shelfImg(4), 10, 21, { dy: -14, block: [10, 21, 13, 21] });
obj(armchairImg('#5d8f7a', '#467060'), 8, 25, { block: [8, 25, 8, 25] }); obj(armchairImg('#5d8f7a', '#467060'), 11, 25, { block: [11, 25, 11, 25] });
obj(tableImg(1, 1, '#c48d61', '#8f6040'), 9, 27, { block: [9, 27, 10, 27] });
obj(lampImg(), 6, 26, { dy: -10, block: [6, 26, 6, 26] }); obj(beanbagImg('#e56b8a'), 12, 28); obj(beanbagImg('#f4c95d'), 7, 29);
idleSpots.push({ x: 8, y: 26, dir: 'up', sit: false, name: 'library' }, { x: 11, y: 26, dir: 'up', sit: false, name: 'library' });

// Lounge
obj(pingpongImg(), 22, 14, { block: [22, 14, 25, 15] });
obj(tvImg(3), 23, 12, { dy: -6, block: [23, 12, 25, 12] });
obj(sofaImg(3, '#f0a35e', '#d6843f', 'up'), 20, 18, { dy: -2, block: [20, 18, 22, 18] });
obj(sofaImg(3, '#f0a35e', '#d6843f', 'up'), 26, 18, { dy: -2, block: [26, 18, 28, 18] });
obj(armchairImg('#f0a35e', '#d6843f'), 28, 14, { block: [28, 14, 28, 14] }); obj(beanbagImg('#6c8cff'), 20, 14);
idleSpots.push(
  { x: 21, y: 17, dir: 'down', sit: false, name: 'sofa' }, { x: 27, y: 17, dir: 'down', sit: false, name: 'sofa' },
  { x: 21, y: 15, dir: 'right', sit: false, name: 'ping-pong' }, { x: 26, y: 14, dir: 'left', sit: false, name: 'ping-pong' },
  { x: 24, y: 13, dir: 'up', sit: false, name: 'TV' },
);

// Reception
obj(receptionImg(), 22, 23, { dy: -8, block: [22, 23, 26, 23] });
obj(sofaImg(3, '#7a8bd1', '#5d6db3', 'up'), 17, 28, { dy: -2, block: [17, 28, 19, 28] });
obj(small, 21, 23, { dy: -4, block: [21, 23, 21, 23] }); obj(small, 27, 23, { dy: -4, block: [27, 23, 27, 23] });
obj(armchairImg('#7a8bd1', '#5d6db3'), 29, 27, { block: [29, 27, 29, 27] }); obj(armchairImg('#7a8bd1', '#5d6db3'), 30, 27, { block: [30, 27, 30, 27] });
spots.spawn = { x: 24, y: 27, dir: 'up' };
idleSpots.push({ x: 18, y: 27, dir: 'down', sit: false, name: 'reception sofa' });

// Meeting room: long table with seats on both sides and both ends
obj(tableImg(7, 3, '#f6f7fb', '#c3c8d8'), 38, 24, { block: [38, 24, 44, 26] });
obj(whiteboardImg(5), 39, 21, { dy: -12, sortY: 21 * T });
for (let x = 38; x <= 44; x++) {
  obj(seatImgDown, x, 23, { dx: 1, dy: 1, sortY: 23 * T + 4 }); meetingSeats.push({ x, y: 23, dir: 'down' });
  obj(seatImgUp, x, 27, { dx: 1, dy: 3, sortY: 27 * T + 17 }); meetingSeats.push({ x, y: 27, dir: 'up' });
}
spots.meetingHead = { x: 37, y: 25, dir: 'right' };   // the owner's place
spots.meetingChair = { x: 45, y: 25, dir: 'left' };   // Claude chairs from the other end
obj(bushImg(), 46, 21, { dy: 2, block: [46, 21, 47, 21] });

// outside
for (const [x, y] of [[0, 1], [1, 7], [0, 13], [1, 19], [0, 25], [1, 29]]) obj(treeImg(), x, y, { dx: -2, dy: -8, block: [x, y + 1, x + 1, y + 1] });
for (const [x, y] of [[2, 5], [0, 11], [2, 17], [1, 23], [2, 27]]) obj(bushImg(), x, y);

// ------------------------------------------------------------------ floor layer (static)
function floorTile(g, x, y, type) {
  const X = x * T, Y = y * T, p = (a, b, w, h, c) => { g.fillStyle = c; g.fillRect(X + a, Y + b, w, h); };
  const n = (x * 73856093 ^ y * 19349663) >>> 0;
  switch (type) {
    case 'grass':
      p(0, 0, 16, 16, '#78c25f');
      if (n % 3 === 0) p(n % 13, (n >> 3) % 13, 1, 2, '#5fa84a');
      if (n % 5 === 0) p((n >> 4) % 14, (n >> 6) % 14, 1, 2, '#5fa84a');
      if (n % 17 === 0) { p((n >> 2) % 12 + 2, (n >> 5) % 12 + 2, 2, 2, ['#f4c95d', '#ffffff', '#e56b8a'][n % 3]); }
      break;
    case 'wood': {
      p(0, 0, 16, 16, '#ead6ad');
      p(0, 0, 16, 1, '#dcc597'); p(0, 8, 16, 1, '#dcc597');
      const s = (y % 2) * 8; p((4 + s) % 16, 1, 1, 7, '#dcc597'); p((12 + s) % 16, 9, 1, 7, '#dcc597');
      if (n % 7 === 0) p(n % 12 + 2, (n >> 3) % 6 + 2, 3, 1, '#e2cc9f');
      break;
    }
    case 'carpetG': p(0, 0, 16, 16, '#9aa1b3'); if ((x + y) % 2) p(7, 7, 2, 2, '#8f96a8'); break;
    case 'carpetB': p(0, 0, 16, 16, '#5f6fa6'); if ((x + y) % 2) p(7, 7, 2, 2, '#56659a'); break;
    case 'carpetP': p(0, 0, 16, 16, '#7d6aa6'); if ((x + y) % 2) p(7, 7, 2, 2, '#725f99'); break;
    case 'tile': p(0, 0, 16, 16, (x + y) % 2 ? '#e9eef1' : '#d7dee3'); p(0, 0, 16, 1, '#c9d2d8'); p(0, 0, 1, 16, '#c9d2d8'); break;
    case 'meet': p(0, 0, 16, 16, '#a9bfcc'); if ((x + y) % 2) p(6, 6, 4, 4, '#a1b7c4'); break;
    case 'rug': p(0, 0, 16, 16, '#6e5fa8'); if ((x * 3 + y) % 4 === 0) p(5, 5, 6, 6, '#7c6db8'); break;
    case 'rugB': p(0, 0, 16, 16, '#7486c4'); p(0, 7, 16, 2, '#8395d1'); break;
    case 'rugP': p(0, 0, 16, 16, '#b07aa8'); p(7, 0, 2, 16, '#bf8bb7'); break;
    case 'mat': p(0, 0, 16, 16, '#5a5f73'); p(1, 1, 14, 14, '#6b7088'); break;
    case 'wall': break;
  }
}
function wallTile(g, x, y) {
  const X = x * T, Y = y * T;
  const below = y + 1 < H && floor[at(x, y + 1)] !== 'wall';
  g.fillStyle = '#434a6b'; g.fillRect(X, Y, 16, 16);
  g.fillStyle = '#58608a'; g.fillRect(X, Y, 16, 3);
  if (below) {
    g.fillStyle = '#353b58'; g.fillRect(X, Y + 5, 16, 11);
    g.fillStyle = '#2e3350'; g.fillRect(X, Y + 15, 16, 1);
    g.fillStyle = '#3d4463'; g.fillRect(X, Y + 5, 16, 1);
    // windows on the outer north wall
    if (y === 0 && x % 4 === 1 && x > 15 && x < 48) {
      g.fillStyle = '#2a2f47'; g.fillRect(X + 1, Y + 4, 14, 11);
      g.fillStyle = '#8fd0f3'; g.fillRect(X + 2, Y + 5, 12, 9);
      g.fillStyle = '#c4ecff'; g.fillRect(X + 3, Y + 6, 4, 3);
      g.fillStyle = '#2a2f47'; g.fillRect(X + 7, Y + 5, 1, 9);
    }
  }
}
export function buildFloorLayer() {
  const c = document.createElement('canvas'); c.width = W * T; c.height = H * T;
  const g = c.getContext('2d');
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) floorTile(g, x, y, floor[at(x, y)]);
  // rug borders
  const border = (x0, y0, x1, y1, col) => { g.strokeStyle = col; g.lineWidth = 2; g.strokeRect(x0 * T + 1, y0 * T + 1, (x1 - x0 + 1) * T - 2, (y1 - y0 + 1) * T - 2); };
  border(19, 12, 30, 19, '#8d7fd0'); border(7, 5, 12, 8, '#93a3dd'); border(7, 24, 12, 28, '#cf9ac7'); border(34, 21, 48, 30, '#bcd0dc');
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (floor[at(x, y)] === 'wall') wallTile(g, x, y);
  // a sign by the entrance
  g.fillStyle = '#2a2f47'; g.fillRect(20 * T + 4, 31 * T + 4, 2 * T, 8);
  return c;
}

// ------------------------------------------------------------------ path finding (BFS on tiles)
export function findPath(sx, sy, tx, ty) {
  if (sx === tx && sy === ty) return [];
  const prev = new Int32Array(W * H).fill(-1), start = at(sx, sy), goal = at(tx, ty);
  const q = [start]; prev[start] = start;
  const free = (x, y) => isWalkable(x, y) || at(x, y) === goal;
  while (q.length) {
    const cur = q.shift();
    if (cur === goal) break;
    const cx = cur % W, cy = (cur / W) | 0;
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const nx = cx + dx, ny = cy + dy;
      if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
      const ni = at(nx, ny);
      if (prev[ni] !== -1 || !free(nx, ny)) continue;
      prev[ni] = cur; q.push(ni);
    }
  }
  if (prev[goal] === -1) return null;
  const path = [];
  for (let c = goal; c !== start; c = prev[c]) path.push({ x: c % W, y: (c / W) | 0 });
  return path.reverse();
}
