import os
import json
import requests
import psycopg

from flask import Flask, jsonify


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# SETTINGS
# ============================================================

DATABASE_URL = os.environ.get("DATABASE_URL")

AUCTION_API_URL = (
    "https://gateway.pipeworx.io/v1/tools/us_auctions_search"
)


# This will store the result of the startup import
STARTUP_RESULT = {
    "status": "starting"
}


# ============================================================
# DATABASE
# ============================================================

def create_listings_table():

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable is missing."
        )

    with psycopg.connect(DATABASE_URL) as conn:

        with conn.cursor() as cur:

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

        conn.commit()

    print("LISTINGS TABLE READY")


# ============================================================
# HELPER
# ============================================================

def first_value(data, *keys):

    if not isinstance(data, dict):
        return None

    for key in keys:

        if key in data:

            value = data[key]

            if value is not None:

                if isinstance(value, dict):

                    # Try common nested names first

                    for nested_key in [
                        "name",
                        "title",
                        "label",
                        "value",
                        "code"
                    ]:

                        if value.get(nested_key):
                            return str(value[nested_key])

                    return json.dumps(value)

                if isinstance(value, list):
                    return json.dumps(value)

                return str(value)

    return None


# ============================================================
# FIND LISTING INSIDE API RESPONSE
# ============================================================

def find_listing(obj):

    if isinstance(obj, dict):

        keys = set(obj.keys())

        # ----------------------------------------------------
        # Looks like an auction listing
        # ----------------------------------------------------

        has_title = (
            "title" in keys
            or "name" in keys
        )

        has_url = any(
            key in keys
            for key in [
                "listing_url",
                "url",
                "link",
                "lot_url",
                "source_url"
            ]
        )

        if has_title and has_url:
            return obj

        # ----------------------------------------------------
        # Check common result containers first
        # ----------------------------------------------------

        for key in [
            "results",
            "listings",
            "lots",
            "items",
            "data",
            "result"
        ]:

            if key in obj:

                found = find_listing(obj[key])

                if found is not None:
                    return found

        # ----------------------------------------------------
        # Search everything recursively
        # ----------------------------------------------------

        for value in obj.values():

            found = find_listing(value)

            if found is not None:
                return found


    elif isinstance(obj, list):

        for item in obj:

            found = find_listing(item)

            if found is not None:
                return found

    return None


# ============================================================
# LOCATION
# ============================================================

def extract_location(raw_listing):

    location = raw_listing.get("location")

    if isinstance(location, str):
        return location

    if isinstance(location, dict):

        # Try full formatted value first

        for key in [
            "formatted",
            "full",
            "name",
            "address"
        ]:

            if location.get(key):
                return str(location[key])

        # Build city/state if available

        city = location.get("city")
        state = location.get("state")

        if isinstance(state, dict):

            state = (
                state.get("code")
                or state.get("name")
            )

        pieces = []

        if city:
            pieces.append(str(city))

        if state:
            pieces.append(str(state))

        if pieces:
            return ", ".join(pieces)

        return json.dumps(location)

    return first_value(
        raw_listing,
        "city",
        "location_name"
    )


# ============================================================
# STATE
# ============================================================

def extract_state(raw_listing):

    # --------------------------------------------------------
    # State directly on listing
    # --------------------------------------------------------

    state = raw_listing.get("state")

    if state:

        if isinstance(state, dict):

            return (
                state.get("code")
                or state.get("abbreviation")
                or state.get("name")
            )

        return str(state)

    # --------------------------------------------------------
    # State nested inside location
    # --------------------------------------------------------

    location = raw_listing.get("location")

    if isinstance(location, dict):

        state = location.get("state")

        if isinstance(state, dict):

            return (
                state.get("code")
                or state.get("abbreviation")
                or state.get("name")
            )

        if state:
            return str(state)

    return None


# ============================================================
# NORMALIZE LISTING
# ============================================================

def normalize_listing(raw_listing):

    listing = {

        # ----------------------------------------------------
        # URL
        # ----------------------------------------------------

        "listing_url": first_value(
            raw_listing,
            "listing_url",
            "url",
            "link",
            "lot_url",
            "source_url"
        ),

        # ----------------------------------------------------
        # AUCTION HOUSE
        # ----------------------------------------------------

        "auction_house": first_value(
            raw_listing,
            "auction_house",
            "selling_house",
            "auctioneer",
            "seller",
            "house",
            "source"
        ),

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        "title": first_value(
            raw_listing,
            "title",
            "name"
        ),

        # ----------------------------------------------------
        # ID
        # ----------------------------------------------------

        "id": first_value(
            raw_listing,
            "id",
            "listing_id",
            "lot_id",
            "item_id"
        ),

        # ----------------------------------------------------
        # DESCRIPTION
        # ----------------------------------------------------

        "description": first_value(
            raw_listing,
            "description",
            "lot_description",
            "details",
            "summary"
        ),

        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

        "category": first_value(
            raw_listing,
            "category",
            "asset_type",
            "type"
        ),

        # ----------------------------------------------------
        # LOCATION
        # ----------------------------------------------------

        "location": extract_location(
            raw_listing
        ),

        # ----------------------------------------------------
        # STATE
        # ----------------------------------------------------

        "state": extract_state(
            raw_listing
        ),

        # ----------------------------------------------------
        # END TIME
        # ----------------------------------------------------

        "end_time": first_value(
            raw_listing,
            "end_time",
            "close_time",
            "closing_time",
            "closes_at",
            "ends_at",
            "end_date"
        )
    }

    return listing


# ============================================================
# GET ONE ACTIVE AUCTION
# ============================================================

def get_one_active_listing():

    print("")
    print("CALLING AUCTION API...")
    print("")

    response = requests.post(
        AUCTION_API_URL,

        json={
            "limit": 1
        },

        headers={
            "Content-Type": "application/json"
        },

        timeout=30
    )

    print(
        "AUCTION API STATUS:",
        response.status_code
    )

    response.raise_for_status()

    data = response.json()

    # --------------------------------------------------------
    # PRINT RAW JSON
    # --------------------------------------------------------

    print("")
    print("======================================")
    print("RAW AUCTION API RESPONSE")
    print("======================================")

    print(
        json.dumps(
            data,
            indent=2
        )
    )

    print(
        "======================================"
    )

    # --------------------------------------------------------
    # FIND FIRST LISTING
    # --------------------------------------------------------

    raw_listing = find_listing(data)

    if raw_listing is None:

        raise RuntimeError(
            "The API responded, but no listing could be found."
        )

    listing = normalize_listing(
        raw_listing
    )

    # --------------------------------------------------------
    # ID IS REQUIRED FOR DATABASE PRIMARY KEY
    # --------------------------------------------------------

    if not listing["id"]:

        raise RuntimeError(
            "Listing was found but API listing ID was missing."
        )

    return listing


# ============================================================
# PRINT LISTING
# ============================================================

def print_listing(listing):

    print("")
    print("======================================")
    print("NORMALIZED LISTING")
    print("======================================")
    print("")

    print(
        "listing_url:",
        listing["listing_url"]
    )

    print(
        "auction_house:",
        listing["auction_house"]
    )

    print(
        "title:",
        listing["title"]
    )

    print(
        "id:",
        listing["id"]
    )

    print(
        "description:",
        listing["description"]
    )

    print(
        "category:",
        listing["category"]
    )

    print(
        "location:",
        listing["location"]
    )

    print(
        "state:",
        listing["state"]
    )

    print(
        "end_time:",
        listing["end_time"]
    )

    print("")
    print(
        "======================================"
    )
    print("")


# ============================================================
# INSERT LISTING INTO NEON
# ============================================================

def save_listing(listing):

    print(
        "CONNECTING TO NEON..."
    )

    with psycopg.connect(
        DATABASE_URL
    ) as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
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

                    listing_url =
                        EXCLUDED.listing_url,

                    auction_house =
                        EXCLUDED.auction_house,

                    title =
                        EXCLUDED.title,

                    description =
                        EXCLUDED.description,

                    category =
                        EXCLUDED.category,

                    location =
                        EXCLUDED.location,

                    state =
                        EXCLUDED.state,

                    end_time =
                        EXCLUDED.end_time;
                """,

                (

                    listing["listing_url"],

                    listing["auction_house"],

                    listing["title"],

                    listing["id"],

                    listing["description"],

                    listing["category"],

                    listing["location"],

                    listing["state"],

                    listing["end_time"]

                )
            )

        conn.commit()

    print("")
    print(
        "SUCCESSFULLY SAVED LISTING TO NEON"
    )
    print("")


# ============================================================
# IMPORT ONE LISTING
# ============================================================

def import_one_listing():

    create_listings_table()

    listing = get_one_active_listing()

    print_listing(
        listing
    )

    save_listing(
        listing
    )

    return listing


# ============================================================
# FLASK HOME PAGE
# ============================================================

@app.route("/")
def home():

    return jsonify({

        "message":
            "Auction API + Neon application is running.",

        "startup_result":
            STARTUP_RESULT,

        "import_endpoint":
            "/import-one"

    })


# ============================================================
# MANUALLY IMPORT ONE ACTIVE LISTING
# ============================================================

@app.route("/import-one")
def import_one():

    try:

        listing = import_one_listing()

        return jsonify({

            "success": True,

            "message":
                "One active auction listing was saved to Neon.",

            "listing":
                listing

        })

    except Exception as error:

        print(
            "IMPORT ERROR:",
            str(error)
        )

        return jsonify({

            "success": False,

            "error":
                str(error)

        }), 500


# ============================================================
# STARTUP IMPORT
# ============================================================

try:

    listing = import_one_listing()

    STARTUP_RESULT = {

        "success": True,

        "message":
            "One active listing was imported during startup.",

        "listing":
            listing

    }

except Exception as error:

    print("")
    print(
        "STARTUP IMPORT FAILED:"
    )

    print(
        str(error)
    )

    print("")

    # IMPORTANT:
    # We do not crash Flask if the auction API
    # or database temporarily fails.

    STARTUP_RESULT = {

        "success": False,

        "error":
            str(error)

    }


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
