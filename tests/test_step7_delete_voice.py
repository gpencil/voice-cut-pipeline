import unittest
from unittest.mock import Mock, patch

from pipeline import step7_delete_voice


class DeleteVoiceTest(unittest.TestCase):
    def test_delete_voice_calls_api_with_voice_id_and_key(self):
        resp = Mock()
        resp.raise_for_status.return_value = None

        with patch("pipeline.step7_delete_voice.requests.delete", return_value=resp) as delete, \
             patch("pipeline.step7_delete_voice.delete_voice_record") as delete_record:
            result = step7_delete_voice.run("manbang_123", api_key="secret")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.output_count, 1)
        delete.assert_called_once()
        url = delete.call_args.args[0]
        kwargs = delete.call_args.kwargs
        self.assertTrue(url.endswith("/v1/voice/manbang_123"))
        self.assertEqual(kwargs["headers"]["X-API-Key"], "secret")
        delete_record.assert_called_once_with("manbang_123")

    def test_delete_voice_requires_voice_id(self):
        result = step7_delete_voice.run("", api_key="secret")

        self.assertEqual(result.status, "error")
        self.assertEqual(result.output_count, 0)
        self.assertEqual(result.errors[0]["file"], "voice_id")


if __name__ == "__main__":
    unittest.main()
