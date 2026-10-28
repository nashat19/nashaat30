"""مزوّد GitHub عبر واجهة REST العامة."""
from __future__ import annotations

from typing import Any

from .base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile

API = "https://api.github.com/users/{username}"

class GitHubProvider(Provider):
    name = "github"
    homepage = "https://github.com"

    def profile_url(self, username: str, instance: str | None = None) -> str:
        return f"https://github.com/{username}"

    async def fetch(
        self,
        fetcher: Fetcher,
        username: str,
        *,
        instance: str | None = None,
    ) -> SocialProfile:
        url = API.format(username=username)
        try:
            data: Any = await fetcher.get_json(
                url, headers={"Accept": "application/vnd.github+json"}
            )
        except ProfileNotFound as exc:
            raise ProfileNotFound(f"github:{username}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"github: {exc}") from exc

        if not isinstance(data, dict) or data.get("message") == "Not Found":
            raise ProfileNotFound(f"github:{username}")

        profile = SocialProfile(
            platform=self.name,
            username=data.get("login", username),
            url=data.get("html_url") or self.profile_url(username),
            display_name=data.get("name"),
            bio=data.get("bio"),
            location_text=data.get("location"),
            website=data.get("blog") or None,
            avatar_url=data.get("avatar_url"),
            followers=data.get("followers"),
            following=data.get("following"),
            posts=data.get("public_repos"),
            created_at=data.get("created_at"),
            raw={
                "company": data.get("company"),
                "twitter_username": data.get("twitter_username"),
                "public_gists": data.get("public_gists"),
                "hireable": data.get("hireable"),
            },
        )
        await profile.harvest(fetcher)
        return profile
