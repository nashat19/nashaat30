"""مزوّد TikTok عبر كتلة إعادة الترطيب المضمّنة."""
from __future__ import annotations

import json
from typing import Any

from .base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile, parse_meta

URL = "https://www.tiktok.com/@{username}"
REHYDRATION = "__UNIVERSAL_DATA_FOR_REHYDRATION__"

def _extract_user(html: str) -> dict[str, Any] | None:
    marker = html.find(REHYDRATION)
    if marker < 0:
        return None
    start = html.find(">", marker)
    end = html.find("</script>", start)
    if start < 0 or end < 0:
        return None
    blob = html[start + 1 : end].strip()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    scope = (data.get("__DEFAULT_SCOPE__") or {}).get("webapp.user-detail") or {}
    return (scope.get("userInfo") or {}).get("user")

class TikTokProvider(Provider):
    name = "tiktok"
    homepage = "https://tiktok.com"

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
            raise ProfileNotFound(f"tiktok:{username}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"tiktok: {exc}") from exc

        user = _extract_user(html)
        if not user:
            meta = parse_meta(html)
            if not meta.meta.get("og:title"):
                raise ProfileNotFound(f"tiktok:{username}")
            user = {
                "uniqueId": username,
                "nickname": meta.meta.get("og:title"),
                "signature": meta.meta.get("og:description"),
            }

        stats = user.get("stats") or {}
        profile = SocialProfile(
            platform=self.name,
            username=user.get("uniqueId", username),
            url=self.profile_url(user.get("uniqueId", username)),
            display_name=user.get("nickname"),
            bio=user.get("signature"),
            location_text=user.get("signature") or user.get("city"),
            avatar_url=user.get("avatarLarger") or user.get("avatarMedium"),
            followers=stats.get("followerCount"),
            following=stats.get("followingCount"),
            posts=stats.get("videoCount"),
            verified=bool(user.get("verified")),
            raw={"region": user.get("region"), "city": user.get("city")},
        )
        await profile.harvest(fetcher)
        return profile
