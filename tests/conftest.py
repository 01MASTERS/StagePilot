"""Pytest configuration and shared fixtures for StagePilot tests."""

import os
import sys
from pathlib import Path
import pytest

# Ensure 'src' is in sys.path
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from stagepilot.config import PathConfig, AppConfig
from stagepilot.ingest.catalogue import CatalogueStore
from stagepilot.ingest.profiles import ProfileStore
from stagepilot.ingest.arms import ArmStore


@pytest.fixture(scope="session")
def pack_dir() -> Path:
    """Return path to the one_user_one_agent_pack directory."""
    path = Path(__file__).resolve().parent.parent / "docs" / "one_user_one_agent_pack"
    assert path.exists(), f"Pack directory does not exist: {path}"
    return path


@pytest.fixture(scope="session")
def path_config(pack_dir: Path) -> PathConfig:
    """Return configured PathConfig pointing to real data pack."""
    return PathConfig(pack_dir=pack_dir)


@pytest.fixture(scope="session")
def app_config(path_config: PathConfig) -> AppConfig:
    """Return root AppConfig."""
    return AppConfig(paths=path_config)


@pytest.fixture(scope="session")
def catalogue_store(path_config: PathConfig) -> CatalogueStore:
    """Loaded CatalogueStore fixture."""
    return CatalogueStore.load(path_config.catalogue_path, path_config.episodes_path)


@pytest.fixture(scope="session")
def profile_store(path_config: PathConfig) -> ProfileStore:
    """Loaded ProfileStore fixture."""
    return ProfileStore.load(path_config.profiles_path)


@pytest.fixture(scope="session")
def arms_store(path_config: PathConfig) -> ArmStore:
    """Loaded ArmStore fixture."""
    return ArmStore.load(path_config.replay_arms_path)
