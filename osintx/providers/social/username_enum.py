"""تعداد وجود اسم المستخدم عبر منصات متعددة (بصمة رقمية)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .base import Fetcher, Provider, ProviderError, SocialProfile

__all__ = ["UsernameEnumProvider", "TARGETS"]

TARGETS: dict[str, str] = {
    "github": "https://github.com/{u}",
    "gitlab": "https://gitlab.com/{u}",
    "codeberg": "https://codeberg.org/{u}",
    "bitbucket": "https://bitbucket.org/{u}",
    "devto": "https://dev.to/{u}",
    "hashnode": "https://hashnode.com/@{u}",
    "medium": "https://medium.com/@{u}",
    "pinterest": "https://www.pinterest.com/{u}",
    "twitch": "https://www.twitch.tv/{u}",
    "youtube": "https://www.youtube.com/@{u}",
    "soundcloud": "https://soundcloud.com/{u}",
    "spotify": "https://open.spotify.com/user/{u}",
    "steam": "https://steamcommunity.com/id/{u}",
    "roblox": "https://www.roblox.com/user.aspx?username={u}",
    "hackernews": "https://news.ycombinator.com/user?id={u}",
    "producthunt": "https://www.producthunt.com/@{u}",
    "behance": "https://www.behance.net/{u}",
    "dribbble": "https://dribbble.com/{u}",
    "flickr": "https://www.flickr.com/people/{u}",
    "vimeo": "https://vimeo.com/{u}",
    "aboutme": "https://about.me/{u}",
    "linktr": "https://linktr.ee/{u}",
    "buymeacoffee": "https://www.buymeacoffee.com/{u}",
    "kofi": "https://ko-fi.com/{u}",
    "patreon": "https://www.patreon.com/{u}",
    "trello": "https://trello.com/{u}",
    "npm": "https://www.npmjs.com/~{u}",
    "pypi": "https://pypi.org/user/{u}",
    "dockerhub": "https://hub.docker.com/u/{u}",
    "replit": "https://replit.com/@{u}",
    "codepen": "https://codepen.io/{u}",
    "jsfiddle": "https://jsfiddle.net/user/{u}",
    "pastebin": "https://pastebin.com/u/{u}",
    "wattpad": "https://www.wattpad.com/user/{u}",
    "goodreads": "https://www.goodreads.com/{u}",
    "letterboxd": "https://letterboxd.com/{u}",
    "trakt": "https://trakt.tv/users/{u}",
    "lastfm": "https://www.last.fm/user/{u}",
    "mixcloud": "https://www.mixcloud.com/{u}",
    "bandcamp": "https://bandcamp.com/{u}",
    "etsy": "https://www.etsy.com/shop/{u}",
    "ebay": "https://www.ebay.com/usr/{u}",
    "fiverr": "https://www.fiverr.com/{u}",
    "upwork": "https://www.upwork.com/freelancers/~{u}",
    "stackoverflow": "https://stackoverflow.com/users/{u}",
    "quora": "https://www.quora.com/profile/{u}",
    "mastodon.social": "https://mastodon.social/@{u}",
    "lemmy": "https://lemmy.world/u/{u}",
    "threads": "https://www.threads.net/@{u}",
    "bluesky": "https://bsky.app/profile/{u}.bsky.social",
}

@dataclass
class EnumHit:
    platform: str
    url: str
    status: int

class UsernameEnumProvider(Provider):
    """يفحص وجود الاسم على منصات كثيرة بالتوازي."""

    name = "enum"
    homepage = "https://osintx.local/enum"
    enabled = True

    def __init__(self, targets: dict[str, str] | None = None, concurrency: int = 12) -> None:
        self.targets = dict(targets or TARGETS)
        self.concurrency = concurrency

    def profile_url(self, username: str, instance: str | None = None) -> str:
        return f"https://github.com/{username}"

    async def _probe(self, fetcher: Fetcher, platform: str, template: str, username: str) -> EnumHit | None:
        url = template.format(u=username)
        try:
            blob = await fetcher.get_bytes(url, max_bytes=64_000)
        except Exception:  # noqa: BLE001
            return None
        if not blob:
            return None
        return EnumHit(platform, url, 200)

    async def scan(self, fetcher: Fetcher, username: str) -> list[EnumHit]:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def guarded(platform: str, template: str) -> EnumHit | None:
            async with semaphore:
                return await self._probe(fetcher, platform, template, username)

        results = await asyncio.gather(
            *(guarded(p, t) for p, t in self.targets.items()), return_exceptions=True
        )
        return [r for r in results if isinstance(r, EnumHit)]

    async def fetch(
        self,
        fetcher: Fetcher,
        username: str,
        *,
        instance: str | None = None,
    ) -> SocialProfile:
        hits = await self.scan(fetcher, username)
        if not hits:
            raise ProviderError(f"enum: لا نتائج لـ {username}")
        profile = SocialProfile(
            platform=self.name,
            username=username,
            url=self.profile_url(username),
            display_name=f"بصمة رقمية ({len(hits)} منصة)",
            raw={"hits": [{"platform": h.platform, "url": h.url} for h in hits]},
        )
        return profile
