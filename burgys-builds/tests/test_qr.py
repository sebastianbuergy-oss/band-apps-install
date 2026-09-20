"""QR encoder: independent decode plus Reed-Solomon syndromes."""
import unittest

from helpers import ControllerCase  # noqa: F401  (path setup)
from qrdecode import decode, read_format

from bb import qr
from bb.errors import ValidationError


class TestQrTables(unittest.TestCase):
    def test_block_table_matches_the_geometry(self):
        qr.self_check()   # raises with a precise message if a row is wrong

    def test_derived_codeword_totals_match_the_standard(self):
        expected = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134,
                    6: 172, 7: 196, 8: 242, 9: 292, 10: 346}
        for version, total in expected.items():
            self.assertEqual(qr.total_codewords(version), total, f"version {version}")

    def test_reed_solomon_parity_has_zero_syndromes(self):
        data = list(range(1, 17))
        parity = qr.rs_encode(data, 10)
        self.assertEqual(qr.rs_syndromes(data + parity, 10), [0] * 10)

    def test_a_corrupted_codeword_has_non_zero_syndromes(self):
        data = list(range(1, 17))
        parity = qr.rs_encode(data, 10)
        corrupted = list(data)
        corrupted[3] ^= 0x5A
        self.assertNotEqual(qr.rs_syndromes(corrupted + parity, 10), [0] * 10)


class TestQrRoundTrip(unittest.TestCase):
    def test_every_version_and_level_round_trips(self):
        checked = 0
        for version in range(1, qr.MAX_VERSION + 1):
            for level in qr.LEVELS:
                capacity = qr.data_capacity_bytes(version, level)
                if capacity < 1:
                    continue
                text = ("burgys" * capacity)[:capacity]
                matrix = qr.encode(text, level, min_version=version)
                self.assertEqual((len(matrix) - 17) // 4, version)
                self.assertEqual(read_format(matrix)[0], level)
                self.assertEqual(decode(matrix), text)
                checked += 1
        self.assertEqual(checked, 40)

    def test_the_real_install_urls_round_trip(self):
        for url in (
            "https://sebastianbuergy-oss.github.io/band-apps-install/",
            "itms-services://?action=download-manifest&url=https://"
            "sebastianbuergy-oss.github.io/band-apps-install/thy-gnosis.plist",
        ):
            self.assertEqual(decode(qr.encode(url, "M")), url)

    def test_utf8_survives(self):
        text = "Grüezi – Bürgys Builds läuft"
        self.assertEqual(decode(qr.encode(text, "Q")), text)

    def test_too_much_data_is_refused_rather_than_truncated(self):
        with self.assertRaises(ValidationError):
            qr.encode("x" * 5000, "H")

    def test_rendering(self):
        matrix = qr.encode("https://example.invalid/", "M")
        svg = qr.to_svg(matrix)
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
        self.assertTrue(qr.to_png(matrix).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn("█", qr.to_text(matrix))


if __name__ == "__main__":
    unittest.main()
