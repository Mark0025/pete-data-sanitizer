from __future__ import annotations


def test_normalize_phone_strips_trailing_dot_zero() -> None:
    from build_staging import normalize_phone

    assert normalize_phone("5551112222.0") == "5551112222"
    assert normalize_phone(5551112222.0) == "5551112222"


def test_normalize_phone_strips_leading_country_code() -> None:
    from build_staging import normalize_phone

    assert normalize_phone("1 (555) 111-2222") == "5551112222"

