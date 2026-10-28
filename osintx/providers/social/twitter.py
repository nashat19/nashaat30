"""مزوّد X/Twitter عبر واجهة fxtwitter العامة."""
from __future__ import annotations

from typing import Any

from .base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile

API = "https://api.fxtwitter.com/{username}"

class TwitterProvider(Provider):
    name = "twitter"
    homepage = "https://x.com"

    def profile_url(self, username: str, instance: str | None = None) -> str:
        return f"https://x.com/{username}"

    async def fetch(
        self,
        fetcher: Fetcher,
        username: str,
        *,
        instance: str | None = None,
    ) -> SocialProfile:
        try:
            data: Any = await fetcher.get_json(API.format(username=username))
        except ProfileNotFound as exc:
            raise ProfileNotFound(f"twitter:{username}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"twitter: {exc}") from exc

        if not isinstance(data, dict) or data.get("code") not in (200, None):
            raise ProfileNotFound(f"twitter:{username}")

        user = data.get("user") or {}
        if not user:
            raise ProfileNotFound(f"twitter:{username}")

        verification = user.get("verification") or {}
        profile = SocialProfile(
            platform=self.name,
            username=user.get("screen_name", username),
            url=user.get("url") or self.profile_url(username),
            display_name=user.get("name"),
            bio=user.get("description"),
            location_text=user.get("location"),
            website=user.get("website"),
            avatar_url=user.get("avatar_url"),
            followers=user.get("followers"),
            following=user.get("following"),
            posts=user.get("tweets"),
            verified=bool(verification.get("verified")),
            created_at=user.get("joined"),
            raw={"banner_url": user.get("banner_url")},
        )
        await profile.harvest(fetcher)
        return profile
