"""tools/ps_prompt_glyphs.py: the generated movie is well formed and exports every symbol the title looks up."""
import os
import struct
import sys
import unittest
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import ps_prompt_glyphs as g  # noqa: E402

N = [*range(4, 40), 58, 59]


def tags(data, start, end):
    o = start
    while o < end:
        head = struct.unpack_from("<H", data, o)[0]
        code, length = head >> 6, head & 63
        o += 2
        if length == 63:
            length = struct.unpack_from("<I", data, o)[0]
            o += 4
        assert o + length <= end, "tag runs past its container"
        yield code, data[o:o + length]
        o += length
        if code == 0:
            assert o == end, "bytes after the End tag"
            return
    raise AssertionError("no End tag")


def u30(b, o):
    v = shift = 0
    while True:
        c = b[o]
        o += 1
        v |= (c & 0x7F) << shift
        shift += 7
        if not c & 0x80:
            return v, o


def skip_abc(b):
    """Walks the ABC up to its instance table; returns (class count, method count, offset)."""
    o = 4
    for _ in range(3):  # ints, uints, doubles (no entries: count 1)
        c, o = u30(b, o)
        assert c == 1
    c, o = u30(b, o)
    for _ in range(c - 1):
        n, o = u30(b, o)
        o += n
    c, o = u30(b, o)
    for _ in range(c - 1):
        o += 1
        _, o = u30(b, o)
    c, o = u30(b, o)
    assert c == 1
    c, o = u30(b, o)
    for _ in range(c - 1):
        assert b[o] == 7
        o += 1
        _, o = u30(b, o)
        _, o = u30(b, o)
    methods, o = u30(b, o)
    for _ in range(methods):
        for _ in range(3):
            _, o = u30(b, o)
        o += 1
    _, o = u30(b, o)  # metadata
    classes, o = u30(b, o)
    for _ in range(classes):
        _, o = u30(b, o)
        _, o = u30(b, o)
        o += 1
        for _ in range(3):  # interface count, iinit, trait count
            _, o = u30(b, o)
    return classes, methods, o


class Glyphs(unittest.TestCase):
    def setUp(self):
        self.data = g.build()

    def test_header(self):
        d = self.data
        self.assertEqual(d[:4], b"GFX*")
        self.assertEqual(struct.unpack_from("<I", d, 4)[0], len(d))

    def test_tags_and_exports(self):
        d = self.data
        nbits = d[8] >> 3
        start = 8 + (5 + 4 * nbits + 7) // 8 + 4
        seen = {}
        sprites, shapes, ids = set(), set(), set()
        for code, body in tags(d, start, len(d)):
            seen[code] = seen.get(code, 0) + 1
            if code == 32:
                shapes.add(struct.unpack_from("<H", body)[0])
            if code == 39:
                sid = struct.unpack_from("<H", body)[0]
                sprites.add(sid)
                inner = list(tags(body, 4, len(body)))
                self.assertEqual(inner[-1][0], 0)
                self.assertEqual(inner[-2][0], 1)
                for c, b in inner:
                    if c == 26:
                        self.assertIn(struct.unpack_from("<H", b, 3)[0], shapes)
            if code == 56:
                n = struct.unpack_from("<H", body)[0]
                o = 2
                names = {}
                for _ in range(n):
                    cid = struct.unpack_from("<H", body, o)[0]
                    e = body.index(b"\0", o + 2)
                    names[body[o + 2:e].decode()] = cid
                    o = e + 1
                self.assertEqual(o, len(body))
                self.assertEqual(sorted(names), sorted("platform_xbsx.input_icons.Main_Button_%d" % i for i in N))
                self.assertEqual(set(names.values()), sprites)
            if code == 76:
                n = struct.unpack_from("<H", body)[0]
                self.assertEqual(n, len(N) + 1)
            if code == 82:
                classes, methods, end = skip_abc(body[4 + len(b"frame1") + 1:])
                self.assertEqual(classes, len(N) + 1)
                self.assertEqual(methods, 2 * classes + 1)
        self.assertEqual(seen[32], len(shapes))
        self.assertEqual(seen[39], len(N))
        self.assertEqual(seen[0], 1)

    def test_fits_the_stored_size(self):
        self.assertLess(len(zlib.compress(self.data, 9)), 9644)
        self.assertEqual(zlib.decompress(zlib.compress(self.data, 9)), self.data)

    def test_deterministic(self):
        self.assertEqual(g.build(), self.data)


if __name__ == "__main__":
    unittest.main()
