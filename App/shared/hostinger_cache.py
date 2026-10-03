"""Clears babyluzconfeccao.com.br's server-side cache via the Hostinger
hosting-platform API (developers.hostinger.com) -- separate from the site's
own PHP API in website_sync.py. website_sync.py calls clear() after every
publish/delete so the public showcase never shows stale catalogs without
someone having to remember to clear the cache by hand.
"""
import requests

import paths

API_BASE_URL = "https://developers.hostinger.com/api/hosting/v1"
ACCOUNT_USERNAME = "u215014885"
DOMAIN = "babyluzconfeccao.com.br"


def clear() -> bool:
    """Best-effort: returns False (never raises) if there's no hPanel API key
    configured or the call fails -- a stale cache is a nuisance, not worth
    failing a publish/delete over."""
    api_key = paths.read_hpanel_api_key()
    if not api_key:
        return False
    try:
        response = requests.delete(
            f"{API_BASE_URL}/accounts/{ACCOUNT_USERNAME}/websites/{DOMAIN}/cache/clear",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
        return response.status_code < 300
    except requests.RequestException:
        return False
