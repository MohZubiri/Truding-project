import unittest

from halal_checker import classify_bot_reply


class HalalCaptionClassificationTests(unittest.TestCase):
    def test_arabic_photo_caption_is_rejected(self):
        caption = (
            "اسم العملة: BULLA\n"
            "حكم العملة: غير مباح\n"
            "رابط الحكم: https://t.me/CryptoIslam/4863"
        )

        self.assertIs(classify_bot_reply(caption), False)

    def test_english_photo_captions_are_rejected(self):
        for verdict in ("Not Permitted", "Impermissible", "Prohibited"):
            with self.subTest(verdict=verdict):
                caption = f"Coin: BULLA\nVerdict: {verdict}"
                self.assertIs(classify_bot_reply(caption), False)

    def test_permitted_arabic_caption_is_accepted(self):
        caption = "اسم العملة: BTC\nحكم العملة: مباح"

        self.assertIs(classify_bot_reply(caption), True)


if __name__ == "__main__":
    unittest.main()
