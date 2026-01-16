from __future__ import annotations


def test_export_prefix_from_input_filename_short_slug() -> None:
    from build_staging import export_prefix_from_input_filename

    assert export_prefix_from_input_filename("Lake City FL - Leads (1).csv") == "lake-city-fl-leads.pete.clean"
    assert export_prefix_from_input_filename("Some Weird__Name 2026.csv") == "some-weird-name.pete.clean"

