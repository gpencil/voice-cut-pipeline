import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import step6_clone


class Step6InputsTest(unittest.TestCase):
    def test_step6_accepts_non_rank_wav_names(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "temp5" / "400000001"
            dst = root / "temp6"
            src.mkdir(parents=True)
            wav = src / "400000001_001_001.wav"
            wav.write_bytes(b"fake-wav")
            wav.with_suffix(".txt").write_text("测试文本", encoding="utf-8")

            with patch("pipeline.step6_clone.sf.info") as info, \
                 patch("pipeline.step6_clone._upload_wav", side_effect=RuntimeError("stop before network")):
                info.return_value.frames = 16000
                info.return_value.samplerate = 16000
                result = step6_clone.run(str(root / "temp5"), str(dst), api_key="secret")

            self.assertEqual(result.input_count, 1)
            self.assertEqual(result.output_count, 0)
            self.assertEqual(result.status, "error")


if __name__ == "__main__":
    unittest.main()
