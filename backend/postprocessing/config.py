from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSION = "2.0.0"


def rgb_value(value) -> tuple[int, int, int]:
    if isinstance(value, str):
        if len(value) != 7 or not value.startswith("#"):
            raise ValueError("RGB color must be #RRGGBB or three integers")
        value = [int(value[i:i + 2], 16) for i in (1, 3, 5)]
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError("RGB color must contain three channels")
    if any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in value):
        raise ValueError("RGB channels must be integers in [0, 255]")
    return tuple(value)


@dataclass
class PostprocessConfig:
    mode: str = "auto"
    background_rgb: tuple[int, int, int] | None = None
    background_delta: float = 10.0  # CIE Lab / Delta E 76, not OpenCV uint8 Lab
    color_delta: float = 5.0
    repair_geometry: bool = True
    clean_colors: bool = True
    defect_radius: int = 1  # pixels at 1024 on the short side
    max_hole_area: int = 4
    max_geometry_change_ratio: float = 0.025
    geometry_mode: str = "regularize"  # regularize, local (v1 geometry), or off
    boundary_tolerance_ratio: float = 0.24  # fraction of estimated local wall width
    regularization_max_change_ratio: float = 0.20
    remove_fragments: bool = True
    fragment_area_ratio: float = 0.025  # relative to typical foreground-component area
    regularize_color_boundaries: bool = True
    max_noise_region_area: int = 2
    max_prototypes: int = 48  # complexity guard; never a required color count
    max_pixels: int = 16_777_216
    palette_delta: float = 10.0
    palette_margin: float = 2.0
    colors: list[dict] = field(default_factory=list)

    def validate(self) -> "PostprocessConfig":
        if self.mode not in {"auto", "palette"}:
            raise ValueError("mode must be auto or palette")
        if self.geometry_mode not in {"regularize", "local", "off"}:
            raise ValueError("geometry_mode must be regularize, local or off")
        for name, maximum in (("boundary_tolerance_ratio", 0.5),
                              ("regularization_max_change_ratio", 0.4), ("fragment_area_ratio", 0.1)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError(f"{name} must be finite and in [0, {maximum}]")
        if type(self.remove_fragments) is not bool:
            raise ValueError("remove_fragments must be boolean")
        if type(self.regularize_color_boundaries) is not bool:
            raise ValueError("regularize_color_boundaries must be boolean")
        for name in ("background_delta", "color_delta", "palette_delta", "palette_margin"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 100:
                raise ValueError(f"{name} must be finite and in (0, 100]")
        for name, minimum, maximum in (("defect_radius", 0, 8), ("max_hole_area", 0, 1000),
                                       ("max_noise_region_area", 0, 16), ("max_prototypes", 2, 128),
                                       ("max_pixels", 1, 100_000_000)):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
        if not isinstance(self.max_geometry_change_ratio, (int, float)) or not math.isfinite(self.max_geometry_change_ratio) or not 0 <= self.max_geometry_change_ratio <= 0.2:
            raise ValueError("max_geometry_change_ratio must be in [0, 0.2]")
        if type(self.repair_geometry) is not bool or type(self.clean_colors) is not bool:
            raise ValueError("repair_geometry and clean_colors must be boolean")
        if self.background_rgb is not None:
            self.background_rgb = rgb_value(self.background_rgb)
        if not isinstance(self.colors, list) or len(self.colors) > 256:
            raise ValueError("colors must be a list with at most 256 entries")
        normalized = []
        seen = set()
        for i, entry in enumerate(self.colors):
            if not isinstance(entry, dict) or "rgb" not in entry:
                raise ValueError("Each palette entry needs rgb")
            rgb = rgb_value(entry["rgb"])
            if rgb in seen:
                raise ValueError("Duplicate palette RGB values are ambiguous")
            seen.add(rgb)
            height = entry.get("height_m")
            if height is not None and (isinstance(height, bool) or not isinstance(height, (int, float)) or not math.isfinite(height) or not 0 < height <= 2000):
                raise ValueError("height_m must be null or finite in (0, 2000]")
            normalized.append({"name": str(entry.get("name", f"C{i + 1}")), "rgb": list(rgb), "height_m": height})
        self.colors = normalized
        if self.mode == "palette" and not self.colors:
            raise ValueError("palette mode requires colors in a configuration file")
        return self

    def as_dict(self) -> dict:
        return asdict(self)


def load_config(path: str | Path | None = None, **overrides) -> PostprocessConfig:
    values = {}
    if path is not None:
        values = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(values, dict):
            raise ValueError("Configuration must be a JSON object")
    values.update({k: v for k, v in overrides.items() if v is not None})
    unknown = set(values) - set(PostprocessConfig.__dataclass_fields__)
    if unknown:
        raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
    return PostprocessConfig(**values).validate()
