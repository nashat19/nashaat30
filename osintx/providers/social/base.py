"""البنية الأساسية لمزوّدي OSINT الاجتماعي: نموذج الملف، الجالب، الحصاد."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, asdict
from html.parser import HTMLParser
from typing import Any, Mapping

from ...geo import Coordinate, extract_coordinates, parse_exif_gps

__all__ = [
    "SocialProfile",
    "Provider",
    "ProviderError",
    "ProfileNotFound",
    "Fetcher",
    "TokenBucket",
    "MetaParser",
    "parse_meta",
    "DEFAULT_UA",
]

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

class ProviderError(RuntimeError):
    """فشل عام في المزوّد."""

class ProfileNotFound(ProviderError):
    """الحساب غير موجود على المنصة."""

# ─────────────────────────── الجالب ───────────────────────────
class TokenBucket:
    """محدد معدل بسيط بمقبس غير متزامن."""

    def __init__(self, rate: float, burst: float | None = None) -> None:
        self.rate = max(rate, 0.01)
        self.burst = burst if burst is not None else max(1.0, rate)
        self._tokens = self.burst
        self._stamp = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, amount: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.burst, self._tokens + (now - self._stamp) * self.rate)
                self._stamp = now
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
                await asyncio.sleep((amount - self._tokens) / self.rate)

def _pick_backend() -> tuple[str, Any]:
    try:
        import httpx  # type: ignore

        return "httpx", httpx
    except ImportError:
        pass
    try:
        import aiohttp  # type: ignore

        return "aiohttp", aiohttp
    except ImportError:
        pass
    return "urllib", None

class Fetcher:
    """جالب HTTP غير متزامن مع حد معدل وحد أقصى للحجم."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        rate: float = 3.0,
        user_agent: str = DEFAULT_UA,
        proxy: str | None = None,
        max_bytes: int = 4_000_000,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.proxy = proxy
        self.max_bytes = max_bytes
        self.bucket = TokenBucket(rate)
        self._backend, self._module = _pick_backend()
        self._client: Any = None

    async def __aenter__(self) -> "Fetcher":
        if self._backend == "httpx":
            self._client = self._module.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                proxy=self.proxy,
                headers={"User-Agent": self.user_agent},
            )
        elif self._backend == "aiohttp":
            self._client = self._module.ClientSession(
                timeout=self._module.ClientTimeout(total=self.timeout),
                headers={"User-Agent": self.user_agent},
            )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _headers(self, extra: Mapping[str, str] | None) -> dict[str, str]:
        headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if extra:
            headers.update(extra)
        return headers

    async def get_bytes(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        *,
        max_bytes: int | None = None,
    ) -> bytes:
        await self.bucket.acquire()
        limit = max_bytes or self.max_bytes
        hdrs = self._headers(headers)

        if self._backend == "httpx":
            response = await self._client.get(url, headers=hdrs)
            if response.status_code == 404:
                raise ProfileNotFound(url)
            response.raise_for_status()
            return response.content[:limit]

        if self._backend == "aiohttp":
            async with self._client.get(url, headers=hdrs) as response:
                if response.status == 404:
                    raise ProfileNotFound(url)
                response.raise_for_status()
                return (await response.content.read(limit))[:limit]

        return await asyncio.to_thread(self._urllib_bytes, url, hdrs, limit)

    def _urllib_bytes(self, url: str, headers: dict[str, str], limit: int) -> bytes:
        import urllib.error
        import urllib.request

        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read(limit)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ProfileNotFound(url) from exc
            raise ProviderError(f"HTTP {exc.code} for {url}") from exc

    async def get_text(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        *,
        max_bytes: int | None = None,
    ) -> str:
        blob = await self.get_bytes(url, headers, max_bytes=max_bytes)
        return blob.decode("utf-8", "replace")

    async def get_json(
        self,
        url: str,
        headers: Mapping[str, str] | None = None,
        *,
        max_bytes: int | None = None,
    ) -> Any:
        import json

        text = await self.get_text(url, headers, max_bytes=max_bytes)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"JSON غير صالح من {url}: {exc}") from exc

# ─────────────────────────── تحليل HTML ───────────────────────────
class MetaParser(HTMLParser):
    """يجمع وسوم meta و ld+json وعنوان الصفحة."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title: str | None = None
        self.json_blobs: list[str] = []
        self._in_title = False
        self._in_json = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        mapping = {k: v for k, v in attrs if v is not None}
        if tag == "meta":
            key = mapping.get("property") or mapping.get("name")
            if key and "content" in mapping:
                self.meta.setdefault(key.lower(), mapping["content"])
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and mapping.get("type") == "application/ld+json":
            self._in_json = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            self._in_json = False

    def handle_data(self, data: str) -> None:
        if self._in_title and self.title is None:
            self.title = data.strip()
        elif self._in_json:
            self.json_blobs.append(data)

def parse_meta(html: str) -> MetaParser:
    parser = MetaParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        pass
    return parser

# ─────────────────────────── نموذج الملف ───────────────────────────
@dataclass
class SocialProfile:
    """ملف حساب اجتماعي موحّد مع الإحداثيات المستخرجة."""

    platform: str
    username: str
    url: str
    display_name: str | None = None
    bio: str | None = None
    location_text: str | None = None
    website: str | None = None
    avatar_url: str | None = None
    followers: int | None = None
    following: int | None = None
    posts: int | None = None
    verified: bool = False
    created_at: str | None = None
    coordinates: list[Coordinate] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_text_coordinates(self) -> None:
        for text in (self.bio, self.location_text, self.website, self.display_name):
            if not text:
                continue
            for coord in extract_coordinates(text, context=f"{self.platform}:{self.username}"):
                coord.source = f"{self.platform}/{coord.source}"
                self.coordinates.append(coord)

    async def harvest_avatar(self, fetcher: Fetcher) -> None:
        if not self.avatar_url:
            return
        try:
            blob = await fetcher.get_bytes(self.avatar_url, max_bytes=2_000_000)
        except Exception as exc:  # noqa: BLE001
            self.errors.append(f"avatar-fetch: {exc}")
            return
        coord = parse_exif_gps(blob)
        if coord:
            coord.source = f"{self.platform}/exif-gps"
            coord.context = self.avatar_url
            self.coordinates.append(coord)

    async def harvest(self, fetcher: Fetcher) -> None:
        self.add_text_coordinates()
        await self.harvest_avatar(fetcher)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["coordinates"] = [c.to_dict() for c in self.coordinates]
        return data

# ─────────────────────────── المزوّد ───────────────────────────
class Provider:
    """صنف أساسي لمزوّدي المنصات الاجتماعية."""

    name: str = "base"
    homepage: str = ""
    requires_instance: bool = False
    default_instance: str | None = None
    enabled: bool = True

    async def fetch(
        self,
        fetcher: Fetcher,
        username: str,
        *,
        instance: str | None = None,
    ) -> SocialProfile:
        raise NotImplementedError

    def profile_url(self, username: str, instance: str | None = None) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<Provider {self.name}>"
