"""Plain spoken text for TTS; leaves the original chat text untouched."""
from html.parser import HTMLParser
import re

import pyromark


class _HTMLText(HTMLParser):
    """Extract data from raw HTML events without treating Markdown text as HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li"}:
            self.parts.append("\n")


def _markdown_text(text):
    """Keep textual parser events, omitting image subtrees and destinations."""
    source = text.encode("utf-8")  # Parser ranges are UTF-8 byte offsets.
    parts = []
    previous_end = 0
    image_depth = 0
    options = (pyromark.Options.ENABLE_STRIKETHROUGH
               | pyromark.Options.ENABLE_TABLES
               | pyromark.Options.ENABLE_TASKLISTS)
    for event, span in pyromark.events_with_range(text, options=options):
        match event:
            case {"Start": {"Image": _}}:
                image_depth += 1
                continue
            case {"End": "Image"}:
                image_depth -= 1
                continue
            case _ if image_depth:
                continue
            case {"Text": content} | {"Code": content}:
                pass
            case {"Html": content} | {"InlineHtml": content}:
                parser = _HTMLText()
                parser.feed(content)
                parser.close()
                content = "".join(parser.parts)
            case _:
                continue
        # Source gaps retain line/paragraph breaks without interpreting their
        # Markdown delimiters. Spaces separate cells in a Markdown table.
        if parts:
            gap = source[previous_end:span["start"]]
            if b"\n" in gap:
                parts.append("\n" * gap.count(b"\n"))
            elif b"|" in gap:
                parts.append(" ")
        parts.append(content)
        previous_end = span["end"]
    return "".join(parts)


def prepare_speech(text):
    text = _markdown_text(text.replace("\\n", "\n"))
    # Bare URLs are speech policy, not Markdown syntax.
    text = re.sub(r"(?:https?://|www\.)[^\s<>]+", "", text)
    # Emoji, their joiners/modifiers and keycap sequences, preserving ordinary
    # digits, punctuation and non-Latin letters.
    text = re.sub(r"[0-9#*]\ufe0f?\u20e3", "", text)
    text = re.sub(r"[\U0001f000-\U0001faff\u2600-\u27bf\u200d\ufe0f\u20e3]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.splitlines()).strip()
    return text if any(char.isalnum() for char in text) else ""
