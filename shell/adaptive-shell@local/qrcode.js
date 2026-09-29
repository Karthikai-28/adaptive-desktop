// Adaptive QR code encoder
//
// Nothing on this system encodes QR codes (no qrencode, no Python qrcode), and
// the Control Center needs one to share a Wi-Fi network with a phone. This is
// the standard algorithm - byte mode, error correction level M, versions 1-40,
// all eight masks tried - after Project Nayuki's reference implementation,
// reduced to what a short WIFI: string needs.
//
// encode(text) returns { size, isDark(x, y) }. QrCodeActor draws one.

/* exported encode, QrCodeActor */

const { Clutter, GObject, St } = imports.gi;

// Error correction level M. Index 0 is unused so the version is the index.
const ECC_CODEWORDS_PER_BLOCK = [-1,
    10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
    26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28];
const NUM_ERROR_CORRECTION_BLOCKS = [-1,
    1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
    17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49];
const FORMAT_BITS_M = 0;

function getBit(value, i) {
    return ((value >>> i) & 1) !== 0;
}

function numRawDataModules(ver) {
    let result = (16 * ver + 128) * ver + 64;
    if (ver >= 2) {
        const numAlign = Math.floor(ver / 7) + 2;
        result -= (25 * numAlign - 10) * numAlign - 55;
        if (ver >= 7)
            result -= 36;
    }
    return result;
}

function numDataCodewords(ver) {
    return Math.floor(numRawDataModules(ver) / 8) -
        ECC_CODEWORDS_PER_BLOCK[ver] * NUM_ERROR_CORRECTION_BLOCKS[ver];
}

// Reed-Solomon over GF(2^8) with the QR polynomial 0x11D.
function rsMultiply(x, y) {
    let z = 0;
    for (let i = 7; i >= 0; i--) {
        z = (z << 1) ^ ((z >>> 7) * 0x11D);
        z ^= ((y >>> i) & 1) * x;
    }
    return z & 0xFF;
}

function rsDivisor(degree) {
    const result = new Array(degree).fill(0);
    result[degree - 1] = 1;
    let root = 1;
    for (let i = 0; i < degree; i++) {
        for (let j = 0; j < result.length; j++) {
            result[j] = rsMultiply(result[j], root);
            if (j + 1 < result.length)
                result[j] ^= result[j + 1];
        }
        root = rsMultiply(root, 0x02);
    }
    return result;
}

function rsRemainder(data, divisor) {
    const result = divisor.map(() => 0);
    for (const b of data) {
        const factor = b ^ result.shift();
        result.push(0);
        divisor.forEach((coef, i) => {
            result[i] ^= rsMultiply(coef, factor);
        });
    }
    return result;
}

function utf8Bytes(text) {
    return Array.from(new TextEncoder().encode(text));
}

function encode(text) {
    const bytes = utf8Bytes(text);

    // Smallest version that holds the data.
    let ver = 1;
    for (; ver <= 40; ver++) {
        const countBits = ver <= 9 ? 8 : 16;
        if (4 + countBits + bytes.length * 8 <= numDataCodewords(ver) * 8)
            break;
    }
    if (ver > 40)
        throw new Error('Text too long for a QR code');

    // Data bits: byte mode, length, payload, terminator, padding.
    const bits = [];
    const push = (value, len) => {
        for (let i = len - 1; i >= 0; i--)
            bits.push((value >>> i) & 1);
    };
    push(0x4, 4);
    push(bytes.length, ver <= 9 ? 8 : 16);
    for (const b of bytes)
        push(b, 8);

    const capacity = numDataCodewords(ver) * 8;
    push(0, Math.min(4, capacity - bits.length));
    push(0, (8 - bits.length % 8) % 8);
    for (let pad = 0xEC; bits.length < capacity; pad ^= 0xEC ^ 0x11)
        push(pad, 8);

    const data = [];
    for (let i = 0; i < bits.length; i += 8)
        data.push(parseInt(bits.slice(i, i + 8).join(''), 2));

    // Split into blocks, add error correction, interleave.
    const numBlocks = NUM_ERROR_CORRECTION_BLOCKS[ver];
    const blockEccLen = ECC_CODEWORDS_PER_BLOCK[ver];
    const rawCodewords = Math.floor(numRawDataModules(ver) / 8);
    const numShortBlocks = numBlocks - rawCodewords % numBlocks;
    const shortBlockLen = Math.floor(rawCodewords / numBlocks);
    const divisor = rsDivisor(blockEccLen);

    const blocks = [];
    for (let i = 0, k = 0; i < numBlocks; i++) {
        const dat = data.slice(k, k + shortBlockLen - blockEccLen + (i < numShortBlocks ? 0 : 1));
        k += dat.length;
        const ecc = rsRemainder(dat, divisor);
        if (i < numShortBlocks)
            dat.push(0);
        blocks.push(dat.concat(ecc));
    }

    const codewords = [];
    for (let i = 0; i < blocks[0].length; i++) {
        blocks.forEach((block, j) => {
            if (i !== shortBlockLen - blockEccLen || j >= numShortBlocks)
                codewords.push(block[i]);
        });
    }

    return new Matrix(ver, codewords);
}

class Matrix {
    constructor(ver, codewords) {
        this.version = ver;
        this.size = ver * 4 + 17;
        this._modules = [];
        this._function = [];
        for (let i = 0; i < this.size; i++) {
            this._modules.push(new Array(this.size).fill(false));
            this._function.push(new Array(this.size).fill(false));
        }

        this._drawFunctionPatterns();
        this._drawCodewords(codewords);

        // Try every mask and keep the one with the lowest penalty.
        let best = 0;
        let bestPenalty = Infinity;
        for (let mask = 0; mask < 8; mask++) {
            this._applyMask(mask);
            this._drawFormatBits(mask);
            const penalty = this._penalty();
            if (penalty < bestPenalty) {
                best = mask;
                bestPenalty = penalty;
            }
            this._applyMask(mask);
        }
        this._applyMask(best);
        this._drawFormatBits(best);
    }

    isDark(x, y) {
        return this._modules[y][x];
    }

    _set(x, y, dark) {
        this._modules[y][x] = dark;
        this._function[y][x] = true;
    }

    _drawFunctionPatterns() {
        const size = this.size;
        for (let i = 0; i < size; i++) {
            this._set(6, i, i % 2 === 0);
            this._set(i, 6, i % 2 === 0);
        }

        this._drawFinder(3, 3);
        this._drawFinder(size - 4, 3);
        this._drawFinder(3, size - 4);

        const positions = this._alignmentPositions();
        const n = positions.length;
        for (let i = 0; i < n; i++) {
            for (let j = 0; j < n; j++) {
                if ((i === 0 && j === 0) || (i === 0 && j === n - 1) || (i === n - 1 && j === 0))
                    continue;
                this._drawAlignment(positions[i], positions[j]);
            }
        }

        this._drawFormatBits(0);
        this._drawVersion();
    }

    _drawFinder(x, y) {
        for (let dy = -4; dy <= 4; dy++) {
            for (let dx = -4; dx <= 4; dx++) {
                const dist = Math.max(Math.abs(dx), Math.abs(dy));
                const xx = x + dx;
                const yy = y + dy;
                if (xx >= 0 && xx < this.size && yy >= 0 && yy < this.size)
                    this._set(xx, yy, dist !== 2 && dist !== 4);
            }
        }
    }

    _drawAlignment(x, y) {
        for (let dy = -2; dy <= 2; dy++) {
            for (let dx = -2; dx <= 2; dx++)
                this._set(x + dx, y + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
        }
    }

    _alignmentPositions() {
        const ver = this.version;
        if (ver === 1)
            return [];
        const numAlign = Math.floor(ver / 7) + 2;
        const step = ver === 32 ? 26
            : Math.ceil((ver * 4 + 4) / (numAlign * 2 - 2)) * 2;
        const result = [6];
        for (let pos = this.size - 7; result.length < numAlign; pos -= step)
            result.splice(1, 0, pos);
        return result;
    }

    _drawFormatBits(mask) {
        const data = (FORMAT_BITS_M << 3) | mask;
        let rem = data;
        for (let i = 0; i < 10; i++)
            rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
        const bits = ((data << 10) | rem) ^ 0x5412;

        for (let i = 0; i <= 5; i++)
            this._set(8, i, getBit(bits, i));
        this._set(8, 7, getBit(bits, 6));
        this._set(8, 8, getBit(bits, 7));
        this._set(7, 8, getBit(bits, 8));
        for (let i = 9; i < 15; i++)
            this._set(14 - i, 8, getBit(bits, i));

        const size = this.size;
        for (let i = 0; i < 8; i++)
            this._set(size - 1 - i, 8, getBit(bits, i));
        for (let i = 8; i < 15; i++)
            this._set(8, size - 15 + i, getBit(bits, i));
        this._set(8, size - 8, true);
    }

    _drawVersion() {
        const ver = this.version;
        if (ver < 7)
            return;
        let rem = ver;
        for (let i = 0; i < 12; i++)
            rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
        const bits = (ver << 12) | rem;
        for (let i = 0; i < 18; i++) {
            const bit = getBit(bits, i);
            const a = this.size - 11 + i % 3;
            const b = Math.floor(i / 3);
            this._set(a, b, bit);
            this._set(b, a, bit);
        }
    }

    _drawCodewords(data) {
        const size = this.size;
        let i = 0;
        for (let right = size - 1; right >= 1; right -= 2) {
            if (right === 6)
                right = 5;
            for (let vert = 0; vert < size; vert++) {
                for (let j = 0; j < 2; j++) {
                    const x = right - j;
                    const upward = ((right + 1) & 2) === 0;
                    const y = upward ? size - 1 - vert : vert;
                    if (!this._function[y][x] && i < data.length * 8) {
                        this._modules[y][x] = getBit(data[i >>> 3], 7 - (i & 7));
                        i++;
                    }
                }
            }
        }
    }

    _applyMask(mask) {
        for (let y = 0; y < this.size; y++) {
            for (let x = 0; x < this.size; x++) {
                if (this._function[y][x])
                    continue;
                let invert;
                switch (mask) {
                case 0: invert = (x + y) % 2 === 0; break;
                case 1: invert = y % 2 === 0; break;
                case 2: invert = x % 3 === 0; break;
                case 3: invert = (x + y) % 3 === 0; break;
                case 4: invert = (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0; break;
                case 5: invert = x * y % 2 + x * y % 3 === 0; break;
                case 6: invert = (x * y % 2 + x * y % 3) % 2 === 0; break;
                default: invert = ((x + y) % 2 + x * y % 3) % 2 === 0; break;
                }
                if (invert)
                    this._modules[y][x] = !this._modules[y][x];
            }
        }
    }

    // Runs, 2x2 blocks and dark/light balance: enough of the standard's
    // penalty to steer away from masks that scan badly.
    _penalty() {
        const size = this.size;
        const m = this._modules;
        let result = 0;

        for (let y = 0; y < size; y++) {
            for (const horizontal of [true, false]) {
                let run = 1;
                for (let i = 1; i < size; i++) {
                    const a = horizontal ? m[y][i] : m[i][y];
                    const b = horizontal ? m[y][i - 1] : m[i - 1][y];
                    if (a === b) {
                        run++;
                    } else {
                        if (run >= 5)
                            result += run - 2;
                        run = 1;
                    }
                }
                if (run >= 5)
                    result += run - 2;
            }
        }

        let dark = 0;
        for (let y = 0; y < size; y++) {
            for (let x = 0; x < size; x++) {
                if (m[y][x])
                    dark++;
                if (x < size - 1 && y < size - 1 &&
                    m[y][x] === m[y][x + 1] && m[y][x] === m[y + 1][x] && m[y][x] === m[y + 1][x + 1])
                    result += 3;
            }
        }

        const total = size * size;
        result += Math.floor(Math.abs(dark * 20 - total * 10) / total) * 10;
        return result;
    }
}

// Dark modules on a white card with the standard four-module quiet zone -
// phones read a light code on a dark UI far more reliably than an inverted one.
var QrCodeActor = GObject.registerClass(
class QrCodeActor extends St.DrawingArea {
    _init(text, pixels = 180) {
        super._init({
            style_class: 'adaptive-qr',
            width: pixels,
            height: pixels,
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._matrix = encode(text);
    }

    vfunc_repaint() {
        const cr = this.get_context();
        const [width, height] = this.get_surface_size();
        const quiet = 4;
        const cells = this._matrix.size + quiet * 2;
        const scale = Math.min(width, height) / cells;

        cr.setSourceRGB(1, 1, 1);
        cr.rectangle(0, 0, width, height);
        cr.fill();

        cr.setSourceRGB(0, 0, 0);
        for (let y = 0; y < this._matrix.size; y++) {
            for (let x = 0; x < this._matrix.size; x++) {
                if (this._matrix.isDark(x, y))
                    cr.rectangle((x + quiet) * scale, (y + quiet) * scale, scale + 0.3, scale + 0.3);
            }
        }
        cr.fill();
        cr.$dispose();
    }
});
