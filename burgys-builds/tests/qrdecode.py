"""An independent QR reader, used only by the tests.

It deliberately does not reuse the encoder's placement or format-info code:
it re-derives the reading order and brute-forces the format bits, so a bug
in :mod:`bb.qr` shows up as a decode failure rather than cancelling out.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bb import qr


def read_format(matrix: list) -> tuple:
    bits = 0
    for i in range(15):
        if i < 6:
            bit = matrix[8][i]
        elif i == 6:
            bit = matrix[8][7]
        elif i == 7:
            bit = matrix[8][8]
        elif i == 8:
            bit = matrix[7][8]
        else:
            bit = matrix[14 - i][8]
        bits |= bit << i
    for level in qr.LEVELS:
        for mask in range(8):
            if qr._format_bits(level, mask) == bits:
                return level, mask
    raise AssertionError(f"format information does not decode: {bits:015b}")


def read_codewords(matrix: list, version: int) -> list:
    size = qr.size_for(version)
    reserved = qr._reserved(version)
    mask_fn = qr._MASKS[read_format(matrix)[1]]
    bits: list = []
    upward, col = True, size - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if reserved[row][c]:
                    continue
                value = matrix[row][c]
                if mask_fn(row, c):
                    value ^= 1
                bits.append(value)
        upward = not upward
        col -= 2
    return [int("".join(str(b) for b in bits[i:i + 8]), 2)
            for i in range(0, len(bits) - len(bits) % 8, 8)]


def decode(matrix: list) -> str:
    version = (len(matrix) - 17) // 4
    level, _ = read_format(matrix)
    stream = read_codewords(matrix, version)
    ec_len, groups = qr.BLOCKS[(version, level)]
    sizes = [size for count, size in groups for _ in range(count)]
    blocks = [[] for _ in sizes]
    pos = 0
    for i in range(max(sizes)):
        for b, size in enumerate(sizes):
            if i < size:
                blocks[b].append(stream[pos])
                pos += 1
    ecs = [[] for _ in sizes]
    for i in range(ec_len):
        for b in range(len(sizes)):
            ecs[b].append(stream[pos])
            pos += 1
    for block, ec in zip(blocks, ecs):
        syn = qr.rs_syndromes(block + ec, ec_len)
        if any(syn):
            raise AssertionError(f"non-zero Reed-Solomon syndromes: {syn}")
    data = [b for block in blocks for b in block]
    bits = "".join(f"{b:08b}" for b in data)
    mode = int(bits[:4], 2)
    if mode != 0b0100:
        raise AssertionError(f"expected byte mode, got {mode:04b}")
    count_bits = 8 if version <= 9 else 16
    length = int(bits[4:4 + count_bits], 2)
    start = 4 + count_bits
    payload = bytes(int(bits[start + i * 8:start + i * 8 + 8], 2) for i in range(length))
    return payload.decode("utf-8")
