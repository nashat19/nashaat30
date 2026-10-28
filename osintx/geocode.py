"""عكس الترميز الجغرافي عبر Nominatim مع تخزين مؤقت واحترام حدود المعدل."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, asdict
from typing import Any, Protocol

__all__ = ["Place", "GeocodeResult", "NominatimGeocoder"]

NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "osintx-geo/1.0 (+https://github.com/osintx)"

@dataclass
class Place:
    display_name: str
    country: str | None = None
    country_code: str | None = None
    state: str | None = None
    county: str | None = None
    city: str | None = None
    suburb: str | None = None
    postcode: str | None = None
    road: str | None = None
    house_number: str | None = None
    osm_type: str | None = None
    osm_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def short(self) -> str:
        parts = [self.house_number, self.road, self.suburb, self.city, self.state, self.country]
        return ", ".join(p for p in parts if p)

@dataclass
class GeocodeResult:
    lat: float
    lon: float
    place: Place | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "place": self.place.to_dict() if self.place else None,
            "error": self.error,
        }

class FetcherLike(Protocol):
    async def get_json(self, url: str, headers: dict[str, str] | None = ...) -> Any: ...

class NominatimGeocoder:
    """مُرمِّز جغرافي عكسي محدود المعدل (طلب واحد/ثانية افتراضياً)."""

    def __init__(
        self,
        fetcher: FetcherLike,
        *,
        min_interval: float = 1.1,
        cache: dict[str, GeocodeResult] | None = None,
        language: str = "ar,en",
    ) -> None:
        self._fetcher = fetcher
        self._min_interval = max(0.0, min_interval)
        self._cache: dict[str, GeocodeResult] = cache if cache is not None else {}
        self._language = language
        self._lock = asyncio.Lock()
        self._last = 0.0

    @staticmethod
    def _key(lat: float, lon: float) -> str:
        return f"{lat:.4f},{lon:.4f}"

    async def _throttle(self) -> None:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    async def reverse(self, lat: float, lon: float, zoom: int = 16) -> GeocodeResult:
        key = self._key(lat, lon)
        if key in self._cache:
            return self._cache[key]

        await self._throttle()
        url = (
            f"{NOMINATIM_REVERSE}?format=jsonv2&lat={lat:.6f}&lon={lon:.6f}"
            f"&zoom={zoom}&addressdetails=1&accept-language={self._language}"
        )
        try:
            payload = await self._fetcher.get_json(url, headers={"User-Agent": USER_AGENT})
        except Exception as exc:  # noqa: BLE001
            result = GeocodeResult(lat, lon, error=str(exc))
            self._cache[key] = result
            return result

        if not isinstance(payload, dict) or payload.get("error"):
            result = GeocodeResult(lat, lon, error=str(payload.get("error", "no-result")))
            self._cache[key] = result
            return result

        address = payload.get("address") or {}
        place = Place(
            display_name=payload.get("display_name", ""),
            country=address.get("country"),
            country_code=address.get("country_code"),
            state=address.get("state"),
            county=address.get("county"),
            city=address.get("city") or address.get("town") or address.get("village"),
            suburb=address.get("suburb") or address.get("neighbourhood"),
            postcode=address.get("postcode"),
            road=address.get("road"),
            house_number=address.get("house_number"),
            osm_type=payload.get("osm_type"),
            osm_id=payload.get("osm_id"),
        )
        result = GeocodeResult(lat, lon, place=place)
        self._cache[key] = result
        return result

    async def search(self, query: str, limit: int = 5) -> list[GeocodeResult]:
        await self._throttle()
        url = (
            f"{NOMINATIM_SEARCH}?format=jsonv2&q={query}&limit={limit}"
            f"&addressdetails=1&accept-language={self._language}"
        )
        try:
            payload = await self._fetcher.get_json(url, headers={"User-Agent": USER_AGENT})
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        results: list[GeocodeResult] = []
        for item in payload:
            try:
                results.append(GeocodeResult(float(item["lat"]), float(item["lon"])))
            except (KeyError, TypeError, ValueError):
                continue
        return results

    def dump_cache(self) -> str:
        return json.dumps({k: v.to_dict() for k, v in self._cache.items()}, ensure_ascii=False, indent=2)
