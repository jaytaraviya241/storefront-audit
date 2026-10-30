"""Identify the ecommerce platform, theme and third-party apps from page source."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# script hosts mapped to what a merchant would recognise
KNOWN_APPS = {
    "klaviyo.com": "Klaviyo", "judge.me": "Judge.me", "yotpo.com": "Yotpo", "stamped.io": "Stamped",
    "okendo.io": "Okendo", "googletagmanager.com": "Google Tag Manager", "google-analytics.com": "Google Analytics",
    "connect.facebook.net": "Meta Pixel", "analytics.tiktok.com": "TikTok Pixel", "hotjar.com": "Hotjar",
    "gorgias.chat": "Gorgias", "tidiochat.com": "Tidio", "intercom": "Intercom", "zendesk": "Zendesk",
    "privy.com": "Privy", "rechargecdn.com": "Recharge", "rechargeapps.com": "Recharge",
    "smile.io": "Smile.io", "loox.io": "Loox", "afterpay.com": "Afterpay", "klarna": "Klarna",
    "shopifycloud": "Shopify", "pinimg.com": "Pinterest Tag", "snapchat.com": "Snap Pixel",
    "clarity.ms": "Microsoft Clarity", "attentive": "Attentive", "postscript": "Postscript",
    "boostcommerce": "Boost", "searchanise": "Searchanise", "rebuyengine.com": "Rebuy",
    "zipify": "Zipify", "pagefly": "PageFly", "gempages": "GemPages", "shogun": "Shogun",
    "cookiebot": "Cookiebot", "onetrust": "OneTrust", "usercentrics": "Usercentrics",
}


@dataclass
class Platform:
    name: str = "unknown"
    theme: str = ""
    third_party_hosts: list[str] = field(default_factory=list)
    apps: list[str] = field(default_factory=list)


def _root(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def detect(html: str, url: str, script_srcs: list[str]) -> Platform:
    platform = Platform()
    if "cdn.shopify.com" in html or "Shopify.shop" in html:
        platform.name = "Shopify"
        match = re.search(r"Shopify\.theme\s*=\s*(\{.*?\});", html)
        if match:
            try:
                platform.theme = json.loads(match.group(1)).get("name", "")
            except json.JSONDecodeError:
                pass
        if not platform.theme:
            match = re.search(r'"theme_name"\s*:\s*"([^"]+)"', html)
            platform.theme = match.group(1) if match else ""
    elif "Magento_" in html or "mage/cookies" in html or "/static/version" in html:
        platform.name = "Magento"
    elif "woocommerce" in html.lower():
        platform.name = "WooCommerce"
    elif "bigcommerce" in html.lower():
        platform.name = "BigCommerce"

    site_root = _root(urlsplit(url).netloc.lower())
    hosts, apps = set(), set()
    first_party = {site_root, "shopify.com", "myshopify.com"}
    for src in script_srcs:
        host = urlsplit(src).netloc.lower()
        if not host or _root(host) in first_party:
            continue
        hosts.add(host)
        for needle, app in KNOWN_APPS.items():
            if needle in host:
                apps.add(app)
    platform.third_party_hosts = sorted(hosts)
    platform.apps = sorted(apps)
    return platform
