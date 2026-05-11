import unittest

import numpy as np

from pipeline.step4_quality import _trim_leading_start
from tests.test_step4_hiss_filter import _voice_like


class Step4LeadingTrimTest(unittest.TestCase):
    def test_leading_silence_is_trimmed(self):
        sr = 16000
        audio = np.concatenate([
            np.zeros(int(sr * 0.4), dtype=np.int16),
            _voice_like(sr, 3.0),
        ])

        trimmed, trimmed_s = _trim_leading_start(audio, sr)

        self.assertLess(len(trimmed), len(audio))
        self.assertAlmostEqual(trimmed_s, 0.35, delta=0.12)

    def test_short_opening_filler_is_trimmed(self):
        sr = 16000
        t = np.arange(int(sr * 0.25)) / sr
        filler = (3000 * np.sin(2 * np.pi * 380 * t)).astype(np.int16)
        gap = np.zeros(int(sr * 0.25), dtype=np.int16)
        main = _voice_like(sr, 3.0)
        audio = np.concatenate([filler, gap, main])

        trimmed, trimmed_s = _trim_leading_start(audio, sr)

        self.assertLess(len(trimmed), len(audio))
        self.assertAlmostEqual(trimmed_s, 0.45, delta=0.15)

    def test_short_opening_with_tiny_gap_is_trimmed(self):
        sr = 8000
        t = np.arange(int(sr * 0.10)) / sr
        opener = (1800 * np.sin(2 * np.pi * 380 * t)).astype(np.int16)
        tiny_gap = np.zeros(int(sr * 0.05), dtype=np.int16)
        main = _voice_like(sr, 2.0)
        audio = np.concatenate([np.zeros(int(sr * 0.05), dtype=np.int16), opener, tiny_gap, main])

        trimmed, trimmed_s = _trim_leading_start(audio, sr)

        self.assertLess(len(trimmed), len(audio))
        self.assertAlmostEqual(trimmed_s, 0.15, delta=0.08)

    def test_longer_opening_filler_before_gap_is_trimmed(self):
        sr = 8000
        t = np.arange(int(sr * 0.60)) / sr
        opener = (1800 * np.sin(2 * np.pi * 380 * t)).astype(np.int16)
        gap = np.zeros(int(sr * 0.10), dtype=np.int16)
        main_t = np.arange(int(sr * 0.8)) / sr
        main_part = (
            4200 * np.sin(2 * np.pi * 520 * main_t)
            + 1800 * np.sin(2 * np.pi * 980 * main_t)
        ).astype(np.int16)
        main = np.concatenate([main_part, np.zeros(int(sr * 0.25), dtype=np.int16), main_part])
        audio = np.concatenate([opener, gap, main])

        trimmed, trimmed_s = _trim_leading_start(audio, sr)

        self.assertLess(len(trimmed), len(audio))
        self.assertAlmostEqual(trimmed_s, 0.65, delta=0.1)


if __name__ == "__main__":
    unittest.main()
