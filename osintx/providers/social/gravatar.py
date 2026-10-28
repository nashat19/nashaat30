"""مزوّد Gravatar عبر ملف JSON العام (يتطلب بريداً أو بصمة MD5)."""
from __future__ import annotations

import hashlib
from typing import Any

from .base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile

API = "https://gravatar.com/{digest}.json"

def digest_for(identifier: str) -> str:
    return hashlib.md5(identifier.strip().lower().encode("utf-8")).hexdigest()

class GravatarProvider(Provider):
    name = "gravatar"
    homepage = "https://gravatar.com"

    def profile_url(self, username: str, instance: str | None = None) -> str:
        return f"https://gravatar.com/{digest_for(username)}"

    async def fetch(
        self,
        fetcher: Fetcher,
        username: str,
        *,
        instance: str | None = None,
    ) -> SocialProfile:
        digest = digest_for(username)
        try:
            data: Any = await fetcher.get_json(API.format(digest=digest))
        except ProfileNotFound as exc:
            raise ProfileNotFound(f"gravatar:{username}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"gravatar: {exc}") from exc

        entries = (data or {}).get("entry") if isinstance(data, dict) else None
        if not entries:
            raise ProfileNotFound(f"gravatar:{username}")

        entry = entries[0]
        profile_data = entry.get("profile") or {}
        accounts = entry.get("accounts") or []

        profile = SocialProfile(
            platform=self.name,
            username=username,
            url=self.profile_url(username),
            display_name=profile_data.get("name") or entry.get("displayName"),
            bio=profile_data.get("aboutMe"),
            location_text=profile_data.get("currentLocation"),
            avatar_url=entry.get("thumbnailUrl"),
            raw={
                "accounts": [
                    {"domain": a.get("domain"), "url": a.get("url")} for a in accounts
                ],
                "urls": entry.get("urls"),
            },
        )
        await profile.harvest(fetcher)
        return profile
