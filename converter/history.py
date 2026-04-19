# -*- coding: utf-8 -*-
"""Task history: circular buffer of up to 50 recent conversion records."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from PyQt5.QtCore import QSettings

from .constants import SettingsKey


@dataclass
class HistoryRecord:
    timestamp: str = ""
    task_kind: str = ""
    file_count: int = 0
    duration_s: float = 0.0
    success_count: int = 0
    fail_count: int = 0
    skip_count: int = 0
    target_format: str = ""
    preset_name: str = ""
    output_dir: str = ""

    def summary(self) -> str:
        parts = [self.timestamp[:16]]
        parts.append(f"{self.task_kind} → {self.target_format}")
        parts.append(f"{self.file_count} 文件")
        if self.success_count:
            parts.append(f"✓{self.success_count}")
        if self.fail_count:
            parts.append(f"✗{self.fail_count}")
        if self.skip_count:
            parts.append(f"⊘{self.skip_count}")
        elapsed = int(self.duration_s)
        if elapsed >= 60:
            m, s = divmod(elapsed, 60)
            parts.append(f"{m}m{s:02d}s")
        else:
            parts.append(f"{elapsed}s")
        return " · ".join(parts)


_MAX_RECORDS = 50


class TaskHistory:
    """Persists history to QSettings as a JSON array."""

    def __init__(self, settings: QSettings) -> None:
        self._settings = settings
        self._records: list[HistoryRecord] = []
        self._load()

    def _load(self) -> None:
        raw = self._settings.value(SettingsKey.TASK_HISTORY, "", type=str)
        if not raw:
            return
        try:
            items = json.loads(raw)
            self._records = [
                HistoryRecord(**{k: v for k, v in d.items() if k in HistoryRecord.__dataclass_fields__})
                for d in items
                if isinstance(d, dict)
            ]
        except (json.JSONDecodeError, TypeError):
            self._records = []

    def _save(self) -> None:
        data = [asdict(r) for r in self._records[-_MAX_RECORDS:]]
        self._settings.setValue(SettingsKey.TASK_HISTORY, json.dumps(data, ensure_ascii=False))

    def add(self, record: HistoryRecord) -> None:
        if not record.timestamp:
            record.timestamp = datetime.now().isoformat(timespec="seconds")
        self._records.append(record)
        if len(self._records) > _MAX_RECORDS:
            self._records = self._records[-_MAX_RECORDS:]
        self._save()

    @property
    def records(self) -> list[HistoryRecord]:
        return list(self._records)

    def clear(self) -> None:
        self._records.clear()
        self._save()
