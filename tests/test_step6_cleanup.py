import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class Step6CleanupTest(unittest.TestCase):
    def test_delete_existing_step6_voices_reads_report_json(self):
        with tempfile.TemporaryDirectory() as td:
            temp6 = Path(td) / "temp6" / "400000001"
            temp6.mkdir(parents=True)
            (temp6 / "report.json").write_text(
                json.dumps({"voice_id": "manbang_123"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch("app.step7_delete_voice.run") as delete_voice:
                app._delete_existing_step6_voices(Path(td) / "temp6", "secret")

            delete_voice.assert_called_once_with("manbang_123", api_key="secret")


if __name__ == "__main__":
    unittest.main()
