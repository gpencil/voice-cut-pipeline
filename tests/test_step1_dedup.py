import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import step1_classify


class Step1DedupeTest(unittest.TestCase):
    def test_skip_shipper_when_voice_id_exists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "input"
            dst = root / "temp1"
            src.mkdir()
            wav = src / "400000001-500000001-0-C20260101000000-LR.wav"
            wav.write_bytes(b"not-a-real-wav")

            with patch("pipeline.step1_classify.find_existing_voice_id", return_value="manbang_123"):
                result = step1_classify.run(str(src), str(dst))

            self.assertEqual(result.input_count, 1)
            self.assertEqual(result.output_count, 0)
            self.assertEqual(result.skipped, 1)
            self.assertFalse((dst / "400000001").exists())
            self.assertTrue(any("已有音色ID" in e["reason"] for e in result.errors))

    def test_existing_voice_logs_once_per_shipper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "input"
            dst = root / "temp1"
            src.mkdir()
            (src / "400000001-500000001-0-C20260101000001-LR.wav").write_bytes(b"wav1")
            (src / "400000001-500000002-0-C20260101000002-LR.wav").write_bytes(b"wav2")
            (src / "400000001-500000003-0-C20260101000003-LR.wav").write_bytes(b"wav3")

            with patch("pipeline.step1_classify.find_existing_voice_id", return_value="manbang_123"):
                result = step1_classify.run(str(src), str(dst))

            self.assertEqual(result.input_count, 3)
            self.assertEqual(result.output_count, 0)
            self.assertEqual(result.skipped, 3)
            self.assertEqual(len(result.errors), 1)
            self.assertEqual(result.errors[0]["file"], "400000001")
            self.assertIn("跳过 3 个文件", result.errors[0]["reason"])

    def test_copy_shipper_when_voice_id_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "input"
            dst = root / "temp1"
            src.mkdir()
            wav = src / "400000001-500000001-0-C20260101000000-LR.wav"
            wav.write_bytes(b"not-a-real-wav")

            with patch("pipeline.step1_classify.find_existing_voice_id", return_value=None):
                result = step1_classify.run(str(src), str(dst))

            self.assertEqual(result.output_count, 1)
            self.assertTrue((dst / "400000001" / wav.name).exists())


if __name__ == "__main__":
    unittest.main()
