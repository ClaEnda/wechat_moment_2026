"""ISAAC-64 keystream used by WeChat moments media.

The seed is the decimal key from the image record. WeChat's generator uses the
golden-ratio constant ending in 7c13. Each 64-bit output word is written
big-endian, which is the client's word order.
"""
from __future__ import annotations

_MASK = 0xFFFFFFFFFFFFFFFF


def _u64(value: int) -> int:
    return value & _MASK


class Isaac64:
    def __init__(self, seed: int):
        self.mm = [0] * 256
        self.aa = 0
        self.bb = 0
        self.cc = 0
        self.randrsl = [0] * 256
        self.randrsl[0] = _u64(seed)
        self.randcnt = 0
        self._init()

    def _init(self) -> None:
        a = b = c = d = e = f = g = h = 0x9E3779B97F4A7C13

        def mix() -> None:
            nonlocal a, b, c, d, e, f, g, h
            a = _u64(a - e)
            f = _u64(f ^ (h >> 9))
            h = _u64(h + a)
            b = _u64(b - f)
            g = _u64(g ^ _u64(a << 9))
            a = _u64(a + b)
            c = _u64(c - g)
            h = _u64(h ^ (b >> 23))
            b = _u64(b + c)
            d = _u64(d - h)
            a = _u64(a ^ _u64(c << 15))
            c = _u64(c + d)
            e = _u64(e - a)
            b = _u64(b ^ (d >> 14))
            d = _u64(d + e)
            f = _u64(f - b)
            c = _u64(c ^ _u64(e << 20))
            e = _u64(e + f)
            g = _u64(g - c)
            d = _u64(d ^ (f >> 17))
            f = _u64(f + g)
            h = _u64(h - d)
            e = _u64(e ^ _u64(g << 14))
            g = _u64(g + h)

        for _ in range(4):
            mix()
        for i in range(0, 256, 8):
            a = _u64(a + self.randrsl[i])
            b = _u64(b + self.randrsl[i + 1])
            c = _u64(c + self.randrsl[i + 2])
            d = _u64(d + self.randrsl[i + 3])
            e = _u64(e + self.randrsl[i + 4])
            f = _u64(f + self.randrsl[i + 5])
            g = _u64(g + self.randrsl[i + 6])
            h = _u64(h + self.randrsl[i + 7])
            mix()
            self.mm[i:i + 8] = [a, b, c, d, e, f, g, h]
        for i in range(0, 256, 8):
            a = _u64(a + self.mm[i])
            b = _u64(b + self.mm[i + 1])
            c = _u64(c + self.mm[i + 2])
            d = _u64(d + self.mm[i + 3])
            e = _u64(e + self.mm[i + 4])
            f = _u64(f + self.mm[i + 5])
            g = _u64(g + self.mm[i + 6])
            h = _u64(h + self.mm[i + 7])
            mix()
            self.mm[i:i + 8] = [a, b, c, d, e, f, g, h]
        self._isaac64()
        self.randcnt = 256

    def _isaac64(self) -> None:
        self.cc = _u64(self.cc + 1)
        self.bb = _u64(self.bb + self.cc)
        for i in range(256):
            x = self.mm[i]
            if (i & 3) == 0:
                self.aa = _u64(self.aa ^ (_u64(self.aa << 21) ^ _MASK))
            elif (i & 3) == 1:
                self.aa = _u64(self.aa ^ (self.aa >> 5))
            elif (i & 3) == 2:
                self.aa = _u64(self.aa ^ _u64(self.aa << 12))
            else:
                self.aa = _u64(self.aa ^ (self.aa >> 33))
            self.aa = _u64(self.mm[(i + 128) & 255] + self.aa)
            y = _u64(self.mm[(x >> 3) & 255] + self.aa + self.bb)
            self.mm[i] = y
            self.bb = _u64(self.mm[(y >> 11) & 255] + x)
            self.randrsl[i] = self.bb

    def rand_u64(self) -> int:
        if self.randcnt == 0:
            self._isaac64()
            self.randcnt = 256
        self.randcnt -= 1
        return self.randrsl[self.randcnt]

    def keystream(self, size: int) -> bytes:
        out = bytearray()
        while len(out) < size:
            out.extend(self.rand_u64().to_bytes(8, "big"))
        return bytes(out[:size])
