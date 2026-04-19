# -*- coding: utf-8 -*-
"""Named task presets stored per-tab in QSettings.

Each preset captures the full set of parameters for a tab so the user can
switch between "YouTube upload" / "podcast" / "archival" with one click.

Schema versioning
-----------------
Every preset record carries a ``schema_version``. When we add or rename a
field we bump :data:`CURRENT_SCHEMA_VERSION` and write a migrator in
``_MIGRATIONS``. Old configs round-trip through the migration chain, so the
user never sees a crash from a stale disk layout.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Callable, Optional

from PyQt5.QtCore import QSettings

from .fs import ConflictPolicy
from .subtitle.styling_config import BurnStyle


CURRENT_SCHEMA_VERSION: int = 1


@dataclass
class TaskPreset:
    name: str = ""
    tab: str = ""  # "audio" / "video" / "subtitle" / "burn"
    target_format: str = ""
    quality: str = "balanced"
    hw_accel: bool = False
    output_dir: str = ""
    filename_template: str = "{base}"
    conflict_policy: str = "ask"
    mirror_subdirs: bool = False
    continue_on_failure: bool = True
    trim_start: Optional[float] = None
    trim_end: Optional[float] = None
    scale_preset: str = ""
    volume_normalize: bool = False
    two_pass: bool = False
    burn_mode: str = "硬编码"
    burn_output_format: str = "mp4"
    burn_style_json: str = ""
    schema_version: int = CURRENT_SCHEMA_VERSION

    def to_json(self) -> str:
        data = asdict(self)
        data["schema_version"] = CURRENT_SCHEMA_VERSION
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> TaskPreset:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        data = _migrate(data)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---- Migration chain ---------------------------------------------------------
#
# Each migrator takes a dict read from disk and returns one shaped like the
# *next* schema version. The chain runs from the record's version up to
# ``CURRENT_SCHEMA_VERSION``. Add entries here; never edit old migrators.

_MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    # 0 -> 1: bootstrap. v0 records had no schema_version; treat any record
    # missing the key as v0 and normalise field names to the v1 layout.
    0: lambda d: {**d, "schema_version": 1},
}


def _migrate(raw: dict) -> dict:
    """Walk *raw* through successive migrators up to the current version."""
    version = int(raw.get("schema_version", 0))
    while version < CURRENT_SCHEMA_VERSION:
        migrator = _MIGRATIONS.get(version)
        if migrator is None:
            break
        raw = migrator(raw)
        version = int(raw.get("schema_version", version + 1))
    raw["schema_version"] = CURRENT_SCHEMA_VERSION
    return raw


# ---- Built-in factory presets ------------------------------------------------

BUILTIN_PRESETS: list[TaskPreset] = [
    TaskPreset(
        name="YouTube 投稿",
        tab="video", target_format="mp4",
        quality="high", hw_accel=True,
        filename_template="{base}_youtube",
        scale_preset="1080p",
    ),
    TaskPreset(
        name="播客压片",
        tab="audio", target_format="mp3",
        quality="balanced",
        filename_template="{base}",
        volume_normalize=True,
    ),
    TaskPreset(
        name="iOS 兼容",
        tab="video", target_format="mp4",
        quality="balanced", hw_accel=True,
        scale_preset="720p",
    ),
    TaskPreset(
        name="存档无损",
        tab="audio", target_format="flac",
        quality="high",
        filename_template="{base}_{date}",
    ),
    TaskPreset(
        name="字幕内嵌 · 小体积",
        tab="burn", target_format="mp4",
        quality="fast", hw_accel=True,
        burn_mode="硬编码",
        scale_preset="720p",
    ),
]


# ---- Preset store (QSettings-backed) -----------------------------------------

_SETTINGS_GROUP = "presets"


class PresetStore:
    """Read/write named presets in a QSettings instance."""

    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def list_names(self, tab: str) -> list[str]:
        """Return sorted preset names for a given tab."""
        self._settings.beginGroup(_SETTINGS_GROUP)
        keys = self._settings.childKeys()
        self._settings.endGroup()
        result: list[str] = []
        for key in keys:
            preset = self._load_raw(key)
            if preset and preset.tab == tab:
                result.append(preset.name)
        return sorted(result)

    def load(self, name: str) -> TaskPreset | None:
        return self._load_raw(_key(name))

    def save(self, preset: TaskPreset) -> None:
        preset.schema_version = CURRENT_SCHEMA_VERSION
        self._settings.beginGroup(_SETTINGS_GROUP)
        self._settings.setValue(_key(preset.name), preset.to_json())
        self._settings.endGroup()
        self._settings.sync()

    def delete(self, name: str) -> None:
        self._settings.beginGroup(_SETTINGS_GROUP)
        self._settings.remove(_key(name))
        self._settings.endGroup()
        self._settings.sync()

    def rename(self, old_name: str, new_name: str) -> bool:
        preset = self.load(old_name)
        if preset is None:
            return False
        self.delete(old_name)
        preset.name = new_name
        self.save(preset)
        return True

    def export_all(self, tab: str) -> str:
        """Export all presets for a tab as a JSON array."""
        names = self.list_names(tab)
        presets = [self.load(n) for n in names]
        return json.dumps(
            {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "presets": [asdict(p) for p in presets if p is not None],
            },
            ensure_ascii=False, indent=2,
        )

    def import_json(self, text: str) -> int:
        """Import presets from an export blob, return count imported."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return 0

        # Accept either new format {"schema_version", "presets": [...]}
        # or the legacy bare list.
        if isinstance(data, dict):
            records = data.get("presets", [])
        elif isinstance(data, list):
            records = data
        else:
            records = [data]

        count = 0
        valid_fields = {f.name for f in fields(TaskPreset)}
        for item in records:
            if not isinstance(item, dict):
                continue
            try:
                migrated = _migrate(dict(item))
                preset = TaskPreset(**{k: v for k, v in migrated.items() if k in valid_fields})
                if preset.name:
                    self.save(preset)
                    count += 1
            except (TypeError, KeyError):
                continue
        return count

    def ensure_builtins(self) -> None:
        """Write built-in presets if they don't already exist."""
        for preset in BUILTIN_PRESETS:
            if self.load(preset.name) is None:
                self.save(preset)

    def _load_raw(self, key: str) -> TaskPreset | None:
        self._settings.beginGroup(_SETTINGS_GROUP)
        raw = self._settings.value(key, "", type=str)
        self._settings.endGroup()
        if not raw:
            return None
        return TaskPreset.from_json(raw)


def _key(name: str) -> str:
    return name.replace("/", "_").replace("\\", "_")
