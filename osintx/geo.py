"""استخراج الإحداثيات وتطبيعها وتجميعها عنقودياً.

وحدة قياسية بالكامل: لا تحتاج أي اعتماد خارجي للمسار الأساسي.
التكاملات الاختيارية (timezonefinder) تُكتشف وقت التشغيل وتتدهور بلطف.
"""
from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Sequence

__all__ = [
    "Coordinate",
    "Cluster",
    "GeoExtraction",
    "EARTH_RADIUS_KM",
    "SOURCE_WEIGHTS",
    "extract_coordinates",
    "parse_exif_gps",
    "decode_plus_code",
    "haversine",
    "bearing",
    "cluster",
    "format_dms",
    "format_decimal",
    "geohash",
    "timezone_for",
    "maps_links",
    "to_geojson",
    "bounding_box",
]

EARTH_RADIUS_KM = 6371.0088
LAT_MIN, LAT_MAX = -90.0, 90.0
LON_MIN, LON_MAX = -180.0, 180.0

# أوزان الثقة بحسب مصدر الإحداثيات — EXIF هو الأقوى لأن الكاميرا تكتبه.
SOURCE_WEIGHTS: dict[str, float] = {
    "exif-gps": 1.00,
    "geo-uri": 0.95,
    "maps-bang": 0.90,
    "maps-at": 0.85,
    "maps-query": 0.80,
    "plus-code": 0.80,
    "dms": 0.80,
    "hemi-decimal": 0.75,
    "labeled": 0.70,
    "labeled-rev": 0.70,
    "decimal-pair": 0.60,
    "manual": 1.00,
}

GEOHASH_B32 = "0123456789bcdefghjkmnpqrstuvwxyz"

# ─────────────────────────── Open Location Code ───────────────────────────
OLC_ALPHABET = "23456789CFGHJMPQRVWX"
OLC_SEPARATOR = "+"
OLC_PADDING = "0"
OLC_PAIR_RESOLUTION = 20
OLC_GRID_ROWS = 5
OLC_GRID_COLUMNS = 4
OLC_MAX_DIGITS = 15

# ─────────────────────────── النموذج ───────────────────────────
@dataclass
class Coordinate:
    """إحداثي جغرافي واحد مع مصدره وثقته."""

    lat: float
    lon: float
    source: str = "manual"
    confidence: float = 0.5
    accuracy_m: float | None = None
    context: str | None = None

    def __post_init__(self) -> None:
        self.lat = float(self.lat)
        self.lon = float(self.lon)
        if self.source in SOURCE_WEIGHTS and self.confidence == 0.5:
            self.confidence = SOURCE_WEIGHTS[self.source]
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def valid(self) -> bool:
        return LAT_MIN <= self.lat <= LAT_MAX and LON_MIN <= self.lon <= LON_MAX

    def pair(self) -> tuple[float, float]:
        return (self.lat, self.lon)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Coordinate":
        return cls(
            lat=data["lat"],
            lon=data["lon"],
            source=data.get("source", "manual"),
            confidence=data.get("confidence", 0.5),
            accuracy_m=data.get("accuracy_m"),
            context=data.get("context"),
        )

@dataclass
class GeoExtraction:
    """نتيجة استخراج من نص واحد."""

    text: str
    coordinates: list[Coordinate] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.coordinates)

# ─────────────────────────── الأنماط ───────────────────────────
_DEC = r"-?\d{1,3}\.\d{1,}"
_DEC_STRICT = r"-?\d{1,3}\.\d{3,}"

GEO_URI_RE = re.compile(r"geo:(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)")
MAPS_BANG_RE = re.compile(r"!3d(-?\d{1,3}\.\d+)!4d(-?\d{1,3}\.\d+)")
MAPS_AT_RE = re.compile(r"@(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)")
MAPS_QUERY_RE = re.compile(r"[?&](?:q|ll|query|center)=(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)")
HEMI_DEC_RE = re.compile(
    r"(?<![\d.])(\d{1,3}\.\d{1,})\s*([NS])\s*[,;\s]*\s*(\d{1,3}\.\d{1,})\s*([EW])",
    re.IGNORECASE,
)
DMS_RE = re.compile(
    r"(?<![\d.])(\d{1,3})\s*[°d]\s*(\d{1,2})\s*['m]\s*(\d{1,2}(?:\.\d+)?)\s*[\"s]?\s*([NS])"
    r"[\s,;]*"
    r"(\d{1,3})\s*[°d]\s*(\d{1,2})\s*['m]\s*(\d{1,2}(?:\.\d+)?)\s*[\"s]?\s*([EW])",
    re.IGNORECASE,
)
LABELED_RE = re.compile(
    r"\b(?:lat|latitude)\s*[:=]?\s*(" + _DEC + r")\s*[,;\s]+"
    r"(?:lon|lng|long|longitude)\s*[:=]?\s*(" + _DEC + r")",
    re.IGNORECASE,
)
LABELED_REV_RE = re.compile(
    r"\b(?:lon|lng|long|longitude)\s*[:=]?\s*(" + _DEC + r")\s*[,;\s]+"
    r"(?:lat|latitude)\s*[:=]?\s*(" + _DEC + r")",
    re.IGNORECASE,
)
DEC_PAIR_RE = re.compile(
    r"(?<![\d.])(" + _DEC_STRICT + r")\s*[,;\s]\s*(" + _DEC_STRICT + r")(?![\d.])"
)
# رمز Plus: 4+ أحرف من الأبجدية، فاصل، ثم 2+ أحرف
PLUS_CODE_RE = re.compile(
    r"(?<![A-Z0-9])([23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,3})(?![A-Z0-9])",
    re.IGNORECASE,
)

def _dms_to_decimal(deg: str, minute: str, second: str, hemi: str) -> float:
    value = float(deg) + float(minute) / 60.0 + float(second) / 3600.0
    return -value if hemi.upper() in ("S", "W") else value

# ─────────────────────── فك ترميز Plus Code ───────────────────────
def decode_plus_code(code: str, reference: tuple[float, float] | None = None) -> Coordinate | None:
    """يفك ترميز Open Location Code إلى إحداثي.

    يدعم الرموز الكاملة والرموز المختصرة (مع نقطة مرجعية).
    """
    if not code:
        return None

    cleaned = code.strip().upper()
    if OLC_SEPARATOR not in cleaned:
        return None

    head, _, tail = cleaned.partition(OLC_SEPARATOR)
    if not tail:
        return None

    # رمز مختصر: يُكمَّل من المرجع أو من (0,0) عند غيابه
    if len(head) < 8:
        pad = 8 - len(head)
        if reference is not None:
            ref_lat, ref_lon = reference
            ref_code = _encode_plus_code(ref_lat, ref_lon, 8)
            head = ref_code[:pad] + head
        else:
            head = OLC_PADDING * pad + head

    full = head + tail
    if len(full) > OLC_MAX_DIGITS:
        full = full[:OLC_MAX_DIGITS]

    lat = -90.0
    lon = -180.0
    lat_res = 400.0
    lon_res = 400.0

    pairs = len(full) // 2
    for index in range(pairs):
        lat_res /= OLC_PAIR_RESOLUTION
        lon_res /= OLC_PAIR_RESOLUTION
        lat_char = OLC_ALPHABET.find(full[index * 2])
        lon_char = OLC_ALPHABET.find(full[index * 2 + 1])
        if lat_char < 0 or lon_char < 0:
            return None
        lat += lat_char * lat_res
        lon += lon_char * lon_res

    if len(full) % 2 == 1:
        lat_res /= OLC_GRID_ROWS
        lon_res /= OLC_GRID_COLUMNS
        last = OLC_ALPHABET.find(full[-1])
        if last < 0:
            return None
        lat += lat_res * (last // OLC_GRID_COLUMNS)
        lon += lon_res * (last % OLC_GRID_COLUMNS)

    # مركز الخلية
    lat += lat_res / 2.0
    lon += lon_res / 2.0

    coord = Coordinate(lat, lon, "plus-code")
    return coord if coord.valid() else None

def _encode_plus_code(lat: float, lon: float, length: int = 8) -> str:
    """ترميز مبسّط يُستخدم فقط لتكميل الرموز المختصرة."""
    lat = max(LAT_MIN, min(LAT_MAX, lat))
    lon = max(LON_MIN, min(LON_MAX, lon))
    lat_res = 400.0
    lon_res = 400.0
    out: list[str] = []
    lat -= -90.0
    lon -= -180.0
    for _ in range(length // 2):
        lat_res /= OLC_PAIR_RESOLUTION
        lon_res /= OLC_PAIR_RESOLUTION
        lat_idx = int(lat / lat_res)
        lon_idx = int(lon / lon_res)
        lat_idx = max(0, min(OLC_PAIR_RESOLUTION - 1, lat_idx))
        lon_idx = max(0, min(OLC_PAIR_RESOLUTION - 1, lon_idx))
        out.append(OLC_ALPHABET[lat_idx])
        out.append(OLC_ALPHABET[lon_idx])
        lat -= lat_idx * lat_res
        lon -= lon_idx * lon_res
    return "".join(out)

# ─────────────────────── استخراج من النصوص ───────────────────────
def extract_coordinates(text: str | None, context: str | None = None) -> list[Coordinate]:
    """يستخرج كل الإحداثيات الصالحة من نص حر، بلا تكرار."""
    if not text:
        return []

    found: list[Coordinate] = []

    def add(lat: float, lon: float, source: str) -> None:
        candidate = Coordinate(lat, lon, source, context=context)
        if candidate.valid():
            found.append(candidate)

    for match in GEO_URI_RE.finditer(text):
        add(float(match.group(1)), float(match.group(2)), "geo-uri")
    for match in MAPS_BANG_RE.finditer(text):
        add(float(match.group(1)), float(match.group(2)), "maps-bang")
    for match in MAPS_AT_RE.finditer(text):
        add(float(match.group(1)), float(match.group(2)), "maps-at")
    for match in MAPS_QUERY_RE.finditer(text):
        add(float(match.group(1)), float(match.group(2)), "maps-query")
    for match in HEMI_DEC_RE.finditer(text):
        lat = float(match.group(1)) * (-1 if match.group(2).upper() == "S" else 1)
        lon = float(match.group(3)) * (-1 if match.group(4).upper() == "W" else 1)
        add(lat, lon, "hemi-decimal")
    for match in DMS_RE.finditer(text):
        add(
            _dms_to_decimal(match.group(1), match.group(2), match.group(3), match.group(4)),
            _dms_to_decimal(match.group(5), match.group(6), match.group(7), match.group(8)),
            "dms",
        )
    for match in LABELED_RE.finditer(text):
        add(float(match.group(1)), float(match.group(2)), "labeled")
    for match in LABELED_REV_RE.finditer(text):
        add(float(match.group(2)), float(match.group(1)), "labeled-rev")
    for match in DEC_PAIR_RE.finditer(text):
        add(float(match.group(1)), float(match.group(2)), "decimal-pair")
    for match in PLUS_CODE_RE.finditer(text):
        decoded = decode_plus_code(match.group(1))
        if decoded:
            decoded.context = context
            found.append(decoded)

    seen: set[tuple[float, float]] = set()
    unique: list[Coordinate] = []
    for coord in found:
        key = (round(coord.lat, 5), round(coord.lon, 5))
        if key in seen:
            continue
        seen.add(key)
        unique.append(coord)
    return unique

# ─────────────────────────── EXIF ───────────────────────────
_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
_GPS_IFD_TAG = 0x8825

def _read_ifd(data: bytes, offset: int, endian: str, limit: int) -> dict[int, tuple[int, int, int]]:
    entries: dict[int, tuple[int, int, int]] = {}
    if offset + 2 > limit:
        return entries
    (count,) = struct.unpack_from(endian + "H", data, offset)
    pos = offset + 2
    for _ in range(count):
        if pos + 12 > limit:
            break
        tag, typ, cnt = struct.unpack_from(endian + "HHI", data, pos)
        entries[tag] = (typ, cnt, pos + 8)
        pos += 12
    return entries

def _read_values(data: bytes, endian: str, typ: int, cnt: int, value_off: int, limit: int) -> Any:
    size = _TYPE_SIZES.get(typ, 1) * cnt
    if size <= 4:
        raw = data[value_off : value_off + size]
    else:
        if value_off + 4 > limit:
            return []
        (offset,) = struct.unpack_from(endian + "I", data, value_off)
        raw = data[offset : offset + size]
    if typ == 5:
        return [struct.unpack_from(endian + "II", raw, i * 8) for i in range(len(raw) // 8)]
    if typ == 2:
        return raw.split(b"\x00")[0].decode("ascii", "ignore")
    return list(raw)

def _rational_triplet(values: Sequence[tuple[int, int]]) -> float | None:
    """يحوّل ثلاثية EXIF (درجات، دقائق، ثوانٍ) إلى عشرية.

    EXIF يخزّن كل مكوّن ككسر (بسط، مقام) — الجمع المباشر خطأ شائع.
    """
    if not values or len(values) < 3:
        return None
    try:
        deg = values[0][0] / values[0][1]
        minute = values[1][0] / values[1][1]
        second = values[2][0] / values[2][1]
    except (ZeroDivisionError, IndexError):
        return None
    return deg + minute / 60.0 + second / 3600.0

def parse_exif_gps(data: bytes | None) -> Coordinate | None:
    """يستخرج إحداثيات GPS من كتلة EXIF داخل JPEG/PNG/WebP."""
    if not data:
        return None

    marker = data.find(b"Exif\x00\x00")
    if marker >= 0:
        tiff = data[marker + 6 :]
    else:
        marker = data.find(b"eXIf")
        if marker < 0:
            return None
        tiff = data[marker + 4 :]

    if len(tiff) < 8:
        return None
    if tiff[:2] == b"II":
        endian = "<"
    elif tiff[:2] == b"MM":
        endian = ">"
    else:
        return None

    try:
        (magic,) = struct.unpack_from(endian + "H", tiff, 2)
        if magic != 42:
            return None
        (ifd0_offset,) = struct.unpack_from(endian + "I", tiff, 4)
    except struct.error:
        return None

    limit = len(tiff)
    ifd0 = _read_ifd(tiff, ifd0_offset, endian, limit)
    if _GPS_IFD_TAG not in ifd0:
        return None

    try:
        (gps_offset,) = struct.unpack_from(endian + "I", tiff, ifd0[_GPS_IFD_TAG][2])
    except struct.error:
        return None

    gps = _read_ifd(tiff, gps_offset, endian, limit)
    if not {1, 2, 3, 4} <= set(gps):
        return None

    lat_ref = _read_values(tiff, endian, *gps[1], limit)
    lat = _rational_triplet(_read_values(tiff, endian, *gps[2], limit))
    lon_ref = _read_values(tiff, endian, *gps[3], limit)
    lon = _rational_triplet(_read_values(tiff, endian, *gps[4], limit))
    if lat is None or lon is None:
        return None

    if str(lat_ref).upper().startswith("S"):
        lat = -lat
    if str(lon_ref).upper().startswith("W"):
        lon = -lon

    coord = Coordinate(lat, lon, "exif-gps")
    return coord if coord.valid() else None

# ─────────────────────────── المسافات ───────────────────────────
def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """المسافة بالكيلومترات على سطح كرة أرضية."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))

def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    """الاتجاه بالدرجات من a إلى b."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0

def bounding_box(points: Iterable[Coordinate]) -> tuple[float, float, float, float] | None:
    pts = list(points)
    if not pts:
        return None
    lats = [p.lat for p in pts]
    lons = [p.lon for p in pts]
    return (min(lats), min(lons), max(lats), max(lons))

# ─────────────────────────── التجميع ───────────────────────────
@dataclass
class Cluster:
    """عنقود إحداثيات متقاربة يمثّل موقعاً واحداً محتملاً."""

    points: list[Coordinate] = field(default_factory=list)

    def add(self, point: Coordinate) -> None:
        self.points.append(point)

    @property
    def centroid(self) -> Coordinate:
        n = len(self.points)
        return Coordinate(
            sum(p.lat for p in self.points) / n,
            sum(p.lon for p in self.points) / n,
            "manual",
            0.0,
        )

    @property
    def weight(self) -> float:
        return sum(p.confidence for p in self.points)

    @property
    def radius_km(self) -> float:
        center = self.centroid
        return max((haversine(center.pair(), p.pair()) for p in self.points), default=0.0)

    @property
    def sources(self) -> list[str]:
        return sorted({p.source for p in self.points})

    def score(self) -> float:
        """درجة ثقة مركّبة: وزن الأدلة + تماسك العنقود."""
        support = min(1.0, self.weight / 3.0)
        tightness = 1.0 / (1.0 + self.radius_km / 5.0)
        return round(0.65 * support + 0.35 * tightness, 4)

    def to_dict(self) -> dict[str, Any]:
        center = self.centroid
        return {
            "lat": round(center.lat, 6),
            "lon": round(center.lon, 6),
            "confidence": self.score(),
            "radius_km": round(self.radius_km, 3),
            "sources": self.sources,
            "points": [p.to_dict() for p in self.points],
        }

def cluster(points: Sequence[Coordinate], radius_km: float = 25.0) -> list[Cluster]:
    """تجميع جشع بترتيب الثقة التنازلي."""
    clusters: list[Cluster] = []
    for point in sorted(points, key=lambda p: -p.confidence):
        for existing in clusters:
            if haversine(existing.centroid.pair(), point.pair()) <= radius_km:
                existing.add(point)
                break
        else:
            fresh = Cluster()
            fresh.add(point)
            clusters.append(fresh)
    clusters.sort(key=lambda c: (-c.score(), -c.weight))
    return clusters

# ─────────────────────────── التنسيق ───────────────────────────
def format_dms(coord: Coordinate) -> str:
    def one(value: float, positive: str, negative: str) -> str:
        hemi = positive if value >= 0 else negative
        value = abs(value)
        deg = int(value)
        minute = int((value - deg) * 60)
        second = (value - deg - minute / 60.0) * 3600.0
        return f"{deg}°{minute:02d}'{second:05.2f}\"{hemi}"

    return f"{one(coord.lat, 'N', 'S')} {one(coord.lon, 'E', 'W')}"

def format_decimal(coord: Coordinate, precision: int = 6) -> str:
    return f"{coord.lat:.{precision}f},{coord.lon:.{precision}f}"

def geohash(lat: float, lon: float, precision: int = 9) -> str:
    """ترميز geohash قياسي."""
    lat_range = [-90.0, 90.0]
    lon_range = [-180.0, 180.0]
    bits = [16, 8, 4, 2, 1]
    bit = 0
    ch = 0
    even = True
    out: list[str] = []
    while len(out) < precision:
        if even:
            mid = (lon_range[0] + lon_range[1]) / 2
            if lon > mid:
                ch |= bits[bit]
                lon_range[0] = mid
            else:
                lon_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat > mid:
                ch |= bits[bit]
                lat_range[0] = mid
            else:
                lat_range[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out.append(GEOHASH_B32[ch])
            bit = 0
            ch = 0
    return "".join(out)

def timezone_for(coord: Coordinate) -> str:
    try:
        from timezonefinder import TimezoneFinder  # type: ignore

        found = TimezoneFinder().timezone_at(lat=coord.lat, lng=coord.lon)
        if found:
            return found
    except Exception:
        pass
    offset = round(coord.lon / 15.0)
    sign = "+" if offset <= 0 else "-"
    return f"Etc/GMT{sign}{abs(offset)}"

def maps_links(coord: Coordinate) -> dict[str, str]:
    query = format_decimal(coord)
    return {
        "google": f"https://www.google.com/maps?q={query}",
        "osm": (
            f"https://www.openstreetmap.org/?mlat={coord.lat:.6f}"
            f"&mlon={coord.lon:.6f}#map=16/{coord.lat:.6f}/{coord.lon:.6f}"
        ),
        "apple": f"https://maps.apple.com/?ll={query}",
        "geo": f"geo:{query}",
    }

def to_geojson(points: Iterable[Coordinate]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [p.lon, p.lat]},
                "properties": {
                    "source": p.source,
                    "confidence": p.confidence,
                    "context": p.context,
                },
            }
            for p in points
        ],
    }
