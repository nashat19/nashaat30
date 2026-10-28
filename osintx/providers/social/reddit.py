"""مزوّد Reddit عبر about.json العام."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile

API = "https://www.reddit.com/user/{username}/about.json"

class RedditProvider(Provider):
    name = "reddit"
    homepage = "https://reddit.com"

    def profile_url(self, username: str, instance: str | None = None) -> str:
        return f"https://reddit.com/user/{username}"

    async def fetch(
        self,
        fetcher: Fetcher,
        username: str,
        *,
        instance: str | None = None,
    ) -> SocialProfile:
        try:
            data: Any = await fetcher.get_json(
                API.format(username=username), headers={"Accept": "application/json"}
            )
        except ProfileNotFound as exc:
            raise ProfileNotFound(f"reddit:{username}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"reddit: {exc}") from exc

        payload = (data or {}).get("data") if isinstance(data, dict) else None
        if not payload or payload.get("is_suspended"):
            raise ProfileNotFound(f"reddit:{username}")

        subreddit = payload.get("subreddit") or {}
        created = payload.get("created_utc")
        created_at = (
            datetime.fromtimestamp(created, tz=timezone.utc).isoformat() if created else None
        )

        profile = SocialProfile(
            platform=self.name,
            username=payload.get("name", username),
            url=self.profile_url(payload.get("name", username)),
            display_name=subreddit.get("title") or payload.get("name"),
            bio=subreddit.get("public_description") or payload.get("description"),
            location_text=subreddit.get("public_description"),
            avatar_url=payload.get("icon_img") or None,
            followers=payload.get("total_karma"),
            created_at=created_at,
            verified=bool(payload.get("verified")),
            raw={"is_mod": payload.get("is_mod"), "is_gold": payload.get("is_gold")},
        )
        await profile.harvest(fetcher)
        return profile
