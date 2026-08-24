"""The fixed words in an answer, in both languages.

Only the frame is translated — headings and the handful of sentences paRY
writes itself. Everything else in an answer comes from the compiler or the
corpus and is already in the language it was written in, which is usually
Tamil for code and both for a diagnostic.

A question written in Tamil script is answered in Tamil unless the caller says
otherwise. That is a guess from the question, and `locale` overrides it.
"""

from __future__ import annotations

import re

TAMIL = re.compile(r"[஀-௿]")

PHRASES: dict[str, dict[str, str]] = {
    "definition": {"en": "Definition", "ta": "விளக்கம்"},
    "spellings": {"en": "Spellings", "ta": "எழுத்துருக்கள்"},
    "defined_in": {"en": "Defined in", "ta": "வரையறுக்கப்பட்டது"},
    "used_in": {"en": "Used in", "ta": "பயன்படுத்தப்பட்டுள்ளது"},
    "example": {"en": "A verified example", "ta": "சரிபார்க்கப்பட்ட எடுத்துக்காட்டு"},
    "compiles": {"en": "compiles", "ta": "இயங்குகிறது"},
    "from_docs": {"en": "From the documentation", "ta": "ஆவணங்களிலிருந்து"},
    "why_not_compile": {"en": "Why this does not compile", "ta": "இது ஏன் இயங்கவில்லை"},
    "the_fix": {"en": "The fix", "ta": "திருத்தம்"},
    "it_compiles": {
        "en": "This compiles. `--check` stops before name resolution, so an "
              "undefined name still passes here.",
        "ta": "இது இயங்குகிறது. `--check` பெயர்களைச் சரிபார்ப்பதற்கு முன் நிற்கிறது, "
              "எனவே வரையறுக்கப்படாத பெயரும் இங்கு தேறும்.",
    },
    "uses": {"en": "What it uses", "ta": "பயன்படுத்துவது"},
    "nothing": {
        "en": "Nothing in the corpus answers that. paRY only says what the "
              "compiler and the documentation say — it does not guess.",
        "ta": "அதற்கான விடை தொகுப்பில் இல்லை. தொகுப்பியும் ஆவணங்களும் சொல்வதை "
              "மட்டுமே paRY சொல்கிறது — ஊகிக்காது.",
    },
}


def detect_locale(text: str) -> str:
    """`ta` if the question is written in Tamil script, else `en`."""
    return "ta" if TAMIL.search(text) else "en"


def say(key: str, locale: str) -> str:
    entry = PHRASES[key]
    return entry.get(locale, entry["en"])
