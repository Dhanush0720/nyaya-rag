"""Language names and script-based language detection for Indian languages."""

NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "te": "Telugu", "ta": "Tamil",
    "kn": "Kannada", "ml": "Malayalam", "bn": "Bengali", "gu": "Gujarati",
    "pa": "Punjabi", "or": "Odia",
}

# Unicode blocks. Devanagari is reported as Hindi: Hindi and Marathi share the
# script, so the uploader can override the language when it is Marathi.
_SCRIPTS = [
    ("te", 0x0C00, 0x0C7F), ("kn", 0x0C80, 0x0CFF), ("ml", 0x0D00, 0x0D7F),
    ("ta", 0x0B80, 0x0BFF), ("bn", 0x0980, 0x09FF), ("hi", 0x0900, 0x097F),
    ("gu", 0x0A80, 0x0AFF), ("pa", 0x0A00, 0x0A7F), ("or", 0x0B00, 0x0B7F),
]


def detect_lang(text: str) -> str:
    counts = {code: 0 for code, _, _ in _SCRIPTS}
    latin = 0
    for ch in text[:5000]:
        if not ch.isalpha():
            continue
        cp = ord(ch)
        if cp < 0x250:
            latin += 1
            continue
        for code, lo, hi in _SCRIPTS:
            if lo <= cp <= hi:
                counts[code] += 1
                break
    best = max(counts, key=counts.get)
    return best if counts[best] > latin else "en"


def lang_name(code: str) -> str:
    return NAMES.get(code, "English")
