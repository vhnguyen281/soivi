"""Smoke tests: the scaffold imports and is wired up correctly. Offline only."""

import importlib

import pytest

PACKAGES = [
    "core",
    "core.config",
    "core.db",
    "core.enums",
    "core.models",
    "core.versioning",
    "pipeline.adapters",
    "pipeline.fetch",
    "pipeline.extract",
    "pipeline.validate",
    "pipeline.diff",
    "review_app",
    "api",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name: str) -> None:
    importlib.import_module(name)


def test_crawler_delay_cannot_go_below_five_seconds() -> None:
    from pydantic import ValidationError

    from core.config import Settings

    with pytest.raises(ValidationError):
        Settings(crawler_min_delay_seconds=1.0)


def test_metadata_has_naming_convention() -> None:
    from core.db import Base

    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"
