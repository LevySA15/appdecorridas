"""Corpos de pedido que mais de uma rota usa."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.geo import GeoPoint


class PlaceIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    text: str = Field(default="", max_length=200)

    @property
    def point(self) -> GeoPoint:
        return GeoPoint(self.lat, self.lng)


class StarsIn(BaseModel):
    stars: int = Field(ge=1, le=5)
