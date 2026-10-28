"""مزوّد Telegram عبر صفحة t.me العامة."""
from __future__ import annotations

from .base import Fetcher, ProfileNotFound, Provider, ProviderError, SocialProfile, parse_meta

class TelegramProvider(Provider):
    name = "telegram"
    homepage = "https://t.me"

    def profile_url(self, username: str, instance: str | None = None) -> str:
        return f"https://t.me/{username}"

    async def fetch(
        self,
        fetcher: Fetcher,
        username: str,
        *,
        instance: str | None = None,
    ) -> SocialProfile:
        url = self.profile_url(username)
        try:
            html = await fetcher.get_text(url)
        except ProfileNotFound as exc:
            raise ProfileNotFound(f"telegram:{username}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"telegram: {exc}") from exc

        meta = parse_meta(html)
        title = meta.meta.get("og:title") or meta.title or ""
        description = meta.meta.get("og:description") or ""
        if not title and not description:
            raise ProfileNotFound(f"telegram:{username}")

        followers = None
        for token in description.replace(",", " ").split():
            if token.isdigit():
                followers = int(token)
                break

        profile = SocialProfile(
            platform=self.name,
            username=username,
            url=url,
            display_name=title or None,
            bio=description or None,
            location_text=description or None,
            avatar_url=meta.meta.get("og:image"),
            followers=followers,
            raw={"site_name": meta.meta.get("og:site_name")},
        )
        await profile.harvest(fetcher)
        return profile
