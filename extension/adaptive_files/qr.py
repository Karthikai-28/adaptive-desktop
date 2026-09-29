"""QR code encoder: byte mode, error correction level M, versions 1-40.

A Python port of shell/adaptive-shell@local/qrcode.js (itself after Project
Nayuki's reference implementation), for the Share dialog's "scan to download"
code. Nothing on this machine encodes QR codes from Python.

encode(text) -> list of rows of booleans (True = dark), no quiet zone.
"""

ECC_CODEWORDS_PER_BLOCK = [-1,
    10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
    26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28]
NUM_ERROR_CORRECTION_BLOCKS = [-1,
    1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
    17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49]
FORMAT_BITS_M = 0


def _bit(value, i):
    return (value >> i) & 1 != 0


def _raw_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        align = ver // 7 + 2
        result -= (25 * align - 10) * align - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver):
    return _raw_modules(ver) // 8 - ECC_CODEWORDS_PER_BLOCK[ver] * NUM_ERROR_CORRECTION_BLOCKS[ver]


def _rs_multiply(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree):
    result = [0] * degree
    result[-1] = 1
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _rs_multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _rs_multiply(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _rs_multiply(coef, factor)
    return result


def encode(text):
    data_bytes = text.encode("utf-8")

    ver = 1
    while ver <= 40:
        count_bits = 8 if ver <= 9 else 16
        if 4 + count_bits + len(data_bytes) * 8 <= _data_codewords(ver) * 8:
            break
        ver += 1
    if ver > 40:
        raise ValueError("text too long for a QR code")

    bits = []

    def push(value, length):
        for i in range(length - 1, -1, -1):
            bits.append((value >> i) & 1)

    push(0x4, 4)
    push(len(data_bytes), 8 if ver <= 9 else 16)
    for b in data_bytes:
        push(b, 8)
    capacity = _data_codewords(ver) * 8
    push(0, min(4, capacity - len(bits)))
    push(0, (8 - len(bits) % 8) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        push(pad, 8)
        pad ^= 0xEC ^ 0x11

    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

    num_blocks = NUM_ERROR_CORRECTION_BLOCKS[ver]
    ecc_len = ECC_CODEWORDS_PER_BLOCK[ver]
    raw = _raw_modules(ver) // 8
    num_short = num_blocks - raw % num_blocks
    short_len = raw // num_blocks
    divisor = _rs_divisor(ecc_len)

    blocks = []
    k = 0
    for i in range(num_blocks):
        length = short_len - ecc_len + (0 if i < num_short else 1)
        dat = data[k:k + length]
        k += length
        ecc = _rs_remainder(dat, divisor)
        if i < num_short:
            dat = dat + [0]
        blocks.append(dat + ecc)

    codewords = []
    for i in range(len(blocks[0])):
        for j, block in enumerate(blocks):
            if i != short_len - ecc_len or j >= num_short:
                codewords.append(block[i])

    return _Matrix(ver, codewords).modules


class _Matrix:
    def __init__(self, ver, codewords):
        self.version = ver
        self.size = ver * 4 + 17
        self.modules = [[False] * self.size for _ in range(self.size)]
        self.function = [[False] * self.size for _ in range(self.size)]

        self._function_patterns()
        self._codewords(codewords)

        best, best_penalty = 0, None
        for mask in range(8):
            self._mask(mask)
            self._format(mask)
            penalty = self._penalty()
            if best_penalty is None or penalty < best_penalty:
                best, best_penalty = mask, penalty
            self._mask(mask)
        self._mask(best)
        self._format(best)

    def _set(self, x, y, dark):
        self.modules[y][x] = dark
        self.function[y][x] = True

    def _function_patterns(self):
        size = self.size
        for i in range(size):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for x, y in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < size and 0 <= yy < size:
                        dist = max(abs(dx), abs(dy))
                        self._set(xx, yy, dist not in (2, 4))
        positions = self._alignment_positions()
        n = len(positions)
        for i in range(n):
            for j in range(n):
                if (i, j) in ((0, 0), (0, n - 1), (n - 1, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(positions[i] + dx, positions[j] + dy, max(abs(dx), abs(dy)) != 1)
        self._format(0)
        self._version()

    def _alignment_positions(self):
        ver = self.version
        if ver == 1:
            return []
        align = ver // 7 + 2
        step = 26 if ver == 32 else -(-(ver * 4 + 4) // (align * 2 - 2)) * 2
        result = [6]
        pos = self.size - 7
        while len(result) < align:
            result.insert(1, pos)
            pos -= step
        return result

    def _format(self, mask):
        data = (FORMAT_BITS_M << 3) | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = ((data << 10) | rem) ^ 0x5412
        for i in range(6):
            self._set(8, i, _bit(bits, i))
        self._set(8, 7, _bit(bits, 6))
        self._set(8, 8, _bit(bits, 7))
        self._set(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self._set(14 - i, 8, _bit(bits, i))
        size = self.size
        for i in range(8):
            self._set(size - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self._set(8, size - 15 + i, _bit(bits, i))
        self._set(8, size - 8, True)

    def _version(self):
        ver = self.version
        if ver < 7:
            return
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = (ver << 12) | rem
        for i in range(18):
            bit = _bit(bits, i)
            a = self.size - 11 + i % 3
            b = i // 3
            self._set(a, b, bit)
            self._set(b, a, bit)

    def _codewords(self, data):
        size = self.size
        i = 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = size - 1 - vert if upward else vert
                    if not self.function[y][x] and i < len(data) * 8:
                        self.modules[y][x] = _bit(data[i >> 3], 7 - (i & 7))
                        i += 1
            right -= 2

    def _mask(self, mask):
        for y in range(self.size):
            for x in range(self.size):
                if self.function[y][x]:
                    continue
                if mask == 0:
                    invert = (x + y) % 2 == 0
                elif mask == 1:
                    invert = y % 2 == 0
                elif mask == 2:
                    invert = x % 3 == 0
                elif mask == 3:
                    invert = (x + y) % 3 == 0
                elif mask == 4:
                    invert = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    invert = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    invert = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    invert = ((x + y) % 2 + x * y % 3) % 2 == 0
                if invert:
                    self.modules[y][x] = not self.modules[y][x]

    def _penalty(self):
        size = self.size
        m = self.modules
        result = 0
        for y in range(size):
            for horizontal in (True, False):
                run = 1
                for i in range(1, size):
                    a = m[y][i] if horizontal else m[i][y]
                    b = m[y][i - 1] if horizontal else m[i - 1][y]
                    if a == b:
                        run += 1
                    else:
                        if run >= 5:
                            result += run - 2
                        run = 1
                if run >= 5:
                    result += run - 2
        dark = 0
        for y in range(size):
            for x in range(size):
                if m[y][x]:
                    dark += 1
                if x < size - 1 and y < size - 1 and m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    result += 3
        total = size * size
        result += abs(dark * 20 - total * 10) // total * 10
        return result
