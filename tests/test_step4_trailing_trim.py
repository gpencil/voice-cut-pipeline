import unittest

import numpy as np

from pipeline.step4_quality import _trim_trailing_residue
from tests.test_step4_hiss_filter import _voice_like


class Step4TrailingTrimTest(unittest.TestCase):
    def test_low_energy_trailing_residue_is_trimmed(self):
        sr = 16000
        main = _voice_like(sr, 3.0)
        t = np.arange(int(sr * 0.25)) / sr
        tail = (180 * np.sin(2 * np.pi * 1200 * t)).astype(np.int16)
        audio = np.concatenate([main, tail])

        trimmed, trimmed_s = _trim_trailing_residue(audio, sr)

        self.assertLess(len(trimmed), len(audio))
        self.assertAlmostEqual(trimmed_s, 0.25, delta=0.12)

    def test_isolated_trailing_burst_after_gap_is_trimmed(self):
        sr = 16000
        main = _voice_like(sr, 1.2)
        gap = np.zeros(int(sr * 0.10), dtype=np.int16)
        t = np.arange(int(sr * 0.15)) / sr
        burst = (4500 * np.sin(2 * np.pi * 900 * t)).astype(np.int16)
        audio = np.concatenate([main, gap, burst])

        trimmed, trimmed_s = _trim_trailing_residue(audio, sr)

        self.assertLess(len(trimmed), len(audio))
        self.assertAlmostEqual(trimmed_s, 0.15, delta=0.06)


if __name__ == "__main__":
    unittest.main()
