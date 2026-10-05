"""Pull all current GSA Auctions listings and print the active-listing count."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://api.gsa.gov/assets/gsaauctions/v2/auctions"

# Recommended: set an environment variable named GSA_API_KEY.
# Or replace the placeholder below with your key for local testing.
API_KEY = os.getenv("GSA_API_KEY", "PASTE_YOUR_GSA_API_KEY_HERE")


def _get_field(record: dict, field_name: str):
    """Read a field even if the upstream JSON contains accidental whitespace in keys."""
    for key, value in record.items():
        if key.strip() == field_name:
            return value
    return None


def fetch_active_listings() -> list[dict]:
    """Fetch the GSA Auctions feed and return only listings marked Active (A)."""
    if not API_KEY or API_KEY == "PASTE_YOUR_GSA_API_KEY_HERE":
        raise RuntimeError(
            "GSA API key is missing. Set GSA_API_KEY or paste your key into API_KEY."
        )

    query = urlencode({"api_key": API_KEY, "format": "JSON"})
    request = Request(
        f"{API_URL}?{query}",
        headers={
            "Accept": "application/json",
            # GSA's current OpenAPI also documents X-API-KEY authentication.
            "X-API-KEY": API_KEY,
            "User-Agent": "GovFlip-GSA-Collector/1.0",
        },
    )

    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8-sig"))
    except HTTPError as exc:
        raise RuntimeError(f"GSA API returned HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not connect to the GSA API: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("GSA API returned data that was not valid JSON.") from exc

    # Official examples/schema use a top-level Results array.
    if isinstance(payload, dict):
        listings = payload.get("Results")
        if listings is None:
            listings = payload.get("results")
    elif isinstance(payload, list):
        # Defensive fallback in case GSA serves the downloaded JSON as a bare array.
        listings = payload
    else:
        listings = None

    if not isinstance(listings, list):
        raise RuntimeError(
            "Unexpected GSA API response: could not find the listings array."
        )

    # Catch API-level errors such as {"status": "NOK", "error": "..."}.
    if listings and isinstance(listings[0], dict):
        api_status = str(_get_field(listings[0], "status") or "").upper()
        api_error = _get_field(listings[0], "error")
        if api_status == "NOK" or api_error:
            raise RuntimeError(f"GSA API error: {api_error or 'request failed'}")

    active_listings = [
        listing
        for listing in listings
        if isinstance(listing, dict)
        and str(_get_field(listing, "AuctionStatus") or "").strip().upper() == "A"
    ]

    return active_listings


def main() -> None:
    active_listings = fetch_active_listings()
    print(f"Total active GSA listings: {len(active_listings)}")


if __name__ == "__main__":
    main()
