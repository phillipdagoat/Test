import os
import json
import requests
import psycopg


# ============================================================
# SETTINGS
# ============================================================

AUCTION_API_URL = "https://gateway.pipeworx.io/us-auctions/mcp"

# This should already be set in Render as an environment variable.
# Example:
# DATABASE_URL=postgresql://user:password@host.neon.tech/dbname?sslmode=require
DATABASE_URL = os.environ["DATABASE_URL"]


# ============================================================
# GET ONE AUCTION LISTING
# ============================================================

def get_one_listing():

    request_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "us_auctions_search",
            "arguments": {
                "limit": 1
            }
        }
    }

    response = requests.post(
        AUCTION_API_URL,
        headers={
            "Content-Type": "application/json"
        },
        json=request_body,
        timeout=30
    )

    response.raise_for_status()

    raw_response = response.json()

    # --------------------------------------------------------
    # Pipeworx is an MCP endpoint, so the actual auction
    # response may be inside result -> content -> text.
    # --------------------------------------------------------

    data = raw_response

    if "result" in raw_response:

        content = raw_response["result"].get("content", [])

        for block in content:

            if block.get("type") == "text":

                text = block.get("text", "")

                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    pass

                break

    # Find the first actual auction listing in the returned JSON
    raw_listing = find_first_listing(data)

    if raw_listing is None:
        print("Could not find an auction listing.")
        print("\nRAW API RESPONSE:")
        print(json.dumps(raw_response, indent=2))
        return None

    # --------------------------------------------------------
    # MAP API FIELDS TO OUR DATABASE FIELDS
    # --------------------------------------------------------

    listing = {
        "listing_url": first_value(
            raw_listing,
            "listing_url",
            "url",
            "link",
            "lot_url"
        ),

        "auction_house": first_value(
            raw_listing,
            "auction_house",
            "selling_house",
            "seller",
            "house"
        ),

        "title": first_value(
            raw_listing,
            "title",
            "name"
        ),

        "id": first_value(
            raw_listing,
            "id",
            "listing_id",
            "lot_id"
        ),

        "description": first_value(
            raw_listing,
            "description",
            "lot_description",
            "details"
        ),

        "category": first_value(
            raw_listing,
            "category",
            "asset_type",
            "type"
        ),

        "location": get_location(raw_listing),

        "state": get_state(raw_listing),

        "end_time": first_value(
            raw_listing,
            "end_time",
            "close_time",
            "closing_time",
            "ends_at",
            "auction_ends_at"
        )
    }

    return listing


# ============================================================
# HELPERS FOR FIELD MAPPING
# ============================================================

def first_value(dictionary, *keys):
    """
    Look through several possible API field names
    and return the first value found.
    """

    for key in keys:
        value = dictionary.get(key)

        if value is not None:
            # Some APIs return things such as:
            # {"name": "Auction House"}
            if isinstance(value, dict):

                if value.get("name"):
                    return str(value["name"])

                return json.dumps(value)

            return str(value)

    return None


def get_location(listing):

    value = listing.get("location")

    if value is None:
        return first_value(
            listing,
            "location_name",
            "city"
        )

    if isinstance(value, str):
        return value

    if isinstance(value, dict):

        # Try a normal city/location name first
        for key in ["name", "city", "raw", "location"]:

            item = value.get(key)

            if isinstance(item, str):
                return item

            if isinstance(item, dict) and item.get("name"):
                return item["name"]

        return json.dumps(value)

    return str(value)


def get_state(listing):

    # State may exist directly
    if listing.get("state"):
        state = listing["state"]

        if isinstance(state, dict):
            return (
                state.get("code")
                or state.get("name")
            )

        return str(state)

    # Or it may be nested inside location
    location = listing.get("location")

    if isinstance(location, dict):

        state = location.get("state")

        if isinstance(state, dict):
            return (
                state.get("code")
                or state.get("name")
            )

        if state:
            return str(state)

    return None


def find_first_listing(obj):
    """
    Recursively search the API response until we find
    what looks like an auction listing.
    """

    if isinstance(obj, dict):

        # These are strong signals that this dictionary
        # is an auction listing.
        keys = set(obj.keys())

        if (
            "title" in keys
            and (
                "listing_url" in keys
                or "url" in keys
                or "link" in keys
                or "lot_url" in keys
            )
        ):
            return obj

        # Common containers returned by APIs
        preferred_keys = [
            "lots",
            "listings",
            "results",
            "data",
            "items"
        ]

        for key in preferred_keys:

            if key in obj:

                result = find_first_listing(obj[key])

                if result is not None:
                    return result

        # Search everything else
        for value in obj.values():

            result = find_first_listing(value)

            if result is not None:
                return result

    elif isinstance(obj, list):

        for item in obj:

            result = find_first_listing(item)

            if result is not None:
                return result

    return None


# ============================================================
# PRINT THE LISTING
# ============================================================

def print_listing(listing):

    print("\n====================================")
    print("AUCTION LISTING")
    print("====================================\n")

    print("listing_url:", listing["listing_url"])
    print("auction_house:", listing["auction_house"])
    print("title:", listing["title"])
    print("id:", listing["id"])
    print("description:", listing["description"])
    print("category:", listing["category"])
    print("location:", listing["location"])
    print("state:", listing["state"])
    print("end_time:", listing["end_time"])

    print("\n====================================\n")


# ============================================================
# SAVE THE LISTING TO NEON
# ============================================================

def save_to_neon(listing):

    with psycopg.connect(DATABASE_URL) as conn:

        with conn.cursor() as cur:

            # -----------------------------------------------
            # Create table
            # -----------------------------------------------

            cur.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id TEXT PRIMARY KEY,
                    listing_url TEXT,
                    auction_house TEXT,
                    title TEXT,
                    description TEXT,
                    category TEXT,
                    location TEXT,
                    state TEXT,
                    end_time TEXT
                );
            """)

            # -----------------------------------------------
            # Insert exactly one listing
            # -----------------------------------------------

            cur.execute("""
                INSERT INTO listings (
                    listing_url,
                    auction_house,
                    title,
                    id,
                    description,
                    category,
                    location,
                    state,
                    end_time
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )

                ON CONFLICT (id)
                DO UPDATE SET

                    listing_url = EXCLUDED.listing_url,
                    auction_house = EXCLUDED.auction_house,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    location = EXCLUDED.location,
                    state = EXCLUDED.state,
                    end_time = EXCLUDED.end_time;
            """, (

                listing["listing_url"],
                listing["auction_house"],
                listing["title"],
                listing["id"],
                listing["description"],
                listing["category"],
                listing["location"],
                listing["state"],
                listing["end_time"]

            ))

        conn.commit()

    print("Listing successfully saved to Neon.")


# ============================================================
# RUN PROGRAM
# ============================================================

if __name__ == "__main__":

    listing = get_one_listing()

    if listing:

        print_listing(listing)

        save_to_neon(listing)
