"""Reported speech failures: real detection, mocked catalogue and transport."""
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import media_handler as mh
import speech_language as sl
from speech_text import prepare_speech
from text_splitter import split_for_telegram

VOICES = [
    {"Locale": locale, "ShortName": name, "Gender": gender}
    for locale, name, gender in [
        ("en-US", sl.DEFAULT_VOICE, "Female"),
        ("en-US", "en-US-GuyNeural", "Male"),
        ("ru-RU", "ru-RU-SvetlanaNeural", "Female"),
        ("uk-UA", "uk-UA-PolinaNeural", "Female"),
        ("zh-CN", "zh-CN-XiaoxiaoNeural", "Female"),
    ]
]


class RoutingTests(unittest.TestCase):
    def setUp(self):
        sl.validated_voice.cache_clear()
        self.catalogue = self.enterContext(patch.object(sl, "available_voices", return_value=VOICES))

    def test_reported_short_phrases(self):
        for text, language in [("Как дела?", "ru"), ("Да.", "ru"), ("你好。", "zh"),
                               ("Як справи?", "uk"), ("Доброе утро. Сегодня в столице ясно и холодно.", "ru")]:
            with self.subTest(text=text):
                self.assertTrue(all(voice.startswith(language + "-") for _, voice in sl.speech_parts(text)))

    def test_ambiguous_cyrillic_uses_context(self):
        self.assertTrue(all(voice.startswith("uk-") for _, voice in
                            sl.speech_parts("Да. Це український текст із літерами ї та є.")))

    def test_mixed_latin_does_not_override_cyrillic(self):
        text = "Я люблю Python и JavaScript."
        parts = sl.speech_parts(text)
        self.assertEqual("".join(piece for piece, _ in parts), text)
        self.assertTrue(all(voice.startswith("ru-") for _, voice in parts))
        chunks = list(sl.speech_chunks([(i, part, voice) for i, (part, voice) in enumerate(parts)]))
        self.assertEqual(len(chunks), 1)
        self.assertEqual("".join(part for _, part, _ in chunks[0]), text)

    def test_sentence_chunks_preserve_whole_sentences_and_voice_changes(self):
        sentence = "This is an ordinary English sentence with several words. "
        text = sentence * 120
        parts = sl.speech_parts(text)
        chunks = list(sl.speech_chunks([(i, part, voice) for i, (part, voice) in enumerate(parts)]))
        texts = ["".join(part for _, part, _ in chunk) for chunk in chunks]
        self.assertEqual("".join(texts), text)
        self.assertGreater(len(texts), 1)
        self.assertLess(len(texts), 4)
        self.assertTrue(all(len(piece) <= 4096 and piece.endswith(". ") for piece in texts))
        mixed = [(0, "Hello. ", "en-US-AriaNeural"),
                 (1, "Я люблю Python и JavaScript. ", "ru-RU-SvetlanaNeural"),
                 (2, "Goodbye.", "en-US-AriaNeural")]
        self.assertEqual(list(sl.speech_chunks(mixed)), [[part] for part in mixed])

    def test_typo_uses_default_then_language_routing(self):
        self.assertEqual(sl.speech_parts("Hello there", "en-US-TypoNeural"),
                         [("Hello there", sl.DEFAULT_VOICE)])
        self.assertTrue(sl.speech_parts("Как дела?", "en-US-TypoNeural")[0][1].startswith("ru-"))

    def test_catalogue_outage_is_not_cached_as_invalid_voice(self):
        self.catalogue.side_effect = RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            sl.validated_voice("en-US-GuyNeural")
        self.catalogue.side_effect = None
        self.assertEqual(sl.validated_voice("en-US-GuyNeural"), "en-US-GuyNeural")

    def test_long_line_preserves_words_and_text(self):
        text = "ordinary words " * 900
        parts = split_for_telegram(text)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(piece) <= 4096 for piece in parts))
        self.assertTrue(all(piece[-1].isspace() for piece in parts[:-1]))
        rendered = split_for_telegram(text, lambda part: len(part) * 2 <= 4096)
        self.assertEqual("".join(rendered), text)
        self.assertTrue(all(len(piece) * 2 <= 4096 for piece in rendered))

    def test_cleanup_bare_domains_symbols_and_ordinary_text(self):
        self.assertEqual(prepare_speech("Read example.com/path ⭐ ⏰ ▶ ™ now"), "Read now")
        text = "Keep v2.0 3.14 report.pdf user@example.com 50% $20 2+2"
        self.assertEqual(prepare_speech(text), text)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(mh._voice_requests, {}, clear=True))
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"MEMORY_DIR": self.directory}))
        config = types.ModuleType("config")
        config.config_get_by_key = lambda key, default=None: default
        self.enterContext(patch.dict(sys.modules, {"config": config}))
        self.channel = types.SimpleNamespace(chat_id=123, _reply_to_id=45, send_message=Mock())
        self.enterContext(patch.object(mh, "_live_channel", self.channel))
        self.enterContext(patch.object(mh, "_live_send_chat_action", None))
        self.enterContext(patch.object(mh, "_tts_allowed", return_value=True))
        self.enterContext(patch.object(mh, "_prompt_is_unsafe", return_value=False))
        self.enterContext(patch.object(mh, "speech_parts", return_value=[
            ("First.", sl.DEFAULT_VOICE), ("Second.", sl.DEFAULT_VOICE), ("Third.", sl.DEFAULT_VOICE)]))
        self.synth = self.enterContext(patch.object(mh, "_synthesise_speech", side_effect=[None, b"first", None, b"third"]))
        self.send = self.enterContext(patch.object(mh, "_live_send_voice", return_value=100))

    def test_partial_retry_only_sends_failed_part_and_new_request_is_distinct(self):
        self.assertTrue(mh.speak("request").startswith("VOICE_PARTIAL"))
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual([c.args[0] for c in self.send.call_args_list], [b"first", b"third"])
        self.channel.send_message.assert_called_once()
        self.synth.side_effect = [b"second"]
        self.assertEqual(mh.speak("request"), "VOICE_SENT")
        self.assertEqual(self.send.call_count, 3)
        self.assertEqual(self.send.call_args.args[0], b"second")
        self.assertEqual(mh.speak("request"), "VOICE_SENT")
        self.assertEqual(self.send.call_count, 3)
        self.channel._reply_to_id = 46
        self.synth.side_effect = None
        self.synth.return_value = b"new"
        self.assertEqual(mh.speak("request"), "VOICE_SENT")
        self.assertEqual(self.send.call_count, 4)

    def test_uncertain_upload_is_not_retried(self):
        self.synth.side_effect = None
        self.synth.return_value = b"audio"
        self.send.side_effect = TimeoutError()
        self.assertTrue(mh.speak("request").startswith("VOICE_FAILED"))
        self.assertIn("delivery uncertain", mh.speak("request"))
        self.assertEqual(self.send.call_count, 1)
        self.channel.send_message.assert_called_once()

    def test_text_budget_splits_uploads_without_repeating_them(self):
        self.synth.side_effect = [b"aaaa", b"bbbb"]
        with patch.object(mh, "speech_parts", return_value=[
                ("a" * 2000 + ". ", sl.DEFAULT_VOICE),
                ("b" * 2000 + ". ", sl.DEFAULT_VOICE),
                ("c" * 2000 + ".", sl.DEFAULT_VOICE)]):
            self.assertEqual(mh.speak("request"), "VOICE_SENT")
            self.assertEqual([call.args[0] for call in self.send.call_args_list],
                             [b"aaaa", b"bbbb"])
            self.assertEqual(mh.speak("request"), "VOICE_SENT")
            self.assertEqual(self.send.call_count, 2)

    def test_successful_chunk_is_synthesized_once(self):
        self.synth.side_effect = None
        self.synth.return_value = b"audio"
        self.assertEqual(mh.speak("request"), "VOICE_SENT")
        self.synth.assert_called_once_with("First.Second.Third.", sl.DEFAULT_VOICE)
        self.send.assert_called_once_with(b"audio")

    def test_checkpoints_are_shared_across_instances_in_this_process(self):
        from media_handler import SpeechDelivery
        first = SpeechDelivery("request-id")
        first.set(0, "sent", 100)
        first.set(1, "uploading")
        second = SpeechDelivery("request-id")
        self.assertEqual(second.get(0), "sent")
        self.assertEqual(second.get(1), "uploading")

    def test_no_database_or_other_file_is_created(self):
        mh.SpeechDelivery("request-id").set_many([0, 1], "sent", 123)
        self.assertEqual(list(Path(self.directory).iterdir()), [])

    def test_cache_is_bounded_and_evicts_least_recently_used_request(self):
        with patch.object(mh, "MAX_VOICE_REQUESTS", 2):
            first = mh.SpeechDelivery("first")
            first.set(0, "sent", 100)
            mh.SpeechDelivery("second").set(0, "uncertain")
            self.assertEqual(first.get(0), "sent")  # refresh first
            mh.SpeechDelivery("third").set(0, "failed")
            self.assertEqual(list(mh._voice_requests), ["first", "third"])
            self.assertEqual(mh.SpeechDelivery("second").get(0), "pending")
            self.assertEqual(len(mh._voice_requests), 2)

    def test_cleared_cache_loses_retry_state(self):
        mh.SpeechDelivery("request-id").set_many([0, 1], "sent", 123)
        mh._voice_requests.clear()  # equivalent to starting with a fresh process
        self.assertEqual(mh.SpeechDelivery("request-id").get(0), "pending")

    def test_group_updates_keep_message_id_and_other_requests_isolated(self):
        first = mh.SpeechDelivery("first")
        first.set_many([0, 1], "sent", 123)
        self.assertEqual(first.get(0), "sent")
        self.assertEqual(first.get(1), "sent")
        self.assertEqual(mh._voice_requests["first"][1]["message_id"], 123)
        self.assertEqual(mh.SpeechDelivery("second").get(0), "pending")


if __name__ == "__main__":
    unittest.main()
