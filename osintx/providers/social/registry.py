"""سجل مزوّدي المنصات الاجتماعية."""
from __future__ import annotations

from typing import Iterable

from .base import Provider
from .facebook import FacebookProvider
from .github import GitHubProvider
from .gravatar import GravatarProvider
from .instagram import InstagramProvider
from .keybase import KeybaseProvider
from .linkedin import LinkedInProvider
from .mastodon import MastodonProvider
from .reddit import RedditProvider
from .telegram import TelegramProvider
from .tiktok import TikTokProvider
from .twitter import TwitterProvider
from .username_enum import UsernameEnumProvider

__all__ = [
    "PROVIDERS",
    "get_provider",
    "all_providers",
    "provider_names",
    "resolve_providers",
]

PROVIDERS: dict[str, Provider] = {
    provider.name: provider
    for provider in (
        GitHubProvider(),
        TwitterProvider(),
        InstagramProvider(),
        TelegramProvider(),
        RedditProvider(),
        MastodonProvider(),
        TikTokProvider(),
        LinkedInProvider(),
        FacebookProvider(),
        KeybaseProvider(),
        GravatarProvider(),
        UsernameEnumProvider(),
    )
}

def get_provider(name: str) -> Provider:
    key = name.strip().lower()
    if key not in PROVIDERS:
        raise KeyError(f"مزوّد غير معروف: {name}")
    return PROVIDERS[key]

def all_providers() -> list[Provider]:
    return [p for p in PROVIDERS.values() if p.enabled]

def provider_names() -> list[str]:
    return sorted(PROVIDERS)

def resolve_providers(names: Iterable[str] | None) -> list[Provider]:
    if not names:
        return all_providers()
    resolved: list[Provider] = []
    for name in names:
        provider = get_provider(name)
        if provider.enabled:
            resolved.append(provider)
    return resolved
