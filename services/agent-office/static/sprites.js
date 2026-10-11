// Pixel characters, drawn procedurally. 16x22 sprite, anchored at the feet (bottom centre).
const cache = new Map();

function shade(hex, f) {
  const n = parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map(v => Math.max(0, Math.min(255, Math.round(v * f))));
  return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
}

// dir: down | up | left | right ; frame: 0 standing, 1/2 walking ; sitting hides the legs
function render(look, dir, frame, sitting, badge) {
  const c = document.createElement('canvas'); c.width = 16; c.height = 22;
  const g = c.getContext('2d');
  const p = (x, y, w, h, col) => { g.fillStyle = col; g.fillRect(x, y, w, h); };
  const skin = look.skin, skinD = shade(skin, 0.85), hair = look.hair, hairD = shade(hair, 0.75);
  const shirt = look.shirt, shirtD = shade(shirt, 0.78), pants = look.pants || '#2f3550', shoe = '#22242e';
  const style = look.hairStyle || 'short';

  // shadow
  g.fillStyle = 'rgba(0,0,0,0.22)'; g.fillRect(4, 21, 8, 1); g.fillRect(3, 20, 10, 1);

  // legs
  if (!sitting) {
    const l = frame === 1 ? -1 : 0, r = frame === 2 ? -1 : 0;
    if (dir === 'left' || dir === 'right') {
      const a = frame === 1 ? 1 : frame === 2 ? -1 : 0;
      p(6 + a, 16, 2, 4, pants); p(8 - a, 16, 2, 4, shade(pants, 0.85));
      p(6 + a, 19, 3, 1, shoe); p(8 - a, 19, 3, 1, shoe);
    } else {
      p(5, 16, 2, 4 + l, pants); p(9, 16, 2, 4 + r, pants);
      p(5, 19 + l, 2, 1, shoe); p(9, 19 + r, 2, 1, shoe);
    }
  } else {
    p(5, 16, 6, 2, pants);
  }

  // body
  p(4, 11, 8, 6, shirt); p(4, 16, 8, 1, shirtD);
  if (dir === 'down') { p(7, 11, 2, 1, skinD); }
  if (badge) { p(dir === 'up' ? 0 : 9, 13, 2, 2, '#fff7e6'); if (dir !== 'up') p(9, 12, 1, 1, '#ffe08a'); }
  // arms
  const swing = sitting ? 0 : frame === 1 ? 1 : frame === 2 ? -1 : 0;
  if (dir === 'left') { p(6, 12, 2, 4, shirtD); p(6, 16 + swing, 2, 1, skin); }
  else if (dir === 'right') { p(8, 12, 2, 4, shirtD); p(8, 16 + swing, 2, 1, skin); }
  else { p(3, 12, 1, 4, shirtD); p(12, 12, 1, 4, shirtD); p(3, 16 + swing, 1, 1, skin); p(12, 16 - swing, 1, 1, skin); }

  // head
  p(4, 3, 8, 8, skin); p(4, 10, 8, 1, skinD);
  // hair
  if (style !== 'bald') {
    p(4, 2, 8, 3, hair); p(3, 3, 1, 4, hair); p(12, 3, 1, 4, hair); p(5, 1, 6, 1, hair);
    if (dir === 'up') { p(4, 3, 8, 7, hair); p(4, 9, 8, 1, hairD); }
    if (dir === 'left') { p(8, 3, 4, 5, hair); }
    if (dir === 'right') { p(4, 3, 4, 5, hair); }
    if (style === 'long') {
      if (dir === 'up') { p(3, 3, 10, 10, hair); p(4, 12, 8, 1, hairD); }
      else if (dir === 'down') { p(3, 4, 1, 9, hair); p(12, 4, 1, 9, hair); p(4, 4, 1, 2, hair); p(11, 4, 1, 2, hair); }
      else { p(dir === 'left' ? 9 : 3, 4, 4, 9, hair); }
    }
    if (style === 'bun') { p(6, -0, 4, 2, hair); p(7, 0, 2, 1, hairD); }
    if (style === 'curly') { p(3, 1, 10, 3, hair); p(2, 3, 1, 4, hair); p(13, 3, 1, 4, hair); p(4, 0, 2, 1, hair); p(10, 0, 2, 1, hair); p(7, 0, 2, 1, hair); }
    p(5, 2, 2, 1, shade(hair, 1.25));
  }
  // face
  if (dir === 'down') { p(6, 6, 1, 2, '#1d1d28'); p(9, 6, 1, 2, '#1d1d28'); p(5, 8, 1, 1, '#f0a0a0aa'); p(10, 8, 1, 1, '#f0a0a0aa'); p(7, 9, 2, 1, skinD); }
  else if (dir === 'left') { p(5, 6, 1, 2, '#1d1d28'); p(4, 8, 1, 1, '#f0a0a0aa'); }
  else if (dir === 'right') { p(10, 6, 1, 2, '#1d1d28'); p(11, 8, 1, 1, '#f0a0a0aa'); }
  return c;
}

export function sprite(look, dir, frame, sitting, badge) {
  const key = JSON.stringify([look, dir, frame, sitting, badge]);
  let c = cache.get(key);
  if (!c) { c = render(look, dir, frame, sitting, badge); cache.set(key, c); }
  return c;
}

// A crisp portrait for the side panel
export function portrait(look, size = 48, badge = false) {
  const c = document.createElement('canvas'); c.width = size; c.height = size;
  const g = c.getContext('2d'); g.imageSmoothingEnabled = false;
  const s = sprite(look, 'down', 0, false, badge);
  const k = Math.floor(size / 14);
  g.drawImage(s, 0, 0, 16, 15, Math.round((size - 16 * k) / 2), Math.round(size * 0.12), 16 * k, 15 * k);
  return c;
}
