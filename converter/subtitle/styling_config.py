# -*- coding: utf-8 -*-
"""Configurable subtitle burn style.

Replaces the hard-coded DEFAULT_BURN_STYLE with a user-editable dataclass
that serializes to/from JSON for QSettings persistence.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass
class BurnStyle:
    font_name: str = "Arial"
    primary_color: str = "&H00FFC0CB"     # pink, ASS &HAABBGGRR
    outline_color: str = "&H00000000"     # black
    border_style: int = 1
    outline_width: int = 2
    shadow: int = 0
    font_size: int = 24
    alignment: int = 2                    # bottom-center
    margin_v: int = 30

    def to_force_style(self) -> str:
        """Build the ``force_style`` value for ffmpeg ``subtitles=`` filter."""
        return (
            f"FontName={self.font_name},"
            f"PrimaryColour={self.primary_color},"
            f"OutlineColour={self.outline_color},"
            f"BorderStyle={self.border_style},"
            f"Outline={self.outline_width},"
            f"Shadow={self.shadow},"
            f"FontSize={self.font_size},"
            f"Alignment={self.alignment},"
            f"MarginV={self.margin_v}"
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> BurnStyle:
        try:
            data = json.loads(text)
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return cls()


DEFAULT_BURN_STYLE_OBJ = BurnStyle()
