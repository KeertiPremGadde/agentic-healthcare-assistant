"""Character-level normalisation in front of the deterministic safety rules (ADR 0026).

The rules match plain spellings. A message the rules catch in plain text got through when it
was spelled differently: a zero-width space (U+200B) inside a word, spaced or dotted letters
("k i l l", "k.i.l.l"), digits for letters ("k1ll"), look-alike Cyrillic or Greek letters,
full-width letters, combining marks, or a typographic apostrophe (U+2019) in "don't". The router,
the second layer, is a model: for some such input it returned nothing at all.

`variants(text)` returns the message itself FIRST, then its folded spellings. The rules run on every
variant and the first hit wins, so folding can only ADD a safety reply: a message the rules already
decided about keeps exactly that decision, and the user's own text is never changed for the model.

What each fold does, and the false alarms it is built to avoid:
- NFKC (full-width letters, ligatures), then every format character (zero-width, soft hyphen, bidi
  marks) and every combining mark that did not compose into a letter is removed: an umlaut stays,
  a strike-through goes.
- Typographic quotes and apostrophes become the plain ones.
- Cyrillic and Greek letters that look like Latin ones become those letters.
- A run of three or more single letters separated by the SAME separator (a space, a dot, a hyphen,
  an underscore or an asterisk) is joined, so "h o w   m a n y" and "k.i.l.l" work; a word gap of
  two or more spaces ends a run. A run with single spaces between words cannot be told apart from
  letter spacing and is left alone (the router is the net there).
- Digits and "@" "$" inside a word of three or more letters become letters ("k1ll", "d0se",
  "l3thal"), except in measurements ("5mg", "3D"), identifiers ("B12", "COVID19") and words with too
  few letters. "1" is tried as "i" and as "l" ("k1ll", "pi11s").
"""

import re
import unicodedata

# Typographic single and double quotes, primes and accents -> the plain ASCII quote.
_QUOTES = str.maketrans(
    {
        0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'", 0x02BC: "'", 0x2032: "'",
        0x00B4: "'", 0x0060: "'",
        0x201C: '"', 0x201D: '"', 0x201E: '"', 0x2033: '"',
    }
)  # fmt: skip

# Look-alikes only (a letter that is visually the Latin one in most fonts), not transliterations.
_HOMOGLYPHS = str.maketrans(
    {
        # Cyrillic, lower case
        0x0430: "a", 0x0435: "e", 0x043E: "o", 0x0440: "p", 0x0441: "c", 0x0443: "y",
        0x0445: "x", 0x0456: "i", 0x0458: "j", 0x0455: "s", 0x0501: "d", 0x04CF: "l",
        0x043A: "k",
        # Cyrillic, upper case
        0x0410: "A", 0x0412: "B", 0x0415: "E", 0x041A: "K", 0x041C: "M", 0x041D: "H",
        0x041E: "O", 0x0420: "P", 0x0421: "C", 0x0422: "T", 0x0425: "X", 0x0406: "I",
        0x0408: "J", 0x0405: "S", 0x0423: "Y",
        # Greek
        0x03BF: "o", 0x03BD: "v", 0x03B9: "i", 0x03BA: "k", 0x03C1: "p", 0x03C5: "u",
        0x03B1: "a",
        0x0391: "A", 0x0392: "B", 0x0395: "E", 0x0396: "Z", 0x0397: "H", 0x0399: "I",
        0x039A: "K", 0x039C: "M", 0x039D: "N", 0x039F: "O", 0x03A1: "P", 0x03A4: "T",
        0x03A5: "Y", 0x03A7: "X",
    }
)  # fmt: skip

_LEET = str.maketrans({"0": "o", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})

_LETTER = r"[^\W\d_]"
_SEPARATORS = r"[ .\-_*·]"  # space, dot, hyphen, underscore, asterisk, middle dot
# Three or more single letters with the same separator between them, not inside a longer word.
# The run may not start right after a letter or a dot-like separator, or it would begin in the
# middle of another run ("i.s a l.e.t.h.a.l": the "s a l" is not a run).
_SPACED = re.compile(
    rf"(?<![\w.\-*·])({_LETTER})(?P<sep>{_SEPARATORS})(?:{_LETTER}(?P=sep))+{_LETTER}(?![^\W_])"
)
# Two letters with a dot-like separator ("i.s"), or two spaced letters between word gaps ("t o").
_SHORT_DOTTED = re.compile(rf"(?<![^\W_])({_LETTER})[.\-_*]({_LETTER})(?![^\W_])")
_SHORT_SPACED = re.compile(rf"(?:(?<=\s\s)|^)({_LETTER}) ({_LETTER})(?=\s\s|$)")
_TOKEN = re.compile(r"[A-Za-z0-9@$]+")
# A number glued to a unit: 5mg, 3D, 4weeks, 10am. Not "1ethal" (a digit for a letter).
_MEASUREMENT = re.compile(
    r"^\d+(?:[.,]\d+)?(?:mg|mcg|ug|g|kg|ml|l|dl|cl|iu|h|hr|hrs|min|s|sec|d|day|days|w|wk|week|weeks"
    r"|month|months|m|y|yr|yrs|year|years|am|pm|x|th|st|nd|rd|cm|mm|km|cc|tabs?|tablets?|pills?)$",
    re.IGNORECASE,
)
_TRAILING_DIGITS = re.compile(r"^[a-z]+\d+$", re.IGNORECASE)  # B12, COVID19, MP3
_MAX_VARIANTS = 8


def _clean(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text)
    # Cf: zero-width and bidi marks. Mn: combining marks that did not compose into a letter.
    kept = [ch for ch in folded if unicodedata.category(ch) not in ("Cf", "Mn")]
    return "".join(kept).translate(_QUOTES).translate(_HOMOGLYPHS)


def _despace(text: str) -> str:
    joined = _SPACED.sub(lambda m: re.sub(_SEPARATORS, "", m.group(0)), text)
    if joined == text:
        return joined
    # The message IS letter-spaced, so its short words are too ("i.s", "t o", "u m"): join those
    # as well. Only here: "e.g" or "a b" in an ordinary message are left alone.
    joined = _SHORT_DOTTED.sub(lambda m: m.group(1) + m.group(2), joined)
    return _SHORT_SPACED.sub(lambda m: m.group(1) + m.group(2), joined)


def _leet(text: str, one_as: str) -> str:
    def token(m: re.Match[str]) -> str:
        word = m.group(0)
        letters = sum(c.isalpha() for c in word)
        if letters < 3 or letters == len(word):
            return word
        if _MEASUREMENT.match(word) or _TRAILING_DIGITS.match(word):
            return word
        if not any(c in "013457@$" for c in word):
            return word
        return word.replace("1", one_as).translate(_LEET)

    return _TOKEN.sub(token, text)


def variants(text: str) -> list[str]:
    """The message itself, then its folded spellings (see the module docstring)."""
    clean = _clean(text)
    despaced = _despace(clean)
    candidates: list[str] = []
    for base in (clean, despaced):
        candidates.append(base)
        for one_as in ("i", "l"):
            candidates.append(_leet(base, one_as))
    out = [text]
    for candidate in candidates:
        if candidate not in out:
            out.append(candidate)
    return out[:_MAX_VARIANTS]
