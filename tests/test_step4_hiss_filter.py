import unittest

import numpy as np

from pipeline.step4_quality import _hiss_spike_frames


def _voice_like(sr: int, seconds: float) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    audio = np.random.default_rng(3).normal(0, 35, len(t))
    # 交替的语音/短停顿让现有 SNR、语音占比和流畅性规则都能正常工作。
    for start_s in (0.0, 0.6, 1.2, 1.8, 2.4):
        start = int(start_s * sr)
        end = len(audio) if start_s == 2.4 else min(len(audio), start + int(0.48 * sr))
        tt = t[start:end]
        audio[start:end] += 4200 * np.sin(2 * np.pi * 520 * tt) + 1800 * np.sin(2 * np.pi * 980 * tt)
    audio[int(0.5 * sr):int(0.6 * sr)] = 0
    return audio.astype(np.int16)


def _with_short_hiss(sr: int, seconds: float) -> np.ndarray:
    audio = _voice_like(sr, seconds).astype(np.float32)
    rng = np.random.default_rng(7)
    start = int(sr * 1.2)
    length = int(sr * 0.12)
    noise = rng.normal(0, 1, length)
    # 高频“呲”声：去掉低频平滑成分，保持 RMS 接近正常语音，避免被普通能量尖刺规则抓到。
    smooth = np.convolve(noise, np.ones(21) / 21, mode="same")
    hiss = noise - smooth
    hiss = hiss / (np.sqrt(np.mean(hiss**2)) + 1e-9) * 3500
    audio[start : start + length] = hiss
    return np.clip(audio, -32768, 32767).astype(np.int16)


class Step4HissFilterTest(unittest.TestCase):
    def test_short_hiss_burst_is_detected(self):
        sr = 16000
        self.assertEqual(_hiss_spike_frames(_voice_like(sr, 3.0), sr), 0)
        self.assertGreater(_hiss_spike_frames(_with_short_hiss(sr, 3.0), sr), 0)

if __name__ == "__main__":
    unittest.main()
