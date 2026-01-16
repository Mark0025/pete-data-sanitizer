from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class Thresholds(BaseModel):
    match_warn_pct: float = 95.0
    missing_seller_warn_count: int = 1


class BuildConfig(BaseModel):
    uploads_dir: str = "uploads"
    template: str = "uploads/templates/Properties Template (15).xlsx"
    export_prefix: str = "PETE.DM.FERNANDO.CLEAN"
    export_date_format: str = "%m.%d.%y"
    max_sellers: int = 5
    desktop_copy: bool = True
    desktop_subfolder_prefix: str = "fernando.dealmachine.clean"
    desktop_subfolder_date_format: str = "%m.%d.%y"


class ServeConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    reload: bool = True


class GeneratorUI(BaseModel):
    label: str = ""
    description: str = ""


class PetePropertiesImportDefaults(BaseModel):
    export_prefix: str = "PETE.DM.FERNANDO.CLEAN"
    export_date_format: str = "%m.%d.%y"
    max_sellers: int = 5
    debug_report: bool = False
    debug_sample_n: int = 25


class GeneratorsConfig(BaseModel):
    pete_properties_import: PetePropertiesImportDefaults = Field(default_factory=PetePropertiesImportDefaults)


class AppConfig(BaseModel):
    build: BuildConfig = Field(default_factory=BuildConfig)
    serve: ServeConfig = Field(default_factory=ServeConfig)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    generators: GeneratorsConfig = Field(default_factory=GeneratorsConfig)

    @classmethod
    def from_yaml_dict(cls, data: dict[str, Any]) -> "AppConfig":
        return cls.model_validate(data or {})


