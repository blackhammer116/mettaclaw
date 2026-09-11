"""Detect speech language locally and select voices without changing config."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import logging
import re

from text_splitter import split_for_telegram


def speech_chunks(parts):
    """Pack indexed sentence pieces without crossing voices or the text limit."""
    chunk = []
    size = 0
    for part in parts:
        _, text, voice = part
        if chunk and (voice != chunk[-1][2] or size + len(text) > 4096):
            yield chunk
            chunk, size = [], 0
        chunk.append(part)
        size += len(text)
    if chunk:
        yield chunk

logger = logging.getLogger(__name__)
DEFAULT_VOICE = "en-US-AriaNeural"
PREFERRED_VOICES = {"en": DEFAULT_VOICE, "ru": "ru-RU-SvetlanaNeural"}


@lru_cache(maxsize=1)
def _detector():
    from lingua import LanguageDetectorBuilder
    # Load models lazily; standard mode also recognises short Cyrillic phrases.
    return LanguageDetectorBuilder.from_all_languages().build()


@lru_cache(maxsize=1)
def _cyrillic_detector():
    from lingua import LanguageDetectorBuilder, Language
    return LanguageDetectorBuilder.from_languages(Language.RUSSIAN, Language.UKRAINIAN).build()


def _script_is_main(text, pattern):
    words = len(re.findall(pattern, text))
    return words > 0 and words >= len(re.findall(r"[A-Za-z]+", text))


def detect_language(text):
    # Script hints protect short phrases and non-Latin text containing product
    # names from being routed to an English-only voice.
    if _script_is_main(text, r"[\u3040-\u30ff]+"):
        return "ja"
    if _script_is_main(text, r"[\uac00-\ud7af]+"):
        return "ko"
    if _script_is_main(text, r"[\u3400-\u9fff]+"):
        return "zh"
    if _script_is_main(text, r"[\u0400-\u052f]+"):
        if re.search(r"[іїєґІЇЄҐ]", text):
            return "uk"
        text = re.sub(r"[A-Za-z]+", " ", text)
        if re.search(r"[ыэёъЫЭЁЪ]", text):
            return "ru"
    else:
        # A brief foreign quotation must not outweigh a mostly Latin reply.
        non_latin = r"[^\W\d_A-Za-z\u00c0-\u024f]+"
        if len(re.findall(r"[A-Za-z\u00c0-\u024f]+", text)) > len(re.findall(non_latin, text)):
            text = re.sub(non_latin, " ", text)
    letters = [char.lower() for char in text if char.isalpha()]
    if len(letters) < 5 or len(set(letters)) < 3:
        return None
    scores = _detector().compute_language_confidence_values(text)
    if _script_is_main(text, r"[\u0400-\u052f]+") and (
            not scores or scores[0].value < .35):
        scores = _cyrillic_detector().compute_language_confidence_values(text)
        if scores and scores[0].value >= .60:
            return scores[0].language.iso_code_639_1.name.lower()
        return None
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
    # Keep the configured voice for its own language and uncertain text.
    if language is None or _language(language) == _language(configured_voice):
        return configured_voice
    language = _language(language)
    voices = available_voices()
    gender = next((voice.get("Gender") for voice in voices
                   if voice.get("ShortName") == configured_voice), None)
    if gender not in ("Female", "Male"):
        raise ValueError(f"Cannot determine gender of configured voice {configured_voice}")
    candidates = sorted(
        voice["ShortName"] for voice in voices
        if _language(voice.get("Locale", "")) == _language(language)
        and voice.get("ShortName")
        and voice.get("Gender") == gender
    )
    if not candidates:
        logger.warning(
            "No %s speech voice for detected language %s; using configured voice %s",
            gender.lower(), language, configured_voice,
        )
        return configured_voice
    preferred = PREFERRED_VOICES.get(language)
    return preferred if preferred in candidates else candidates[0]


@lru_cache(maxsize=64)
def validated_voice(configured_voice):
    """Cache successful validation only; catalogue outages are not typos."""
    if any(v.get("ShortName") == configured_voice for v in available_voices()):
        return configured_voice
    logger.warning("Unknown configured voice %r; using %s", configured_voice, DEFAULT_VOICE)
    return DEFAULT_VOICE


def speech_parts(text, configured_voice=DEFAULT_VOICE):
    """Select one voice for the whole reply; retain sentences for chunk retries."""
    configured_voice = validated_voice(configured_voice)
    language = detect_language(text)
    if language is None and _script_is_main(text, r"[\u0400-\u052f]+"):
        language = _language(configured_voice)
        if language not in ("ru", "uk"):
            language = "ru"
    voice = select_voice(language, configured_voice)
    logger.info("Speech language=%s voice=%s", language or "uncertain", voice)
    segments = []
    start = 0
    for boundary in re.finditer(r"(?<=[.!?。！？])\s+|\n+", text):
        segments.append(text[start:boundary.end()])
        start = boundary.end()
    if start < len(text):
        segments.append(text[start:])
    return [(piece, voice) for segment in segments
            for piece in split_for_telegram(segment)]
