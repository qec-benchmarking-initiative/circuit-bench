"""Shared human-readable formatting for scientific registry values."""

from decimal import Decimal, InvalidOperation


def format_scientific_value(value: object, *, significant_digits: int = 4) -> str:
    """Render a numeric value compactly without exposing storage-scale zeros.

    This is deliberately a presentation formatter. Stored values, form values,
    query parameters, CSV, and JSON should continue to use their exact forms.
    """

    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    if not number.is_finite():
        return str(number)
    if number == 0:
        return "0"

    significant_digits = max(1, significant_digits)
    exponent = number.copy_abs().adjusted()
    if exponent <= -2 or exponent >= 4:
        mantissa = number.scaleb(-exponent)
        rendered = _trim_decimal(format(mantissa, f".{significant_digits - 1}f"))
        # Rounding 9.999... must not produce the awkward, non-normalized 10eN.
        if Decimal(rendered).copy_abs() >= 10:
            exponent += 1
            rendered = _trim_decimal(
                format(Decimal(rendered).scaleb(-1), f".{significant_digits - 1}f")
            )
        return f"{rendered}e{exponent}"

    decimal_places = max(0, significant_digits - exponent - 1)
    return _trim_decimal(format(number, f".{decimal_places}f"))


def format_scientific_range(
    minimum: object,
    maximum: object,
    *,
    empty_label: str | None = None,
    minimum_fallback: str = "0",
    maximum_fallback: str = "∞",
    significant_digits: int = 4,
) -> str:
    """Render a human-facing range while keeping its submitted bounds separate."""

    minimum_missing = minimum is None or str(minimum).strip() == ""
    maximum_missing = maximum is None or str(maximum).strip() == ""
    if minimum_missing and maximum_missing and empty_label is not None:
        return empty_label
    minimum_display = (
        minimum_fallback
        if minimum_missing
        else format_scientific_value(minimum, significant_digits=significant_digits)
    )
    maximum_display = (
        maximum_fallback
        if maximum_missing
        else format_scientific_value(maximum, significant_digits=significant_digits)
    )
    return f"{minimum_display}–{maximum_display}"


def _trim_decimal(value: str) -> str:
    return value.rstrip("0").rstrip(".") if "." in value else value
