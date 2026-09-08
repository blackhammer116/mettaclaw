"""Plain spoken text for TTS; leaves the original chat text untouched."""
import html
import re


def prepare_speech(text):
    text = html.unescape(text.replace("\\n", "\n"))
    # Keep a link's readable label, but omit image descriptions and destinations.
    text = re.sub(r"!\[[^\]]*\]\([^\n]*?\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\((?:[^()\n]|\([^()\n]*\))*\)", r"\1", text)
    text = re.sub(r"(?im)^\s*\[[^\]]+\]:\s*\S+.*$", "", text)
    text = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"(?:https?://|www\.)[^\s<>]+", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"(?m)^\s*```[^\n]*$", "", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)", "", text)
    text = re.sub(r"(\*\*|__|~~)(.*?)\1", r"\2", text, flags=re.S)
    text = re.sub(r"(?<!\w)(\*|_)(\S(?:.*?\S)?)\1(?!\w)", r"\2", text)
    text = re.sub(r"`+([^`]+)`+", r"\1", text)
    # Emoji, their joiners/modifiers and keycap sequences, preserving ordinary
    # digits, punctuation and non-Latin letters.
    text = re.sub(r"[0-9#*]\ufe0f?\u20e3", "", text)
    text = re.sub(r"[\U0001f000-\U0001faff\u2600-\u27bf\u200d\ufe0f\u20e3]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.splitlines()).strip()
    return text if any(char.isalnum() for char in text) else ""
