"""Shared human-readable formatting for scientific registry values."""

from decimal import Decimal, InvalidOperation


def format_scientific_value(value: object, *, significant_digits: int = 4) -> str:
    """Render a numeric value compactly without exposing storage-scale zeros."""

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
        rendered = _trim_decimal(
            format(mantissa, f".{significant_digits - 1}f")
        )
        return f"{rendered}e{exponent}"

    decimal_places = max(0, significant_digits - exponent - 1)
    return _trim_decimal(format(number, f".{decimal_places}f"))


def _trim_decimal(value: str) -> str:
    return value.rstrip("0").rstrip(".") if "." in value else value
