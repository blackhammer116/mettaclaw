"""Real offline detection; mock the network catalogue and audio delivery."""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import speech_language as sl
import media_handler as mh

VOICES = [
    {"Locale": "en-US", "ShortName": sl.DEFAULT_VOICE, "Gender": "Female"},
    {"Locale": "en-US", "ShortName": "en-US-GuyNeural", "Gender": "Male"},
    {"Locale": "en-GB", "ShortName": "en-GB-SoniaNeural", "Gender": "Female"},
    {"Locale": "nb-NO", "ShortName": "nb-NO-PernilleNeural", "Gender": "Female"},
    {"Locale": "ru-RU", "ShortName": "ru-RU-DmitryNeural", "Gender": "Male"},
    {"Locale": "ru-RU", "ShortName": "ru-RU-SvetlanaNeural", "Gender": "Female"},
    {"Locale": "uk-UA", "ShortName": "uk-UA-PolinaNeural", "Gender": "Female"},
    {"Locale": "fr-FR", "ShortName": "fr-FR-DeniseNeural", "Gender": "Female"},
    {"Locale": "fr-FR", "ShortName": "fr-FR-AlainNeural", "Gender": "Male"},
]
RUSSIAN = "Это проверка русского голоса. Пожалуйста, прочитайте весь текст вслух."


class SpeechLanguageTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = self.enterContext(patch.object(
            sl, "available_voices", return_value=VOICES))

    def test_real_language_detection(self):
        for text, expected in [
            ("Hello, this is an English sentence.", "en"),
            ("Привет, мир!", "ru"),
            (RUSSIAN, "ru"),
            ("Це перевірка української мови. Будь ласка, прочитайте цей текст уголос.", "uk"),
            ("Bonjour, comment allez-vous aujourd’hui ?", "fr"),
            ("Hola, me gustaría escuchar este texto en español.", "es"),
            ("こんにちは、今日はいい天気ですね。", "ja"),
            ("OK", None), ("12345", None), ("", None),
        ]:
            with self.subTest(text=text):
                self.assertEqual(sl.detect_language(text), expected)

    def test_matching_configured_voice_and_uncertainty_need_no_catalogue(self):
        for language, voice in [("en", "en-GB-SoniaNeural"),
                                ("ru", "ru-RU-SvetlanaNeural"),
                                (None, "en-US-AriaNeural"),
                                ("no", "nb-NO-PernilleNeural")]:
            self.assertEqual(sl.select_voice(language, voice), voice)
        self.catalogue.assert_not_called()

    def test_russian_selection_and_return_to_english(self):
        self.assertEqual(sl.select_voice("ru", sl.DEFAULT_VOICE), "ru-RU-SvetlanaNeural")
        self.assertEqual(sl.select_voice("en", "ru-RU-DmitryNeural"), "en-US-GuyNeural")

    def test_unsupported_language_fails(self):
        with self.assertRaisesRegex(ValueError, "No female speech voice"):
            sl.select_voice("xx", sl.DEFAULT_VOICE)

    def test_uncertain_short_text_uses_configured_voice(self):
        self.assertEqual(sl.speech_parts("OK", "en-GB-SoniaNeural"),
                         [("OK", "en-GB-SoniaNeural")])
        self.catalogue.assert_not_called()

    def test_alphabetically_first_male_voice_is_skipped(self):
        self.assertEqual(sl.select_voice("fr", sl.DEFAULT_VOICE), "fr-FR-DeniseNeural")

    def test_configured_male_voice_is_preserved_for_matching_or_uncertain_text(self):
        for language in ("ru", None):
            self.assertEqual(sl.select_voice(language, "ru-RU-DmitryNeural"),
                             "ru-RU-DmitryNeural")
        self.catalogue.assert_not_called()

    def test_missing_or_male_gender_is_not_a_fallback(self):
        for gender in ("Male", None):
            self.catalogue.return_value = [
                VOICES[0],
                {"Locale": "ru-RU", "ShortName": "ru-RU-SvetlanaNeural", "Gender": gender}]
            with self.assertRaisesRegex(ValueError, "No female speech voice"):
                sl.select_voice("ru", sl.DEFAULT_VOICE)

    def test_dynamic_switch_then_return_to_configured_male_voice(self):
        text = "Hello, this is an English sentence.\n" + RUSSIAN + "\nHello, this is an English sentence."
        parts = sl.speech_parts(text, "en-US-GuyNeural")
        self.assertEqual([voice for _, voice in parts],
                         ["en-US-GuyNeural", "ru-RU-DmitryNeural", "en-US-GuyNeural"])

    def test_male_configuration_does_not_fall_back_to_female(self):
        with self.assertRaisesRegex(ValueError, "No male speech voice"):
            sl.select_voice("uk", "en-US-GuyNeural")

    def test_unknown_configured_gender_fails_on_language_switch(self):
        for configured in ("en-US-UnknownNeural", sl.DEFAULT_VOICE):
            with self.subTest(configured=configured):
                self.catalogue.return_value = [
                    {"Locale": "en-US", "ShortName": sl.DEFAULT_VOICE},
                    VOICES[4],
                ]
                with self.assertRaisesRegex(ValueError, "Cannot determine gender"):
                    sl.select_voice("ru", configured)

    def test_mixed_lines_keep_order(self):
        text = "Hello, this is an English sentence.\n" + RUSSIAN + "\nHello, this is an English sentence."
        parts = sl.speech_parts(text)
        self.assertEqual([voice for _, voice in parts],
                         [sl.DEFAULT_VOICE, "ru-RU-SvetlanaNeural", sl.DEFAULT_VOICE])
        self.assertEqual(" ".join(piece.strip() for piece, _ in parts),
                         text.replace("\n", " "))

    def test_long_russian_text_still_splits(self):
        text = (RUSSIAN + " ") * 100
        parts = sl.speech_parts(text)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(0 < len(piece) <= 4096 for piece, _ in parts))
        self.assertTrue(all(voice == "ru-RU-SvetlanaNeural" for _, voice in parts))
        self.assertEqual([piece for piece, _ in parts], sl.split_for_telegram(text))

    def test_speak_routes_cleaned_text_to_synthesis(self):
        config = types.ModuleType("config")
        config.config_get_by_key = lambda key, default=None: default
        with patch.dict(sys.modules, {"config": config}), \
                patch.object(mh, "_tts_allowed", return_value=True), \
                patch.object(mh, "_prompt_is_unsafe", return_value=False), \
                patch.object(mh, "_live_send_chat_action", None), \
                patch.object(mh, "_synthesise_speech", return_value=b"audio") as synth, \
                patch.object(mh, "_live_send_voice") as send:
            self.assertEqual(mh.speak("**Привет, мир!** https://example.com"), "VOICE_SENT")
            synth.assert_called_once_with("Привет, мир!", "ru-RU-SvetlanaNeural")
            send.assert_called_once()
            synth.reset_mock()
            send.reset_mock()
            self.catalogue.side_effect = RuntimeError("catalogue unavailable")
            self.assertIn("VOICE_FAILED", mh.speak(RUSSIAN))
            synth.assert_not_called()
            send.assert_not_called()


class VoiceCatalogueTests(unittest.TestCase):
    def setUp(self):
        sl.available_voices.cache_clear()
        self.addCleanup(sl.available_voices.cache_clear)

    def test_success_is_cached(self):
        with patch("edge_tts.list_voices", new_callable=AsyncMock,
                   return_value=VOICES) as fetch:
            self.assertEqual(sl.available_voices(), VOICES)
            self.assertEqual(sl.available_voices(), VOICES)
            fetch.assert_awaited_once()

    def test_failed_request_can_retry(self):
        with patch("edge_tts.list_voices", new_callable=AsyncMock,
                   side_effect=[TimeoutError("timeout"), VOICES]) as fetch:
            with self.assertRaises(TimeoutError):
                sl.available_voices()
            self.assertEqual(sl.available_voices(), VOICES)
            self.assertEqual(fetch.await_count, 2)

    def test_lookup_inside_running_event_loop(self):
        async def lookup():
            return sl.available_voices()

        with patch("edge_tts.list_voices", new_callable=AsyncMock,
                   return_value=VOICES):
            self.assertEqual(asyncio.run(lookup()), VOICES)


if __name__ == "__main__":
    unittest.main()
