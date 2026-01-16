from __future__ import annotations

from pete_dm_clean.app_config import AppConfig


def test_config_defaults():
    cfg = AppConfig.from_yaml_dict({})
    assert cfg.serve.port == 8765
    assert cfg.thresholds.match_warn_pct == 95.0


def test_config_overrides():
    cfg = AppConfig.from_yaml_dict(
        {
            "thresholds": {"match_warn_pct": 99.0},
            "generators": {"pete_properties_import": {"max_sellers": 7}},
        }
    )
    assert cfg.thresholds.match_warn_pct == 99.0
    assert cfg.generators.pete_properties_import.max_sellers == 7

