"""Markdown parsing and speech-only cleanup, without TTS or network calls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speech_text import prepare_speech


class SpeechTextTests(unittest.TestCase):
    def test_nested_formatting_and_link_destination(self):
        self.assertEqual(prepare_speech(
            '[**Read _this_ guide**](https://example.com/a(b(c)) "title")'),
            'Read this guide')

    def test_reference_links_and_images(self):
        self.assertEqual(prepare_speech(
            '[Read **this**][guide] ![hidden *description*][image]\n\n'
            '[guide]: https://example.com\n[image]: https://example.com/image'),
            'Read this')

    def test_shortcut_and_collapsed_references(self):
        self.assertEqual(prepare_speech(
            '[guide] and [guide][]\n\n[guide]: https://example.com'), 'guide and guide')

    def test_inline_image_nested_destination_is_removed(self):
        self.assertEqual(prepare_speech('Before ![hidden](https://example.com/a(b(c))) after'),
                         'Before after')

    def test_escaped_and_unmatched_delimiters_stay_literal(self):
        self.assertEqual(prepare_speech(r'Keep \*literal\* and [unfinished'),
                         'Keep *literal* and [unfinished')

    def test_code_contents_are_not_parsed_as_markdown(self):
        self.assertEqual(prepare_speech('`a ** b`'), 'a ** b')
        self.assertEqual(prepare_speech('```python\nx = "**value**"\n```'),
                         'x = "**value**"')

    def test_unicode_and_paragraph_breaks(self):
        self.assertEqual(prepare_speech('Привет **мир**\nВторая строка\n\n第三行'),
                         'Привет мир\nВторая строка\n\n第三行')

    def test_lists_headings_and_strikethrough(self):
        self.assertEqual(prepare_speech('# Heading\n- **First**\n- ~~Second~~'),
                         'Heading\nFirst\nSecond')

    def test_html_and_entities(self):
        self.assertEqual(prepare_speech('<div>Hello <b>world</b><br>Again &amp; more</div>'),
                         'Hello world\nAgain & more')
        self.assertEqual(prepare_speech('&lt;literal&gt; &amp; text'), '<literal> & text')

    def test_table_cells_do_not_join_words(self):
        self.assertEqual(prepare_speech('| Name | Value |\n| --- | --- |\n| A | B |'),
                         'Name Value\n\nA B')

    def test_removed_content_is_empty(self):
        for text in ('![hidden](https://example.com)', '<!-- comment -->',
                     'https://example.com', '😀', '---'):
            with self.subTest(text=text):
                self.assertEqual(prepare_speech(text), '')


if __name__ == '__main__':
    unittest.main()
