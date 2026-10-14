"""Canonical stored party values; display masks belong to rendering layers."""
import re


def raw_number(value):
    if value is None or value == "":
        return value
    raw = re.sub(r"[\s()+.\-]", "", str(value))
    if not raw or not raw.isascii() or not raw.isdigit():
        raise ValueError("number must contain digits and optional display separators only")
    return raw


def raw_identification(number, code):
    # Foreign and non-taxpayer identifiers may contain letters; never drop them.
    if str(getattr(code, "value", code)) in ("01", "02", "03", "04"):
        return raw_number(number)
    return number.strip() if isinstance(number, str) else number
