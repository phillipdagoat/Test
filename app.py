import os
from decimal import Decimal, InvalidOperation

import requests
import psycopg
from flask import Flask, jsonify


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

DATABASE_URL = os.environ.get("DATABASE_URL")
GSA_API_KEY = os.environ.get("GSA_API_KEY")


# ============================================================
# GSA API
# ============================================================

GSA_URL = "https://api.gsa.gov/assets/gsaauctions/v2/auctions"


# ============================================================
# CREATE TABLE IF IT DOES NOT EXIST
# ============================================================

def create_table():

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing.")

    with psycopg.connect(DATABASE_URL) as conn:

        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS listings (

                    id BIGSERIAL PRIMARY KEY,

                    start_time DATE,
                    end_time DATE,

                    title TEXT,

                    address TEXT,
                    city TEXT,
                    state TEXT,
                    zip_code TEXT,

                    description TEXT,

                    seller_name TEXT,
                    seller_email TEXT,
                    seller_phone TEXT,

                    reserve NUMERIC(12, 2),
                    bid_increment NUMERIC(12, 2),

                    photo_url TEXT
                );
            """)

        conn.commit()


# ============================================================
# FIND FIRST LISTING IN GSA RESPONSE
# ============================================================

def find_first_listing(data):

    # --------------------------------------------------------
    # If response itself is a list
    # --------------------------------------------------------

    if isinstance(data, list):

        for item in data:

            if isinstance(item, dict):

                # Looks like a GSA listing
                if "SaleNo" in item or "ItemName" in item:
                    return item

                found = find_first_listing(item)

                if found:
                    return found

    # --------------------------------------------------------
    # If response is a dictionary
    # --------------------------------------------------------

    if isinstance(data, dict):

        # This dictionary itself may be a listing
        if "SaleNo" in data or "ItemName" in data:
            return data

        # Search nested dictionaries/lists
        for value in data.values():

            found = find_first_listing(value)

            if found:
                return found

    return None


# ============================================================
# CONVERT NUMERIC VALUES
# ============================================================

def to_decimal(value):

    if value is None:
        return None

    if value == "":
        return None

    try:

        # Remove dollar signs and commas if GSA returns them
        cleaned = str(value).replace("$", "").replace(",", "").strip()

        return Decimal(cleaned)

    except (InvalidOperation, ValueError):

        return None


# ============================================================
# PULL ONE ACTIVE GSA LISTING
# ============================================================

def get_one_listing():

    if not GSA_API_KEY:
        raise RuntimeError("GSA_API_KEY is missing.")

    response = requests.get(
        GSA_URL,
        params={
            "api_key": GSA_API_KEY,
            "format": "JSON"
        },
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    listing = find_first_listing(data)

    if listing is None:
        raise RuntimeError(
            "GSA API responded successfully, but no listing was found."
        )

    return listing


# ============================================================
# MAP GSA VARIABLES TO YOUR VARIABLES
# ============================================================

def map_listing(gsa):

    listing = {

        # AucStartDt → start_time
        "start_time":
            gsa.get("AucStartDt"),

        # AucEndDt → end_time
        "end_time":
            gsa.get("AucEndDt"),

        # ItemName → title
        "title":
            gsa.get("ItemName"),

        # PropertyAddr3 → address
        "address":
            gsa.get("PropertyAddr3"),

        # PropertyCity → city
        "city":
            gsa.get("PropertyCity"),

        # PropertyState → state
        "state":
            gsa.get("PropertyState"),

        # PropertyZip → zip_code
        "zip_code":
            str(gsa.get("PropertyZip"))
            if gsa.get("PropertyZip") is not None
            else None,

        # LotDescript → description
        "description":
            gsa.get("LotDescript"),

        # ContractOfficer → seller_name
        "seller_name":
            gsa.get("ContractOfficer"),

        # COEmail → seller_email
        "seller_email":
            gsa.get("COEmail"),

        # COPhone → seller_phone
        "seller_phone":
            gsa.get("COPhone"),

        # Reserve → reserve
        "reserve":
            to_decimal(
                gsa.get("Reserve")
            ),

        # AucIncrement → bid_increment
        "bid_increment":
            to_decimal(
                gsa.get("AucIncrement")
            ),

        # ImageURL → photo_url
        "photo_url":
            gsa.get("ImageURL")
    }

    return listing


# ============================================================
# PRINT LISTING
# ============================================================

def print_listing(listing):

    print("")
    print("=====================================")
    print("GSA LISTING")
    print("=====================================")

    for key, value in listing.items():

        print(
            f"{key}: {value}"
        )

    print("=====================================")
    print("")


# ============================================================
# INSERT NEW ROW INTO NEON
# ============================================================

def insert_listing(listing):

    with psycopg.connect(DATABASE_URL) as conn:

        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO listings (
                    start_time,
                    end_time,
                    title,
                    address,
                    city,
                    state,
                    zip_code,
                    description,
                    seller_name,
                    seller_email,
                    seller_phone,
                    reserve,
                    bid_increment,
                    photo_url
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id;
            """, (
                listing["start_time"],
                listing["end_time"],
                listing["title"],
                listing["address"],
                listing["city"],
                listing["state"],
                listing["zip_code"],
                listing["description"],
                listing["seller_name"],
                listing["seller_email"],
                listing["seller_phone"],
                listing["reserve"],
                listing["bid_increment"],
                listing["photo_url"]
            ))

            new_id = cur.fetchone()[0]

        conn.commit()

    return new_id
# ============================================================
# COMPLETE IMPORT
# ============================================================

def import_one_listing():

    # Make sure database table exists
    create_table()

    # Pull one active listing from GSA
    raw_gsa_listing = get_one_listing()

    # Convert GSA names into your database names
    listing = map_listing(
        raw_gsa_listing
    )

    # Print it in Render logs
    print_listing(
        listing
    )

    # Insert new row into Neon
    new_id = insert_listing(
        listing
    )

    print(
        f"SUCCESS: New Neon row created. ID = {new_id}"
    )

    return new_id, listing


# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def home():

    return jsonify({

        "status": "running",

        "message":
            "GSA Auctions importer is running.",

        "import_one_listing":
            "/import-one"

    })


# ============================================================
# IMPORT ONE LISTING
# ============================================================

@app.route("/import-one")
@app.route("/import-one")
def import_one():
    try:
        create_table()

        raw_listing = get_one_listing()

        listing = map_listing(raw_listing)

        print("ABOUT TO INSERT:")
        print(listing)

        new_id = insert_listing(listing)

        print(f"ROW CREATED IN NEON WITH ID: {new_id}")

        return jsonify({
            "success": True,
            "database_id": new_id,
            "listing": listing
        })

    except Exception as error:
        print("IMPORT ERROR:", str(error))

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500
        # ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":
    # ============================================================
# IMPORT ONE LISTING WHEN RENDER STARTS
# ============================================================

    try:
        print("STARTING AUTOMATIC GSA IMPORT...")
    
        new_id, listing = import_one_listing()
    
        print("")
        print("=====================================")
        print("AUTOMATIC IMPORT SUCCESSFUL")
        print(f"NEW DATABASE ROW ID: {new_id}")
        print("=====================================")
        print("")

    except Exception as error:

        print("")
        print("=====================================")
        print("AUTOMATIC IMPORT FAILED")
        print(str(error))
        print("=====================================")
        print("")
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
