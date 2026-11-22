"""Codec boundaries shared by ARM artwork/maps and the Z80 music player."""
import random
import unittest
from lzss import compress,decompress

class CodecTests(unittest.TestCase):
    def test_boundary_lengths(self):
        for length in (0,1,2,3,7,8,9,33,34,35,255,2047,2048,2049,7168):
            with self.subTest(length=length):
                raw=bytes([17])*length
                self.assertEqual(decompress(compress(raw),length),raw)

    def test_all_literals_and_history_wrap(self):
        rng=random.Random(12)
        for raw in (bytes(range(256)),bytes(range(256))*40,bytes(rng.randrange(256) for _ in range(9000))):
            self.assertEqual(decompress(compress(raw),len(raw)),raw)

    def test_overlapping_references(self):
        for pattern in (b'A',b'AB',b'ABC',b'ABCDE'):
            raw=pattern*3000
            self.assertEqual(decompress(compress(raw),len(raw)),raw)

    def test_invalid_reference_and_trailing_data(self):
        with self.assertRaises(ValueError):decompress(b'\x01\x00\x00',3)
        with self.assertRaises(ValueError):decompress(compress(b'abc')+b'x',3)

if __name__=='__main__':unittest.main()
