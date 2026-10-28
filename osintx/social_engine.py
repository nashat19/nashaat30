"""محرك OSINT اجتماعي: تشغيل المزوّدين، تجميع الموقع، بناء التقرير."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .geo import (
    Cluster,
    Coordinate,
    bounding_box,
    cluster,
    format_dms,
    geohash,
    maps_links,
    timezone_for,
    to_geojson,
)
from .geocode import GeocodeResult, NominatimGeocoder
from .providers.social.base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile
from .providers.social.registry import resolve_providers

__all__ = ["SocialReport", "SocialEngine", "EngineOptions"]

@dataclass
class EngineOptions:
    concurrency: int = 6
    timeout: float = 20.0
    rate: float = 3.0
    proxy: str | None = None
    cluster_radius_km: float = 25.0
    geocode: bool = True
    geocode_interval: float = 1.1
    max_avatar_bytes: int = 2_000_000

@dataclass
class SocialReport:
    username: str
    started_at: float
    finished_at: float | None = None
    profiles: list[SocialProfile] = field(default_factory=list)
    clusters: list[Cluster] = field(default_factory=list)
    places: dict[str, GeocodeResult] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    options: EngineOptions = field(default_factory=EngineOptions)

    @property
    def duration(self) -> float:
        return (self.finished_at or time.time()) - self.started_at

    @property
    def coordinates(self) -> list[Coordinate]:
        return [c for p in self.profiles for c in p.coordinates]

    @property
    def best(self) -> Cluster | None:
        return self.clusters[0] if self.clusters else None

    def summary(self) -> dict[str, Any]:
        best = self.best
        return {
            "username": self.username,
            "profiles_found": len(self.profiles),
            "platforms": sorted({p.platform for p in self.profiles}),
            "coordinates": len(self.coordinates),
            "clusters": len(self.clusters),
            "best_location": best.to_dict() if best else None,
            "errors": self.errors,
            "duration_s": round(self.duration, 2),
        }

    def _best_payload(self, best: Cluster) -> dict[str, Any]:
        center = best.centroid
        key = f"{center.lat:.4f},{center.lon:.4f}"
        place = self.places.get(key)
        return {
            "lat": round(center.lat, 6),
            "lon": round(center.lon, 6),
            "dms": format_dms(center),
            "geohash": geohash(center.lat, center.lon),
            "timezone": timezone_for(center),
            "confidence": best.score(),
            "radius_km": round(best.radius_km, 3),
            "sources": best.sources,
            "links": maps_links(center),
            "place": place.place.to_dict() if place and place.place else None,
        }

    def to_dict(self) -> dict[str, Any]:
        best = self.best
        return {
            "username": self.username,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_s": round(self.duration, 2),
            "summary": self.summary(),
            "profiles": [p.to_dict() for p in self.profiles],
            "clusters": [c.to_dict() for c in self.clusters],
            "places": {k: v.to_dict() for k, v in self.places.items()},
            "best_location": self._best_payload(best) if best else None,
            "errors": self.errors,
        }

    def to_geojson(self) -> dict[str, Any]:
        return to_geojson(self.coordinates)

    def bbox(self) -> tuple[float, float, float, float] | None:
        return bounding_box(self.coordinates)

class SocialEngine:
    """ينسّق تشغيل المزوّدين ويجمع الأدلة الجغرافية."""

    def __init__(
        self,
        providers: Sequence[Provider] | None = None,
        options: EngineOptions | None = None,
    ) -> None:
        self.options = options or EngineOptions()
        self.providers = list(providers) if providers is not None else resolve_providers(None)

    async def investigate(
        self,
        username: str,
        *,
        platforms: Iterable[str] | None = None,
        instances: dict[str, str] | None = None,
    ) -> SocialReport:
        username = username.strip().lstrip("@")
        if not username:
            raise ValueError("اسم المستخدم مطلوب")

        selected = resolve_providers(platforms) if platforms else self.providers
        report = SocialReport(username=username, started_at=time.time(), options=self.options)
        semaphore = asyncio.Semaphore(self.options.concurrency)

        async with Fetcher(
            timeout=self.options.timeout,
            rate=self.options.rate,
            proxy=self.options.proxy,
            max_bytes=self.options.max_avatar_bytes,
        ) as fetcher:
            async def run(provider: Provider) -> None:
                async with semaphore:
                    instance = (instances or {}).get(provider.name)
                    try:
                        profile = await provider.fetch(fetcher, username, instance=instance)
                    except ProfileNotFound:
                        return
                    except ProviderError as exc:
                        report.errors[provider.name] = str(exc)
                        return
                    except Exception as exc:  # noqa: BLE001
                        report.errors[provider.name] = f"{type(exc).__name__}: {exc}"
                        return
                    report.profiles.append(profile)

            await asyncio.gather(*(run(p) for p in selected))

            report.profiles.sort(key=lambda p: (-len(p.coordinates), p.platform))
            report.clusters = cluster(report.coordinates, self.options.cluster_radius_km)

            if self.options.geocode and report.clusters:
                geocoder = NominatimGeocoder(fetcher, min_interval=self.options.geocode_interval)
                for item in report.clusters[:5]:
                    center = item.centroid
                    key = f"{center.lat:.4f},{center.lon:.4f}"
                    report.places[key] = await geocoder.reverse(center.lat, center.lon)

        report.finished_at = time.time()
        return report
