"""Minimal PNG writer (indexed and RGBA) using only zlib and struct."""

import struct
import zlib

import numpy as np


def _chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def _encode(width, height, color_type, raw_rows, extra_chunks=()):
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    out = [b"\x89PNG\r\n\x1a\n", _chunk(b"IHDR", header)]
    out.extend(extra_chunks)
    filtered = b"".join(b"\x00" + row for row in raw_rows)
    out.append(_chunk(b"IDAT", zlib.compress(filtered, 9)))
    out.append(_chunk(b"IEND", b""))
    return b"".join(out)


def write_indexed(path, indices, palette, transparent_index=0):
    """Write an 8-bit paletted PNG. ``indices`` is an (H, W) uint8 array."""
    indices = np.ascontiguousarray(indices, dtype=np.uint8)
    height, width = indices.shape
    plte = np.asarray(palette, dtype=np.uint8).reshape(-1, 3).tobytes()
    trns = bytes([255] * transparent_index + [0])
    chunks = [_chunk(b"PLTE", plte), _chunk(b"tRNS", trns)]
    rows = [indices[y].tobytes() for y in range(height)]
    data = _encode(width, height, 3, rows, chunks)
    with open(path, "wb") as handle:
        handle.write(data)


def write_rgba(path, rgba):
    """Write an 8-bit RGBA PNG. ``rgba`` is an (H, W, 4) uint8 array."""
    rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
    height, width = rgba.shape[:2]
    rows = [rgba[y].tobytes() for y in range(height)]
    with open(path, "wb") as handle:
        handle.write(_encode(width, height, 6, rows))


def read_indexed(path):
    """Read back a non-interlaced 8-bit paletted PNG written by :func:`write_indexed`.

    Returns (indices, palette). Only filter type 0 rows are supported, which
    is all this module writes.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    pos = 8
    width = height = 0
    palette = None
    idat = b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif kind == b"PLTE":
            palette = np.frombuffer(body, dtype=np.uint8).reshape(-1, 3)
        elif kind == b"IDAT":
            idat += body
    raw = zlib.decompress(idat)
    stride = width + 1
    rows = [raw[y * stride + 1 : (y + 1) * stride] for y in range(height)]
    indices = np.frombuffer(b"".join(rows), dtype=np.uint8).reshape(height, width)
    return indices, palette
