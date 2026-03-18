"""Shared fixtures for property-pipeline tests."""
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixtures_dir() -> Path:
    """Return the path to the tests/fixtures directory."""
    return FIXTURES_DIR
