"""Detect speech language locally and select voices without changing config."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import logging
import re

from text_splitter import split_for_telegram

logger = logging.getLogger(__name__)
DEFAULT_VOICE = "en-US-AriaNeural"
PREFERRED_VOICES = {"en": DEFAULT_VOICE, "ru": "ru-RU-SvetlanaNeural"}


@lru_cache(maxsize=1)
def _detector():
    from lingua import LanguageDetectorBuilder
    # Load models lazily; standard mode also recognises short Cyrillic phrases.
    return LanguageDetectorBuilder.from_all_languages().build()


def detect_language(text):
    letters = [char.lower() for char in text if char.isalpha()]
    if len(letters) < 5 or len(set(letters)) < 3:
        return None
    scores = _detector().compute_language_confidence_values(text[:4096])
    # Scores are relative across all languages, not calibrated probabilities.
    if not scores or scores[0].value < .35:
        return None
    if len(scores) > 1 and scores[0].value - scores[1].value < .10:
        return None
    return scores[0].language.iso_code_639_1.name.lower()


def _language(code):
    code = code.lower().split("-")[0]
    return {"nb": "no", "nn": "no"}.get(code, code)


@lru_cache(maxsize=1)
def available_voices():
    """Cache successful catalogue requests; a failed request can be retried."""
    import edge_tts

    async def fetch():
        return await asyncio.wait_for(edge_tts.list_voices(), timeout=10)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(fetch())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, fetch()).result()


def select_voice(language, configured_voice):
    if language is None or _language(language) == _language(configured_voice):
        return configured_voice
    candidates = sorted(
        voice["ShortName"] for voice in available_voices()
        if _language(voice.get("Locale", "")) == _language(language)
        and voice.get("ShortName")
    )
    if not candidates:
        raise ValueError(f"No speech voice available for detected language {language}")
    preferred = PREFERRED_VOICES.get(language)
    return preferred if preferred in candidates else candidates[0]


def speech_parts(text, configured_voice=DEFAULT_VOICE):
    """Route sentences/lines, merge adjacent voices, then apply text splitting.

    Preserve every character until the existing Telegram splitter runs. Mixed
    languages within a single sentence use that sentence's detected language.
    """
    segments = []
    start = 0
    for boundary in re.finditer(r"(?<=[.!?。！？])\s+|\n+", text):
        segments.append(text[start:boundary.end()])
        start = boundary.end()
    if start < len(text):
        segments.append(text[start:])
    runs = []
    for segment in segments:
        if not segment.strip():
            continue
        language = detect_language(segment)
        voice = select_voice(language, configured_voice)
        logger.info("Speech language=%s voice=%s", language or "uncertain", voice)
        if runs and runs[-1][1] == voice:
            runs[-1] = (runs[-1][0] + segment, voice)
        else:
            runs.append((segment, voice))
    return [(piece, voice) for segment, voice in runs
            for piece in split_for_telegram(segment)]
