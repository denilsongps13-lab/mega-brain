"""Tests for preflight -- manifest bootstrap + thread-safe updater.
Uses temporary manifests so tests never touch repo state.
"""
import json
from pathlib import Path

from engine.intelligence.pipeline.preflight import (
    ManifestUpdater,
    PreFlightBootstrap,
)


def test_manifest_updater_creates_file_on_completed(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    updater = ManifestUpdater(manifest)
    updater.mark_completed("slug/notes.md")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["slug/notes.md"] == "completed"


def test_manifest_updater_mark_failed(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    updater = ManifestUpdater(manifest)
    updater.mark_failed("slug/bad.md", "boom")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["slug/bad.md"] == "failed: boom"


def test_manifest_updater_preserves_entries(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    updater = ManifestUpdater(manifest)
    updater.mark_completed("slug/a.md")
    updater.mark_completed("slug/b.md")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["slug/a.md"] == "completed"
    assert data["slug/b.md"] == "completed"


def test_preflight_bootstrap_creates_manifest(tmp_path: Path):
    files = [tmp_path / f for f in ("a.md", "b.md")]
    manifest = tmp_path / "mce" / "PROCESSED-MANIFEST.json"
    bootstrap = PreFlightBootstrap(
        manifest_path=manifest,
        mce_base=tmp_path / "mce",
        ingestion_registry_path=tmp_path / "ingestion-registry.json",
    )
    created = bootstrap.create_manifest(files)
    assert created == manifest
    assert manifest.exists()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["total_files"] == 2
    assert data[f"{tmp_path.name}/a.md"] == "pending"