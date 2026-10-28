"""مزوّد Facebook عبر وسوم OpenGraph العامة."""
from __future__ import annotations

from .base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile, parse_meta

URL = "https://www.facebook.com/{username}"

class FacebookProvider(Provider):
    name = "facebook"
    homepage = "https://facebook.com"

    def profile_url(self, username: str, instance: str | None = None) -> str:
        return URL.format(username=username)

    async def fetch(
        self,
        fetcher: Fetcher,
        username: str,
        *,
        instance: str | None = None,
    ) -> SocialProfile:
        try:
            html = await fetcher.get_text(self.profile_url(username))
        except ProfileNotFound as exc:
            raise ProfileNotFound(f"facebook:{username}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"facebook: {exc}") from exc

        meta = parse_meta(html)
        title = meta.meta.get("og:title") or meta.title
        if not title:
            raise ProfileNotFound(f"facebook:{username}")

        description = meta.meta.get("og:description")
        profile = SocialProfile(
            platform=self.name,
            username=username,
            url=self.profile_url(username),
            display_name=title,
            bio=description,
            location_text=description,
            avatar_url=meta.meta.get("og:image"),
            raw={"site_name": meta.meta.get("og:site_name")},
        )
        await profile.harvest(fetcher)
        return profile
