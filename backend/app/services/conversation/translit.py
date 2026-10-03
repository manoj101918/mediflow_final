# ruff: noqa: RUF001 - Telugu/Devanagari letters are the point of this module.
"""Rough Telugu / Devanagari -> Latin transliteration, only to match spoken doctor names.

"శర్మ" and "शर्मा" both become "sharma", so a voice note naming "Dr. Sharma" in Telugu or
Hindi can be matched against "Dr. Anil Sharma". Not a general transliterator.
"""

import difflib
import unicodedata

# Consonants (inherent "a"), independent vowels, vowel signs; Telugu then Devanagari.
_CONSONANTS = {
    "క": "k", "ఖ": "kh", "గ": "g", "ఘ": "gh", "ఙ": "n", "చ": "ch", "ఛ": "chh", "జ": "j",
    "ఝ": "jh", "ఞ": "n", "ట": "t", "ఠ": "th", "డ": "d", "ఢ": "dh", "ణ": "n", "త": "t",
    "థ": "th", "ద": "d", "ధ": "dh", "న": "n", "ప": "p", "ఫ": "ph", "బ": "b", "భ": "bh",
    "మ": "m", "య": "y", "ర": "r", "ఱ": "r", "ల": "l", "ళ": "l", "వ": "v", "శ": "sh",
    "ష": "sh", "స": "s", "హ": "h",
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j",
    "झ": "jh", "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t",
    "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh",
    "म": "m", "य": "y", "र": "r", "ल": "l", "ळ": "l", "व": "v", "श": "sh", "ष": "sh",
    "स": "s", "ह": "h",
}  # fmt: skip
_VOWELS = {
    "అ": "a", "ఆ": "aa", "ఇ": "i", "ఈ": "ee", "ఉ": "u", "ఊ": "oo", "ఋ": "ru", "ఎ": "e",
    "ఏ": "e", "ఐ": "ai", "ఒ": "o", "ఓ": "o", "ఔ": "au",
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e",
    "ऐ": "ai", "ओ": "o", "औ": "au",
}  # fmt: skip
_SIGNS = {
    "ా": "aa", "ి": "i", "ీ": "ee", "ు": "u", "ూ": "oo", "ృ": "ru", "ె": "e", "ే": "e",
    "ై": "ai", "ొ": "o", "ో": "o", "ౌ": "au",
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai",
    "ो": "o", "ौ": "au", "ॉ": "o",
}  # fmt: skip
_VIRAMA = {"్", "्"}
_NASAL = {"ం": "m", "ँ": "n", "ं": "n"}


def to_latin(text: str) -> str:
    out: list[str] = []
    chars = list(unicodedata.normalize("NFC", text))
    for index, ch in enumerate(chars):
        nxt = chars[index + 1] if index + 1 < len(chars) else ""
        if ch in _CONSONANTS:
            out.append(_CONSONANTS[ch])
            if nxt not in _SIGNS and nxt not in _VIRAMA:
                out.append("a")
        elif ch in _VOWELS:
            out.append(_VOWELS[ch])
        elif ch in _SIGNS:
            out.append(_SIGNS[ch])
        elif ch in _NASAL:
            out.append(_NASAL[ch])
        elif ch in _VIRAMA or ch in ("‌", "‍", "़"):
            continue
        else:
            out.append(ch.lower())
    return "".join(out)


def _squash(word: str) -> str:
    """Spelling-insensitive key: drop doubled vowels and 'h' after consonants."""
    word = word.replace("aa", "a").replace("ee", "i").replace("oo", "u")
    return word.replace("sh", "s").replace("th", "t").replace("dh", "d").replace("ph", "f")


def name_score(spoken_word: str, name_word: str) -> float:
    """How alike a (possibly Indic-script) spoken word is to a Latin name word, 0..1."""
    a = _squash(to_latin(spoken_word).strip(".,!?").lower())
    b = _squash(name_word.strip(".,").lower())
    if len(a) < 3 or len(b) < 3:
        return 0.0
    # Spoken Indic words often end with an extra inherent "a" ("sharma" vs "sharm").
    return max(
        difflib.SequenceMatcher(None, a, b).ratio(),
        difflib.SequenceMatcher(None, a.rstrip("a"), b.rstrip("a")).ratio(),
    )
