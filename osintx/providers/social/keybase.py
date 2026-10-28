"""مزوّد Keybase عبر واجهة lookup العامة."""
from __future__ import annotations

from typing import Any

from .base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile

API = "https://keybase.io/_/api/1.0/user/lookup.json?username={username}&fields=profile,basics"

class KeybaseProvider(Provider):
    name = "keybase"
    homepage = "https://keybase.io"

    def profile_url(self, username: str, instance: str | None = None) -> str:
        return f"https://keybase.io/{username}"

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
            raise ProfileNotFound(f"keybase:{username}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"keybase: {exc}") from exc

        them = (data or {}).get("them") if isinstance(data, dict) else None
        if not them:
            raise ProfileNotFound(f"keybase:{username}")

        entry = them[0] if isinstance(them, list) else them
        profile_data = entry.get("profile") or {}
        basics = entry.get("basics") or {}

        profile = SocialProfile(
            platform=self.name,
            username=basics.get("username", username),
            url=self.profile_url(basics.get("username", username)),
            display_name=profile_data.get("full_name"),
            bio=profile_data.get("bio"),
            location_text=profile_data.get("location"),
            avatar_url=basics.get("picture_url"),
            created_at=str(basics.get("ctime")) if basics.get("ctime") else None,
            raw={"proofs": profile_data.get("proofs_summary")},
        )
        await profile.harvest(fetcher)
        return profile
