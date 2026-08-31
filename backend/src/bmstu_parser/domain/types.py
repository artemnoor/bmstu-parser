from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any


Money = Decimal


@dataclass(frozen=True, slots=True)
class ParsedNumber:
    """A typed numeric value together with the source representation.

    Source APIs are not consistent about numeric fields: the same value can
    arrive as an integer, a formatted string, an em dash, or an empty value.
    The canonical layer keeps the typed value and the original text so a
    failed conversion is visible instead of silently becoming a made-up
    number.
    """

    value: int | Decimal | None
    raw: str
    warning: str | None = None


def raw_number(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    return str(value).strip()


def _normalized_number_text(value: Any) -> str:
    text = raw_number(value)
    if not text or text.casefold() in {
        "-",
        "—",
        "–",
        "нет",
        "н/д",
        "н.д.",
        "none",
        "null",
    }:
        return ""
    text = (
        text.replace("\u00a0", " ")
        .replace("₽", "")
        .replace("руб.", "")
        .replace("руб", "")
    )
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^0-9,.+-]", "", text)
    if not text or text in {"-", "+", ".", ","}:
        return ""

    # Treat the last separator as a decimal separator when both styles are
    # present. A lone comma with one or two trailing digits is decimal; other
    # commas are thousands separators.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        chunks = text.split(",")
        if len(chunks) == 2 and len(chunks[1]) in {1, 2}:
            text = ".".join(chunks)
        else:
            text = "".join(chunks)
    return text


def parse_int(value: Any, field_name: str) -> ParsedNumber:
    raw = raw_number(value)
    if value is None or raw.casefold() in {
        "",
        "-",
        "—",
        "–",
        "нет",
        "н/д",
        "н.д.",
        "none",
        "null",
    }:
        return ParsedNumber(None, raw)
    if isinstance(value, bool):
        return ParsedNumber(None, raw, f"{field_name}: boolean is not a valid integer")
    try:
        text = _normalized_number_text(value)
        if not text:
            return ParsedNumber(
                None, raw, f"{field_name}: cannot parse integer {raw!r}"
            )
        decimal = Decimal(text)
        if not decimal.is_finite() or decimal != decimal.to_integral_value():
            raise InvalidOperation
        return ParsedNumber(int(decimal), raw)
    except (InvalidOperation, ValueError):
        return ParsedNumber(None, raw, f"{field_name}: cannot parse integer {raw!r}")


def parse_decimal(value: Any, field_name: str) -> ParsedNumber:
    raw = raw_number(value)
    if value is None or raw.casefold() in {
        "",
        "-",
        "—",
        "–",
        "нет",
        "н/д",
        "н.д.",
        "none",
        "null",
    }:
        return ParsedNumber(None, raw)
    if isinstance(value, bool):
        return ParsedNumber(None, raw, f"{field_name}: boolean is not a valid decimal")
    try:
        text = _normalized_number_text(value)
        if not text:
            return ParsedNumber(
                None, raw, f"{field_name}: cannot parse decimal {raw!r}"
            )
        decimal = Decimal(text)
        if not decimal.is_finite():
            raise InvalidOperation
        return ParsedNumber(decimal, raw)
    except (InvalidOperation, ValueError):
        return ParsedNumber(None, raw, f"{field_name}: cannot parse decimal {raw!r}")


def decimal_to_wire(value: Decimal | None) -> str | None:
    """Serialize money without losing precision or locale-independent meaning."""

    if value is None:
        return None
    return format(value, "f")


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_to_wire(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
