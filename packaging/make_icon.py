"""生成应用图标 packaging/context_cli.ico（纯标准库，可重复运行）。

设计：蓝色圆角方块背景 + 白色闪电，对应「快捷执行」。
同时输出 preview.png 便于人工检查效果。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

TARGET = 256
S = 3  # 超采样倍数，用于抗锯齿
CANVAS = TARGET * S

# 圆角方块范围与圆角半径（256 网格坐标）
BOX = (14, 14, 242, 242)
RADIUS = 52

# 闪电多边形（256 网格坐标）
BOLT = [
    (152, 24),
    (88, 132),
    (120, 132),
    (104, 232),
    (184, 104),
    (148, 104),
]

GRADIENT_TOP = (48, 130, 242)
GRADIENT_BOTTOM = (20, 80, 190)


def in_rounded_square(x: float, y: float) -> bool:
    x0, y0, x1, y1 = (value * S for value in BOX)
    radius = RADIUS * S
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    px = min(max(x, x0 + radius), x1 - radius)
    py = min(max(y, y0 + radius), y1 - radius)
    return (x - px) ** 2 + (y - py) ** 2 <= radius * radius


def in_bolt(x: float, y: float) -> bool:
    points = [(px * S, py * S) for px, py in BOLT]
    inside = False
    n = len(points)
    for index in range(n):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % n]
        if (y1 > y) != (y2 > y):
            intersect_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < intersect_x:
                inside = not inside
    return inside


def render_supersampled() -> list[list[tuple[int, int, int, int]]]:
    """按 CANVAS 尺寸超采样渲染，再缩小到 TARGET。"""
    acc: list[list[tuple[float, float, float, float]]] = [
        [(0.0, 0.0, 0.0, 0.0) for _ in range(TARGET)] for _ in range(TARGET)
    ]
    total = S * S
    for yy in range(CANVAS):
        # 背景渐变按超采样行计算
        t = yy / (CANVAS - 1)
        base_r = GRADIENT_TOP[0] + (GRADIENT_BOTTOM[0] - GRADIENT_TOP[0]) * t
        base_g = GRADIENT_TOP[1] + (GRADIENT_BOTTOM[1] - GRADIENT_TOP[1]) * t
        base_b = GRADIENT_TOP[2] + (GRADIENT_BOTTOM[2] - GRADIENT_TOP[2]) * t
        ty = yy // S
        for xx in range(CANVAS):
            if not in_rounded_square(xx, yy):
                continue
            r = int(base_r)
            g = int(base_g)
            b = int(base_b)
            a = 255
            if in_bolt(xx, yy):
                r = g = b = 255
            tx = xx // S
            cell = acc[ty][tx]
            acc[ty][tx] = (cell[0] + r, cell[1] + g, cell[2] + b, cell[3] + a)
    return [
        [
            (
                round(cell[0] / total),
                round(cell[1] / total),
                round(cell[2] / total),
                round(cell[3] / total),
            )
            for cell in row
        ]
        for row in acc
    ]


def resample(
    src: list[list[tuple[int, int, int, int]]], size: int
) -> list[list[tuple[int, int, int, int]]]:
    """从 256 图按面积平均缩放到 size。"""
    scale = len(src) / size
    out: list[list[tuple[int, int, int, int]]] = []
    for ty in range(size):
        y0 = int(ty * scale)
        y1 = max(int((ty + 1) * scale), y0 + 1)
        row: list[tuple[int, int, int, int]] = []
        for tx in range(size):
            x0 = int(tx * scale)
            x1 = max(int((tx + 1) * scale), x0 + 1)
            count = (x1 - x0) * (y1 - y0)
            sums = [0, 0, 0, 0]
            for y in range(y0, y1):
                for x in range(x0, x1):
                    pixel = src[y][x]
                    for channel in range(4):
                        sums[channel] += pixel[channel]
            row.append(
                tuple(round(value / count) for value in sums)  # type: ignore[arg-type]
            )
        out.append(row)
    return out


def encode_png(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    height = len(pixels)
    width = len(pixels[0])
    raw = b"".join(
        b"\x00" + bytes(value for pixel in row for value in pixel) for row in pixels
    )

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def encode_dib(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    """32 位 BGRA DIB（ICO 的 BMP 条目），自底向上 + 全零 AND 掩码。"""
    size = len(pixels)
    xor = bytearray()
    for y in range(size - 1, -1, -1):
        for pixel in pixels[y]:
            r, g, b, a = pixel
            xor += bytes((b, g, r, a))
    and_stride = ((size + 31) // 32) * 4
    and_mask = b"\x00" * (and_stride * size)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(xor) + len(and_mask),
        0,
        0,
        0,
        0,
    )
    return header + bytes(xor) + and_mask


def build_ico() -> bytes:
    base = render_supersampled()
    entries: list[tuple[int, bytes]] = []
    for size in (16, 32, 48):
        entries.append((size, encode_dib(resample(base, size))))
    png256 = encode_png(base)
    entries.append((256, png256))

    header = struct.pack("<HHH", 0, 1, len(entries))
    blobs: list[bytes] = []
    directory = b""
    offset = 6 + 16 * len(entries)
    for size, data in entries:
        dimension = 0 if size >= 256 else size
        directory += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset
        )
        blobs.append(data)
        offset += len(data)
    return header + directory + b"".join(blobs)


def write_png_preview(pixels: list[list[tuple[int, int, int, int]]], path: Path) -> None:
    path.write_bytes(encode_png(pixels))


def main() -> None:
    here = Path(__file__).resolve().parent
    base = render_supersampled()
    (here / "context_cli.ico").write_bytes(build_ico())
    write_png_preview(base, here / "icon_preview.png")
    print("已生成 context_cli.ico 与 icon_preview.png")


if __name__ == "__main__":
    main()
