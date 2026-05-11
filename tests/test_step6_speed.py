import unittest

from pipeline import step6_clone


class Step6SpeedTest(unittest.TestCase):
    def test_very_fast_reference_uses_slow_speed(self):
        text = "好挂了吧师傅你发过来就行了"

        rate, speed = step6_clone._select_tts_speed(text, duration_s=1.7)

        self.assertGreater(rate, 7.0)
        self.assertEqual(speed, 0.9)

    def test_fast_reference_uses_normal_speed(self):
        text = "今天天气不错我们可以明天早上出发"

        rate, speed = step6_clone._select_tts_speed(text, duration_s=2.3)

        self.assertGreater(rate, 6.0)
        self.assertLessEqual(rate, 7.0)
        self.assertEqual(speed, 1.0)

    def test_normal_reference_uses_slightly_faster_speed(self):
        text = "今天天气不错我们可以明天早上出发"

        rate, speed = step6_clone._select_tts_speed(text, duration_s=3.0)

        self.assertLessEqual(rate, 6.0)
        self.assertEqual(speed, 1.1)

    def test_round2_always_uses_default_speed(self):
        self.assertEqual(step6_clone._ROUND2_TTS_SPEED, 1.0)


if __name__ == "__main__":
    unittest.main()
