# -*- coding: utf-8 -*-
"""Tests for converter.presets: TaskPreset serialization, PresetStore CRUD."""

import json
import os
import tempfile

import pytest

from converter.presets import (
    BUILTIN_PRESETS,
    CURRENT_SCHEMA_VERSION,
    PresetStore,
    TaskPreset,
)


@pytest.fixture
def store(tmp_path):
    from PyQt5.QtCore import QSettings
    ini = str(tmp_path / "test.ini")
    settings = QSettings(ini, QSettings.IniFormat)
    return PresetStore(settings)


class TestTaskPreset:
    def test_roundtrip_json(self):
        p = TaskPreset(name="test", tab="video", target_format="mp4", quality="high")
        text = p.to_json()
        loaded = TaskPreset.from_json(text)
        assert loaded.name == "test"
        assert loaded.quality == "high"

    def test_from_invalid_json(self):
        p = TaskPreset.from_json("not json")
        assert p.name == ""

    def test_from_partial_json(self):
        p = TaskPreset.from_json('{"name": "partial"}')
        assert p.name == "partial"
        assert p.quality == "balanced"


class TestPresetStore:
    def test_save_and_load(self, store):
        p = TaskPreset(name="my_preset", tab="audio", target_format="mp3")
        store.save(p)
        loaded = store.load("my_preset")
        assert loaded is not None
        assert loaded.target_format == "mp3"

    def test_list_names(self, store):
        store.save(TaskPreset(name="a", tab="video"))
        store.save(TaskPreset(name="b", tab="video"))
        store.save(TaskPreset(name="c", tab="audio"))
        names = store.list_names("video")
        assert "a" in names
        assert "b" in names
        assert "c" not in names

    def test_delete(self, store):
        store.save(TaskPreset(name="del_me", tab="video"))
        store.delete("del_me")
        assert store.load("del_me") is None

    def test_rename(self, store):
        store.save(TaskPreset(name="old", tab="video", target_format="mp4"))
        assert store.rename("old", "new")
        assert store.load("old") is None
        loaded = store.load("new")
        assert loaded is not None and loaded.target_format == "mp4"

    def test_export_import(self, store):
        store.save(TaskPreset(name="exp1", tab="video", target_format="mp4"))
        store.save(TaskPreset(name="exp2", tab="video", target_format="mkv"))
        exported = store.export_all("video")
        data = json.loads(exported)
        assert len(data) == 2

        from PyQt5.QtCore import QSettings
        ini2 = str(store._settings.fileName()) + ".import.ini"
        s2 = QSettings(ini2, QSettings.IniFormat)
        store2 = PresetStore(s2)
        count = store2.import_json(exported)
        assert count == 2
        assert store2.load("exp1") is not None

    def test_ensure_builtins(self, store):
        store.ensure_builtins()
        for bp in BUILTIN_PRESETS:
            assert store.load(bp.name) is not None


class TestSchemaVersioning:
    def test_new_preset_has_current_version(self):
        p = TaskPreset(name="x")
        data = json.loads(p.to_json())
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_legacy_record_without_version_loads(self):
        """A v0 record (no schema_version key) should migrate silently."""
        legacy = json.dumps({"name": "legacy", "tab": "audio", "target_format": "mp3"})
        p = TaskPreset.from_json(legacy)
        assert p.name == "legacy"
        assert p.schema_version == CURRENT_SCHEMA_VERSION

    def test_unknown_future_version_still_loads_known_fields(self):
        """A record from a newer app version shouldn't crash us."""
        future = json.dumps({
            "name": "future",
            "tab": "video",
            "schema_version": 99,
            "some_new_field": "ignored",
        })
        p = TaskPreset.from_json(future)
        assert p.name == "future"
        assert p.tab == "video"

    def test_export_import_roundtrip_preserves_data(self, store):
        store.save(TaskPreset(name="rt", tab="video", target_format="mkv"))
        exported = store.export_all("video")
        assert "schema_version" in exported

        from PyQt5.QtCore import QSettings
        ini2 = str(store._settings.fileName()) + ".rt.ini"
        s2 = QSettings(ini2, QSettings.IniFormat)
        store2 = PresetStore(s2)
        count = store2.import_json(exported)
        assert count == 1
        assert store2.load("rt").target_format == "mkv"

    def test_import_legacy_list_format(self, store):
        """Older exports were a bare JSON array; import must still accept them."""
        legacy = json.dumps([
            {"name": "old1", "tab": "audio", "target_format": "mp3"},
            {"name": "old2", "tab": "video", "target_format": "mp4"},
        ])
        count = store.import_json(legacy)
        assert count == 2
        assert store.load("old1") is not None
        assert store.load("old2") is not None
