from decimal import Decimal

from registry.formatting import format_scientific_value


def test_scientific_values_use_compact_significant_digits():
    assert format_scientific_value(Decimal("0.02300000000000000000")) == "2.3e-2"
    assert format_scientific_value(Decimal("0.00230000000000000000")) == "2.3e-3"
    assert format_scientific_value(Decimal("0.15000000000000000000")) == "0.15"
    assert format_scientific_value(Decimal("1.23456")) == "1.235"
    assert format_scientific_value(Decimal("12340")) == "1.234e4"
    assert format_scientific_value(Decimal("0")) == "0"


def test_scientific_value_formatter_leaves_non_numbers_readable():
    assert format_scientific_value("not reported") == "not reported"
