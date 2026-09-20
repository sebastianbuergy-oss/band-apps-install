"""A QR encoder in the standard library, because the OTA page needs one.

Sebastian's HP has no pip mirror we want to depend on for a build system, so
this is byte-mode QR (versions 1-10, all four error-correction levels)
written out in full.  It renders to SVG and to PNG, both without Pillow.

Correctness is not taken on faith:

* the codeword totals are *derived from the module geometry*, not typed in,
  and the block table is asserted against them (:func:`self_check`);
* the tests decode the finished matrix back to the input string and verify
  the Reed-Solomon syndromes are zero.

A QR symbol is still only DEVICE VERIFIED once someone scans one.
"""
from __future__ import annotations

from typing import Iterable

from .errors import ValidationError

# --------------------------------------------------------------------------
# Galois field GF(256), primitive polynomial 0x11D
# --------------------------------------------------------------------------
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator(degree: int) -> list:
    poly = [1]
    for i in range(degree):
        poly = _poly_mul(poly, [1, _EXP[i]])
    return poly


def _poly_mul(a: list, b: list) -> list:
    out = [0] * (len(a) + len(b) - 1)
    for i, av in enumerate(a):
        if av == 0:
            continue
        for j, bv in enumerate(b):
            out[i + j] ^= _mul(av, bv)
    return out


def rs_encode(data: Iterable[int], ec_len: int) -> list:
    """Reed-Solomon parity for ``data``."""
    data = list(data)
    gen = _generator(ec_len)
    rem = [0] * ec_len
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        if factor:
            for i, g in enumerate(gen[1:]):
                rem[i] ^= _mul(g, factor)
    return rem


def rs_syndromes(codeword: Iterable[int], ec_len: int) -> list:
    """Syndromes of a full codeword.  All zero iff the codeword is valid.

    This is an independent check on :func:`rs_encode`: it evaluates the
    codeword polynomial at the roots the generator was built from, without
    reusing the encoder's own arithmetic path.
    """
    codeword = list(codeword)
    out = []
    for i in range(ec_len):
        root = _EXP[i]
        acc = 0
        for byte in codeword:           # Horner
            acc = _mul(acc, root) ^ byte
        out.append(acc)
    return out


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
MAX_VERSION = 10

ALIGNMENT_CENTERS = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}


def size_for(version: int) -> int:
    return version * 4 + 17


def _reserved(version: int) -> list:
    """Matrix of booleans: True where a data bit may not go."""
    size = size_for(version)
    res = [[False] * size for _ in range(size)]

    def fill(r0: int, c0: int, h: int, w: int) -> None:
        for r in range(r0, r0 + h):
            for c in range(c0, c0 + w):
                if 0 <= r < size and 0 <= c < size:
                    res[r][c] = True

    # Finder patterns plus their separators (8x8 including the white ring).
    fill(0, 0, 8, 8)
    fill(0, size - 8, 8, 8)
    fill(size - 8, 0, 8, 8)
    # Timing patterns.
    for i in range(size):
        res[6][i] = True
        res[i][6] = True
    # Format information (and the dark module, which sits inside it).
    for i in range(9):
        res[8][i] = True
        res[i][8] = True
    for i in range(8):
        res[8][size - 1 - i] = True
        res[size - 1 - i][8] = True
    # Alignment patterns, except where they would sit on a finder.
    centers = ALIGNMENT_CENTERS[version]
    for r in centers:
        for c in centers:
            if (r, c) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            fill(r - 2, c - 2, 5, 5)
    # Version information blocks (version 7 and up).
    if version >= 7:
        fill(size - 11, 0, 3, 6)
        fill(0, size - 11, 6, 3)
    return res


def total_codewords(version: int) -> int:
    """Derived from the geometry - never typed in from a table."""
    res = _reserved(version)
    free = sum(1 for row in res for cell in row if not cell)
    return free // 8


# (ec_per_block, [(block_count, data_codewords_per_block), ...])
BLOCKS: dict[tuple, tuple] = {
    (1, "L"): (7, [(1, 19)]),   (1, "M"): (10, [(1, 16)]),
    (1, "Q"): (13, [(1, 13)]),  (1, "H"): (17, [(1, 9)]),
    (2, "L"): (10, [(1, 34)]),  (2, "M"): (16, [(1, 28)]),
    (2, "Q"): (22, [(1, 22)]),  (2, "H"): (28, [(1, 16)]),
    (3, "L"): (15, [(1, 55)]),  (3, "M"): (26, [(1, 44)]),
    (3, "Q"): (18, [(2, 17)]),  (3, "H"): (22, [(2, 13)]),
    (4, "L"): (20, [(1, 80)]),  (4, "M"): (18, [(2, 32)]),
    (4, "Q"): (26, [(2, 24)]),  (4, "H"): (16, [(4, 9)]),
    (5, "L"): (26, [(1, 108)]), (5, "M"): (24, [(2, 43)]),
    (5, "Q"): (18, [(2, 15), (2, 16)]), (5, "H"): (22, [(2, 11), (2, 12)]),
    (6, "L"): (18, [(2, 68)]),  (6, "M"): (16, [(4, 27)]),
    (6, "Q"): (24, [(4, 19)]),  (6, "H"): (28, [(4, 15)]),
    (7, "L"): (20, [(2, 78)]),  (7, "M"): (18, [(4, 31)]),
    (7, "Q"): (18, [(2, 14), (4, 15)]), (7, "H"): (26, [(4, 13), (1, 14)]),
    (8, "L"): (24, [(2, 97)]),  (8, "M"): (22, [(2, 38), (2, 39)]),
    (8, "Q"): (22, [(4, 18), (2, 19)]), (8, "H"): (26, [(4, 14), (2, 15)]),
    (9, "L"): (30, [(2, 116)]), (9, "M"): (22, [(3, 36), (2, 37)]),
    (9, "Q"): (20, [(4, 16), (4, 17)]), (9, "H"): (24, [(4, 12), (4, 13)]),
    (10, "L"): (18, [(2, 68), (2, 69)]), (10, "M"): (26, [(4, 43), (1, 44)]),
    (10, "Q"): (24, [(6, 19), (2, 20)]), (10, "H"): (28, [(6, 15), (2, 16)]),
}

LEVELS = ("L", "M", "Q", "H")
_LEVEL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}


def self_check() -> None:
    """Every block entry must add up to the geometry-derived total."""
    for (version, level), (ec_len, groups) in sorted(BLOCKS.items()):
        blocks = sum(count for count, _ in groups)
        data = sum(count * size for count, size in groups)
        expected = total_codewords(version)
        got = blocks * ec_len + data
        if got != expected:
            raise AssertionError(
                f"QR block table wrong for version {version}{level}: "
                f"{blocks} blocks x {ec_len} ec + {data} data = {got}, "
                f"geometry says {expected}"
            )


self_check()


def data_capacity_bytes(version: int, level: str) -> int:
    """Payload bytes that fit, after mode and length headers."""
    ec_len, groups = BLOCKS[(version, level)]
    data_codewords = sum(count * size for count, size in groups)
    count_bits = 8 if version <= 9 else 16
    return (data_codewords * 8 - 4 - count_bits) // 8


def choose_version(payload: bytes, level: str, min_version: int = 1) -> int:
    for version in range(max(1, min_version), MAX_VERSION + 1):
        if len(payload) <= data_capacity_bytes(version, level):
            return version
    raise ValidationError(
        f"{len(payload)} Bytes passen bei Level {level} in keine QR-Version bis "
        f"{MAX_VERSION}. Kuerzere URL verwenden."
    )


# --------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------

class _Bits:
    def __init__(self) -> None:
        self.bits: list = []

    def add(self, value: int, length: int) -> None:
        for i in range(length - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def __len__(self) -> int:
        return len(self.bits)


def _encode_data(payload: bytes, version: int, level: str) -> list:
    ec_len, groups = BLOCKS[(version, level)]
    data_codewords = sum(count * size for count, size in groups)
    capacity_bits = data_codewords * 8
    bits = _Bits()
    bits.add(0b0100, 4)                                 # byte mode
    bits.add(len(payload), 8 if version <= 9 else 16)   # character count
    for byte in payload:
        bits.add(byte, 8)
    # Terminator, then pad to a byte boundary, then the alternating pad bytes.
    bits.add(0, min(4, capacity_bits - len(bits)))
    while len(bits) % 8:
        bits.add(0, 1)
    codewords = [
        int("".join(str(b) for b in bits.bits[i:i + 8]), 2)
        for i in range(0, len(bits), 8)
    ]
    for pad in _cycle_pads(data_codewords - len(codewords)):
        codewords.append(pad)
    return codewords


def _cycle_pads(count: int) -> list:
    pads = (0xEC, 0x11)
    return [pads[i % 2] for i in range(max(0, count))]


def _interleave(codewords: list, version: int, level: str) -> list:
    ec_len, groups = BLOCKS[(version, level)]
    blocks, ec_blocks, pos = [], [], 0
    for count, size in groups:
        for _ in range(count):
            block = codewords[pos:pos + size]
            pos += size
            blocks.append(block)
            ec_blocks.append(rs_encode(block, ec_len))
    out = []
    for i in range(max(len(b) for b in blocks)):
        for block in blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ec_len):
        for block in ec_blocks:
            out.append(block[i])
    return out


# --------------------------------------------------------------------------
# matrix
# --------------------------------------------------------------------------

def _draw_function_patterns(m: list, version: int) -> None:
    size = size_for(version)

    def finder(r0: int, c0: int) -> None:
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = r0 + r, c0 + c
                if not (0 <= rr < size and 0 <= cc < size):
                    continue
                inside = 0 <= r < 7 and 0 <= c < 7
                dark = inside and (
                    r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)
                )
                m[rr][cc] = 1 if dark else 0

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)
    for i in range(size):
        if m[6][i] is None:
            m[6][i] = 1 if i % 2 == 0 else 0
        if m[i][6] is None:
            m[i][6] = 1 if i % 2 == 0 else 0
    centers = ALIGNMENT_CENTERS[version]
    for cr in centers:
        for cc in centers:
            if (cr, cc) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    dark = max(abs(r), abs(c)) != 1
                    m[cr + r][cc + c] = 1 if dark else 0
    m[size - 8][8] = 1                                   # dark module


def _place_version_info(m: list, version: int) -> None:
    if version < 7:
        return
    size = size_for(version)
    rem = version
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    value = (version << 12) | rem
    for i in range(18):
        bit = (value >> i) & 1
        m[size - 11 + i % 3][i // 3] = bit
        m[i // 3][size - 11 + i % 3] = bit


def _format_bits(level: str, mask: int) -> int:
    value = (_LEVEL_BITS[level] << 3) | mask
    rem = value
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((value << 10) | rem) ^ 0x5412


def _place_format_info(m: list, level: str, mask: int) -> None:
    size = len(m)
    bits = _format_bits(level, mask)
    for i in range(15):
        bit = (bits >> i) & 1
        # Copy 1: around the top-left finder.
        if i < 6:
            m[8][i] = bit
        elif i == 6:
            m[8][7] = bit
        elif i == 7:
            m[8][8] = bit
        elif i == 8:
            m[7][8] = bit
        else:
            m[14 - i][8] = bit
        # Copy 2: split between the other two finders.
        if i < 8:
            m[8][size - 1 - i] = bit
        else:
            m[size - 15 + i][8] = bit


_MASKS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
)


def _place_data(m: list, reserved: list, bits: list) -> None:
    size = len(m)
    idx = 0
    upward = True
    col = size - 1
    while col > 0:
        if col == 6:            # the vertical timing pattern is not a column pair
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                m[row][c] = bits[idx] if idx < len(bits) else 0
                idx += 1
        upward = not upward
        col -= 2


def _penalty(m: list) -> int:
    size = len(m)
    score = 0
    # Rule 1: runs of five or more of the same colour.
    for line in list(m) + [list(col) for col in zip(*m)]:
        run, prev = 1, line[0]
        for cell in line[1:]:
            if cell == prev:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run, prev = 1, cell
        if run >= 5:
            score += 3 + (run - 5)
    # Rule 2: 2x2 blocks of one colour.
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    # Rule 3: the finder-lookalike pattern, with four light modules either side.
    pat_a = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pat_b = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(size - 10):
            window = list(line[i:i + 11])
            if window == pat_a or window == pat_b:
                score += 40
    # Rule 4: deviation from a 50/50 light/dark balance.
    dark = sum(cell for row in m for cell in row)
    percent = dark * 100 // (size * size)
    score += 10 * (abs(percent - 50) // 5)
    return score


def encode(text: str, level: str = "M", min_version: int = 1) -> list:
    """Return the QR matrix as a list of rows of 0/1."""
    if level not in LEVELS:
        raise ValidationError(f"unbekanntes Fehlerkorrektur-Level {level!r}")
    payload = text.encode("utf-8")
    version = choose_version(payload, level, min_version)
    size = size_for(version)
    codewords = _interleave(_encode_data(payload, version, level), version, level)
    bits = [(byte >> i) & 1 for byte in codewords for i in range(7, -1, -1)]

    reserved = _reserved(version)
    base = [[None] * size for _ in range(size)]
    _draw_function_patterns(base, version)
    _place_version_info(base, version)
    _place_data(base, reserved, bits)

    best, best_score = None, None
    for mask in range(8):
        candidate = [row[:] for row in base]
        for r in range(size):
            for c in range(size):
                if not reserved[r][c] and _MASKS[mask](r, c):
                    candidate[r][c] ^= 1
        _place_format_info(candidate, level, mask)
        score = _penalty(candidate)
        if best_score is None or score < best_score:
            best, best_score = candidate, score
    return best


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def to_svg(matrix: list, quiet_zone: int = 4, module: int = 8,
           dark: str = "#0b1220", light: str = "#ffffff") -> str:
    size = len(matrix)
    total = (size + 2 * quiet_zone) * module
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="{total}" '
        f'viewBox="0 0 {total} {total}" shape-rendering="crispEdges" role="img" '
        f'aria-label="QR-Code">',
        f'<rect width="{total}" height="{total}" fill="{light}"/>',
        f'<path fill="{dark}" d="',
    ]
    for r, row in enumerate(matrix):
        for c, cell in enumerate(row):
            if cell:
                x = (c + quiet_zone) * module
                y = (r + quiet_zone) * module
                parts.append(f"M{x} {y}h{module}v{module}h-{module}z")
    parts.append('"/></svg>')
    return "".join(parts)


def to_png(matrix: list, quiet_zone: int = 4, module: int = 8) -> bytes:
    """A 1-bit PNG written by hand - no Pillow on the build controller."""
    import struct
    import zlib

    size = len(matrix)
    width = (size + 2 * quiet_zone) * module
    rows = []
    blank = bytes([1] * width)
    for _ in range(quiet_zone * module):
        rows.append(blank)
    for row in matrix:
        line = bytearray()
        line.extend([1] * (quiet_zone * module))
        for cell in row:
            line.extend([0 if cell else 1] * module)
        line.extend([1] * (quiet_zone * module))
        for _ in range(module):
            rows.append(bytes(line))
    for _ in range(quiet_zone * module):
        rows.append(blank)

    raw = b"".join(b"\x00" + bytes(bytearray(
        (sum(r[i + k] << (7 - k) for k in range(8) if i + k < len(r))
         for i in range(0, len(r), 8))
    )) for r in rows)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, len(rows), 1, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def to_text(matrix: list, quiet_zone: int = 2) -> str:
    """Half-block rendering, for the terminal."""
    size = len(matrix)
    pad = [[0] * (size + 2 * quiet_zone) for _ in range(quiet_zone)]
    grid = pad + [[0] * quiet_zone + row + [0] * quiet_zone for row in matrix] + pad
    if len(grid) % 2:
        grid.append([0] * len(grid[0]))
    out = []
    for r in range(0, len(grid), 2):
        line = []
        for top, bottom in zip(grid[r], grid[r + 1]):
            line.append({(0, 0): " ", (1, 0): "▀", (0, 1): "▄",
                         (1, 1): "█"}[(top, bottom)])
        out.append("".join(line))
    return "\n".join(out)
