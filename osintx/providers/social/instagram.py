"""مزوّد Instagram عبر نقطة web_profile_info."""
from __future__ import annotations

import json
from typing import Any

from .base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile

API = "https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
APP_ID = "936619743392459"

class InstagramProvider(Provider):
    name = "instagram"
    homepage = "https://instagram.com"

    def profile_url(self, username: str, instance: str | None = None) -> str:
        return f"https://instagram.com/{username}"

    async def fetch(
        self,
        fetcher: Fetcher,
        username: str,
        *,
        instance: str | None = None,
    ) -> SocialProfile:
        try:
            data: Any = await fetcher.get_json(
                API.format(username=username),
                headers={"x-ig-app-id": APP_ID, "Accept": "application/json"},
            )
        except ProfileNotFound as exc:
            raise ProfileNotFound(f"instagram:{username}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"instagram: {exc}") from exc

        user = ((data or {}).get("data") or {}).get("user") if isinstance(data, dict) else None
        if not user:
            raise ProfileNotFound(f"instagram:{username}")

        address: dict[str, Any] = {}
        if user.get("business_address_json"):
            try:
                address = json.loads(user["business_address_json"])
            except (json.JSONDecodeError, TypeError):
                address = {}

        location_parts = [
            user.get("city_name"),
            address.get("city_name"),
            address.get("street_address"),
            address.get("zip_code"),
        ]
        location_text = ", ".join(p for p in location_parts if p) or None

        profile = SocialProfile(
            platform=self.name,
            username=user.get("username", username),
            url=self.profile_url(user.get("username", username)),
            display_name=user.get("full_name"),
            bio=user.get("biography"),
            location_text=location_text,
            website=user.get("external_url"),
            avatar_url=user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
            followers=(user.get("edge_followed_by") or {}).get("count"),
            following=(user.get("edge_follow") or {}).get("count"),
            posts=(user.get("edge_owner_to_timeline_media") or {}).get("count"),
            verified=bool(user.get("is_verified")),
            raw={"category": user.get("category_name"), "business": bool(address)},
        )
        await profile.harvest(fetcher)
        return profile
