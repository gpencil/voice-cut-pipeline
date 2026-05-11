import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from pipeline import step2_extract_channel, step3_split


class ShortNamePipelineTest(unittest.TestCase):
    def test_step2_renames_files_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "temp1" / "400000001"
            dst = root / "temp2"
            src.mkdir(parents=True)
            wav = src / "400000001-400000002-0-C20260111000000-LR.wav"
            data = np.zeros((16000, 2), dtype=np.int16)
            data[:, 0] = 1000
            sf.write(wav, data, 16000, subtype="PCM_16")

            result = step2_extract_channel.run(str(root / "temp1"), str(dst))

            self.assertEqual(result.output_count, 1)
            self.assertTrue((dst / "400000001" / "400000001_001.wav").exists())
            manifest = json.loads((dst / "400000001" / "manifest.json").read_text())
            self.assertEqual(
                manifest["400000001_001.wav"]["origin"],
                "400000001-400000002-0-C20260111000000-LR.wav",
            )

    def test_step3_keeps_short_source_id_in_segment_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "temp2" / "400000001"
            dst = root / "temp3"
            src.mkdir(parents=True)
            wav = src / "400000001_001.wav"
            data = np.full(16000 * 3, 1000, dtype=np.int16)
            sf.write(wav, data, 16000, subtype="PCM_16")
            (src / "manifest.json").write_text(
                json.dumps(
                    {
                        "400000001_001.wav": {
                            "source": "400000001_001.wav",
                            "origin": "400000001-400000002-0-C20260111000000-LR.wav",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = step3_split.run(str(root / "temp2"), str(dst))

            self.assertEqual(result.output_count, 1)
            self.assertTrue((dst / "400000001" / "400000001_001_001.wav").exists())
            manifest = json.loads((dst / "400000001" / "manifest.json").read_text())
            self.assertEqual(
                manifest["400000001_001_001.wav"]["origin"],
                "400000001-400000002-0-C20260111000000-LR.wav",
            )


if __name__ == "__main__":
    unittest.main()
