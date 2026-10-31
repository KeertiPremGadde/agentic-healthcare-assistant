"""PII masking for anything that might reach logs or traces.

Policy: logs never contain message text at all (only routes, counts, timings, token usage).
`mask_pii` is the safety net for the few places that log free text, such as error summaries.
"""

import hashlib
import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s()/-]{6,}\d(?!\w)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")
_DATE = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")


def mask_pii(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _IBAN.sub("[iban]", text)
    text = _DATE.sub("[date]", text)
    return _PHONE.sub("[phone]", text)


def pseudonymise(value: str | int, salt: str = "medagent") -> str:
    """Stable, non-reversible id for correlating logs without storing the real identifier."""
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:12]
