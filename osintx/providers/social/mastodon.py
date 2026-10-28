"""مزوّد Mastodon — يتطلب تحديد نسخة (instance)."""
from __future__ import annotations

from typing import Any

from .base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile

API = "https://{instance}/api/v1/accounts/lookup?acct={username}"

class MastodonProvider(Provider):
    name = "mastodon"
    homepage = "https://joinmastodon.org"
    requires_instance = True
    default_instance = "mastodon.social"

    def profile_url(self, username: str, instance: str | None = None) -> str:
        host = instance or self.default_instance
        return f"https://{host}/@{username}"

    async def fetch(
        self,
        fetcher: Fetcher,
        username: str,
        *,
        instance: str | None = None,
    ) -> SocialProfile:
        host = (instance or self.default_instance or "").strip().rstrip("/")
        if not host:
            raise ProviderError("mastodon: يلزم تحديد instance")

        try:
            data: Any = await fetcher.get_json(
                API.format(instance=host, username=username),
                headers={"Accept": "application/json"},
            )
        except ProfileNotFound as exc:
            raise ProfileNotFound(f"mastodon:{host}/{username}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"mastodon: {exc}") from exc

        if not isinstance(data, dict) or not data.get("id"):
            raise ProfileNotFound(f"mastodon:{host}/{username}")

        fields = {f.get("name", "").lower(): f.get("value") for f in data.get("fields") or []}
        location_text = fields.get("location") or fields.get("الموقع")

        profile = SocialProfile(
            platform=self.name,
            username=data.get("acct", username),
            url=data.get("url") or self.profile_url(username, host),
            display_name=data.get("display_name"),
            bio=data.get("note"),
            location_text=location_text,
            avatar_url=data.get("avatar"),
            followers=data.get("followers_count"),
            following=data.get("following_count"),
            posts=data.get("statuses_count"),
            created_at=data.get("created_at"),
            raw={"instance": host, "fields": fields, "bot": data.get("bot")},
        )
        await profile.harvest(fetcher)
        return profile
