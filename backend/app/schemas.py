from __future__ import annotations

from pydantic import BaseModel, Field


class SelectionPoint(BaseModel):
    lng: float
    lat: float
    order: int


class SelectionBBox(BaseModel):
    west: float
    south: float
    east: float
    north: float


class SelectionRange(BaseModel):
    points: list[SelectionPoint] = Field(default_factory=list)
    bbox: SelectionBBox
    closed: bool = True


class ChatRequest(BaseModel):
    message: str
    selection_range: SelectionRange | None = None


class ResultUpdateRequest(BaseModel):
    title: str | None = None
    notes: str | None = None


class AnalysisRequest(BaseModel):
    season_profile: str = "spring"
    sun_altitude_deg: float | None = None
    primary_wind_direction: str = "west"
    wind_directions: list[str] | None = None
