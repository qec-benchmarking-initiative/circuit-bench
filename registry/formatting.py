"""One display policy for scientific quantities across Circuit Bench.

The functions in this module are presentation-only. Database values, form
values, query parameters, JSON, and CSV must continue to use their exact,
machine-readable representations.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class NumberProfile:
    """Formatting choices for one broad class of scientific quantities."""

    significant_digits: int = 4
    scientific_below_exponent: int = -2
    scientific_from_exponent: int = 4
    group_thousands: bool = True


@dataclass(frozen=True)
class NumberDisplay:
    """Structured display parts that HTML and SVG renderers can share."""

    raw: str
    text: str
    accessible_text: str
    scientific: bool = False
    mantissa: str | None = None
    exponent: int | None = None
    exponent_text: str | None = None
    unit: str | None = None
    valid_number: bool = True


NUMBER_PROFILES: dict[str, NumberProfile] = {
    "default": NumberProfile(),
    # Counts remain easy to scan as grouped integers until they reach a million.
    "count": NumberProfile(scientific_below_exponent=-99, scientific_from_exponent=6),
    "probability": NumberProfile(significant_digits=3),
    "duration": NumberProfile(significant_digits=4),
    "score": NumberProfile(significant_digits=4),
}

_SUPERSCRIPT_TRANSLATION = str.maketrans("-+0123456789", "⁻⁺⁰¹²³⁴⁵⁶⁷⁸⁹")


def scientific_number_display(
    value: object,
    *,
    profile: str | NumberProfile | None = None,
    significant_digits: int | None = None,
    unit: str | None = None,
) -> NumberDisplay:
    """Return exact raw data and structured, human-facing display parts."""

    raw = str(value)
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return NumberDisplay(
            raw=raw,
            text=str(value),
            accessible_text=str(value),
            unit=unit,
            valid_number=False,
        )
    if not number.is_finite():
        text = str(number)
        return NumberDisplay(
            raw=raw,
            text=text,
            accessible_text=text,
            unit=unit,
            valid_number=False,
        )

    policy = _profile(profile)
    digits = max(
        1,
        significant_digits
        if significant_digits is not None
        else policy.significant_digits,
    )
    if number == 0:
        return NumberDisplay(raw=raw, text="0", accessible_text="0", unit=unit)

    exponent = number.copy_abs().adjusted()
    use_scientific = (
        exponent <= policy.scientific_below_exponent
        or exponent >= policy.scientific_from_exponent
    )
    if use_scientific:
        mantissa = number.scaleb(-exponent)
        rendered = _trim_decimal(format(mantissa, f".{digits - 1}f"))
        # Rounding 9.999... must result in 1 × 10^(n+1), never 10 × 10^n.
        if Decimal(rendered).copy_abs() >= 10:
            exponent += 1
            rendered = _trim_decimal(
                format(Decimal(rendered).scaleb(-1), f".{digits - 1}f")
            )
        exponent_text = str(exponent).translate(_SUPERSCRIPT_TRANSLATION)
        text = f"{rendered}\u2009·\u200910{exponent_text}"
        accessible = f"{rendered} times ten to the power of {exponent}"
        return NumberDisplay(
            raw=raw,
            text=text,
            accessible_text=accessible,
            scientific=True,
            mantissa=rendered,
            exponent=exponent,
            exponent_text=exponent_text,
            unit=unit,
        )

    decimal_places = max(0, digits - exponent - 1)
    rendered = _trim_decimal(format(number, f".{decimal_places}f"))
    if policy.group_thousands:
        rendered = _group_thousands(rendered)
    return NumberDisplay(
        raw=raw,
        text=rendered,
        accessible_text=rendered,
        unit=unit,
    )


def format_scientific_value(
    value: object,
    *,
    significant_digits: int | None = None,
    profile: str | NumberProfile | None = None,
) -> str:
    """Return the plain-text form for SVG, labels, and other text-only uses."""

    return scientific_number_display(
        value,
        profile=profile,
        significant_digits=significant_digits,
    ).text


def format_scientific_range(
    minimum: object,
    maximum: object,
    *,
    empty_label: str | None = None,
    minimum_fallback: str = "0",
    maximum_fallback: str = "∞",
    significant_digits: int | None = None,
    profile: str | NumberProfile | None = None,
) -> str:
    """Render a human-facing range while retaining submitted bounds elsewhere."""

    minimum_missing = minimum is None or str(minimum).strip() == ""
    maximum_missing = maximum is None or str(maximum).strip() == ""
    if minimum_missing and maximum_missing and empty_label is not None:
        return empty_label
    minimum_display = (
        minimum_fallback
        if minimum_missing
        else format_scientific_value(
            minimum, significant_digits=significant_digits, profile=profile
        )
    )
    maximum_display = (
        maximum_fallback
        if maximum_missing
        else format_scientific_value(
            maximum, significant_digits=significant_digits, profile=profile
        )
    )
    return f"{minimum_display}–{maximum_display}"


def _profile(profile: str | NumberProfile | None) -> NumberProfile:
    if isinstance(profile, NumberProfile):
        return profile
    return NUMBER_PROFILES.get(profile or "default", NUMBER_PROFILES["default"])


def _trim_decimal(value: str) -> str:
    return value.rstrip("0").rstrip(".") if "." in value else value


def _group_thousands(value: str) -> str:
    sign = ""
    unsigned = value
    if unsigned.startswith(("-", "+")):
        sign, unsigned = unsigned[0], unsigned[1:]
    integer, separator, fractional = unsigned.partition(".")
    grouped = f"{int(integer):,}" if integer else "0"
    return f"{sign}{grouped}{separator}{fractional}"
