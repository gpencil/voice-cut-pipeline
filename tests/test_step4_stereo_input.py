import unittest

import numpy as np

from pipeline.step4_quality import _frame_rms, _noisy_voiced_ratio


class Step4StereoInputTest(unittest.TestCase):
    def test_frame_metrics_accept_stereo_input(self):
        sr = 44100
        t = np.arange(304290 // 2) / sr
        mono = (3000 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
        stereo = np.column_stack([mono, mono])

        rms = _frame_rms(stereo, sr)
        noisy_ratio = _noisy_voiced_ratio(stereo, sr)

        self.assertGreater(len(rms), 0)
        self.assertGreaterEqual(noisy_ratio, 0.0)


if __name__ == "__main__":
    unittest.main()
