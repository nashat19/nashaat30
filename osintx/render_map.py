"""توليد خريطة HTML مستقلة (Leaflet) من تقرير اجتماعي."""
from __future__ import annotations

import html
import json
from typing import Any

from .geo import Coordinate, format_dms, maps_links
from .social_engine import SocialReport

__all__ = ["render_map", "render_markdown"]

_TEMPLATE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>خريطة OSINT — {username}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  html,body{{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}
  #map{{height:100%}}
  .panel{{position:absolute;top:12px;right:12px;z-index:1000;background:#fff;
    border-radius:10px;padding:14px 16px;box-shadow:0 4px 18px rgba(0,0,0,.22);
    max-width:340px;font-size:13px;line-height:1.6}}
  .panel h1{{margin:0 0 8px;font-size:15px}}
  .badge{{display:inline-block;background:#eef2ff;color:#3730a3;border-radius:6px;
    padding:1px 7px;margin:2px 2px 2px 0;font-size:11px}}
  .conf{{font-weight:700;color:{conf_color}}}
  .pin{{border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 2px rgba(0,0,0,.35)}}
</style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <h1>الموقع المحتمل — {username}</h1>
  <div>الثقة: <span class="conf">{confidence}</span> · نصف القطر: {radius} كم</div>
  <div>{dms}</div>
  <div>{place}</div>
  <div>{badges}</div>
  <div style="margin-top:8px">{links}</div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const data = {geojson};
const map = L.map('map');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{maxZoom:19, attribution:'&copy; OpenStreetMap'}}).addTo(map);
const points = [];
L.geoJSON(data, {{
  pointToLayer: (f, latlng) => {{
    points.push(latlng);
    const c = f.properties.confidence || 0.5;
    const color = c >= 0.8 ? '#16a34a' : c >= 0.5 ? '#d97706' : '#dc2626';
    return L.circleMarker(latlng, {{
      radius: 7, color, weight: 2, fillColor: color, fillOpacity: .75, className: 'pin'
    }}).bindPopup(`<b>${{f.properties.source}}</b><br>ثقة: ${{c}}`);
  }}
}}).addTo(map);
if (points.length === 1) {{
  map.setView(points[0], 13);
}} else if (points.length > 1) {{
  map.fitBounds(L.latLngBounds(points).pad(0.25));
}} else {{
  map.setView([20, 0], 2);
}}
</script>
</body>
</html>
"""

def _conf_color(value: float) -> str:
    if value >= 0.8:
        return "#16a34a"
    if value >= 0.5:
        return "#d97706"
    return "#dc2626"

def render_map(report: SocialReport) -> str:
    """يبني صفحة HTML مستقلة تعرض كل الأدلة الجغرافية."""
    best = report.best
    if best:
        center = best.centroid
        confidence = f"{best.score():.2f}"
        radius = f"{best.radius_km:.1f}"
        dms = format_dms(center)
        key = f"{center.lat:.4f},{center.lon:.4f}"
        place_result = report.places.get(key)
        place = html.escape(place_result.place.short()) if place_result and place_result.place else "—"
        badges = "".join(f'<span class="badge">{html.escape(s)}</span>' for s in best.sources)
        links = " · ".join(
            f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{name}</a>'
            for name, url in maps_links(center).items()
        )
    else:
        confidence = "0.00"
        radius = "0"
        dms = "لا توجد إحداثيات"
        place = "—"
        badges = ""
        links = ""

    return _TEMPLATE.format(
        username=html.escape(report.username),
        geojson=json.dumps(report.to_geojson(), ensure_ascii=False),
        confidence=confidence,
        radius=radius,
        dms=html.escape(dms),
        place=place,
        badges=badges,
        links=links,
        conf_color=_conf_color(float(confidence)),
    )

def render_markdown(report: SocialReport) -> str:
    """ملخص Markdown قابل للنسخ."""
    lines = [f"# تقرير OSINT — `{report.username}`", ""]
    lines.append(f"- المدة: {report.duration:.2f} ثانية")
    lines.append(f"- الملفات: {len(report.profiles)}")
    lines.append(f"- الإحداثيات: {len(report.coordinates)}")
    lines.append("")

    if report.profiles:
        lines.append("## الحسابات")
        for profile in report.profiles:
            lines.append(f"- **{profile.platform}** — {profile.url}")
            if profile.location_text:
                lines.append(f"  - الموقع النصي: {profile.location_text}")
            for coord in profile.coordinates:
                lines.append(f"  - إحداثي ({coord.source}): {format_dms(coord)}")
        lines.append("")

    best = report.best
    if best:
        center = best.centroid
        lines.append("## الموقع الأرجح")
        lines.append(f"- الإحداثيات: `{center.lat:.6f},{center.lon:.6f}`")
        lines.append(f"- DMS: {format_dms(center)}")
        lines.append(f"- الثقة: {best.score():.2f} · نصف القطر: {best.radius_km:.1f} كم")
        lines.append(f"- المصادر: {', '.join(best.sources)}")
        for name, url in maps_links(center).items():
            lines.append(f"- [{name}]({url})")
        lines.append("")

    if report.errors:
        lines.append("## أخطاء")
        for platform, message in report.errors.items():
            lines.append(f"- `{platform}`: {message}")

    return "\n".join(lines)
