import os
from decimal import Decimal, InvalidOperation

import requests
import psycopg
from flask import Flask, jsonify


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

DATABASE_URL = os.environ.get("DATABASE_URL")
GSA_API_KEY = os.environ.get("GSA_API_KEY")


# ============================================================
# GSA AUCTIONS API
# ============================================================

GSA_API_URL = "https://api.gsa.gov/assets/gsaauctions/v2/auctions"


# ============================================================
# NUMBER CLEANER
# ============================================================

def clean_number(value):

    if value is None:
        return None

    text = str(value).strip()

    if text == "":
        return None

    text = (
        text
        .replace("$", "")
        .replace(",", "")
    )

    try:
        return Decimal(text)

    except (InvalidOperation, ValueError):
        return None


# ============================================================
# ZIP CODE CLEANER
# ============================================================

def clean_zip(value):

    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    # Preserve 5-digit ZIP format
    if value.isdigit() and len(value) < 5:
        value = value.zfill(5)

    return value


# ============================================================
# CHECK DATABASE CONNECTION
# ============================================================

def check_database():

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing from Render."
        )

    with psycopg.connect(DATABASE_URL) as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT current_database();
            """)

            database_name = cur.fetchone()[0]

    print(
        "CONNECTED TO NEON DATABASE:",
        database_name
    )


# ============================================================
# CHECK ACTIVE_LISTINGS TABLE EXISTS
# ============================================================

def check_active_listings_table():

    with psycopg.connect(DATABASE_URL) as conn:

        with conn.cursor() as cur:

            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'active_listings'
                );
            """)

            exists = cur.fetchone()[0]

    if not exists:

        raise RuntimeError(
            "The active_listings table does not exist in Neon."
        )

    print("active_listings table found.")


# ============================================================
# FIND ONE ACTIVE GSA LISTING
# ============================================================

def find_active_listing(data):

    active_listing = None
    fallback_listing = None

    def search(obj):

        nonlocal active_listing
        nonlocal fallback_listing

        if active_listing is not None:
            return

        # ----------------------------------------------------
        # DICTIONARY
        # ----------------------------------------------------

        if isinstance(obj, dict):

            looks_like_listing = (
                "ItemName" in obj
                or "SaleNo" in obj
                or "LotNo" in obj
            )

            if looks_like_listing:

                if fallback_listing is None:
                    fallback_listing = obj

                status = str(
                    obj.get(
                        "AuctionStatus",
                        ""
                    )
                ).strip().upper()

                if status == "A":

                    active_listing = obj

                    return

            for value in obj.values():

                search(value)

                if active_listing is not None:
                    return

        # ----------------------------------------------------
        # LIST
        # ----------------------------------------------------

        elif isinstance(obj, list):

            for item in obj:

                search(item)

                if active_listing is not None:
                    return

    search(data)

    if active_listing is not None:
        return active_listing

    return fallback_listing


# ============================================================
# CALL GSA API
# ============================================================

def get_one_gsa_listing():

    if not GSA_API_KEY:

        raise RuntimeError(
            "GSA_API_KEY is missing from Render."
        )

    print("")
    print("Calling GSA Auctions API...")
    print("")

    response = requests.get(
        GSA_API_URL,
        params={
            "api_key": GSA_API_KEY,
            "format": "JSON"
        },
        timeout=60
    )

    print(
        "GSA HTTP STATUS:",
        response.status_code
    )

    response.raise_for_status()

    data = response.json()

    listing = find_active_listing(data)

    if listing is None:

        raise RuntimeError(
            "No active GSA listing was found."
        )

    print("Active GSA listing found.")

    return listing


# ============================================================
# MAP GSA FIELDS TO ACTIVE_LISTINGS
# ============================================================

def map_gsa_listing(gsa):

    listing = {

        # ----------------------------------------
        # AucStartDt → start_time
        # ----------------------------------------

        "start_time":
            gsa.get("AucStartDt"),


        # ----------------------------------------
        # AucEndDt → end_time
        # ----------------------------------------

        "end_time":
            gsa.get("AucEndDt"),


        # ----------------------------------------
        # ItemName → title
        # ----------------------------------------

        "title":
            gsa.get("ItemName"),


        # ----------------------------------------
        # PropertyAddr3 → address
        # ----------------------------------------

        "address":
            gsa.get("PropertyAddr3"),


        # ----------------------------------------
        # PropertyCity → city
        # ----------------------------------------

        "city":
            gsa.get("PropertyCity"),


        # ----------------------------------------
        # PropertyState → state
        # ----------------------------------------

        "state":
            gsa.get("PropertyState"),


        # ----------------------------------------
        # PropertyZip → zip_code
        # ----------------------------------------

        "zip_code":
            clean_zip(
                gsa.get("PropertyZip")
            ),


        # ----------------------------------------
        # LotDescript → description
        # ----------------------------------------

        "description":
            gsa.get("LotDescript"),


        # ----------------------------------------
        # ContractOfficer → seller_name
        # ----------------------------------------

        "seller_name":
            gsa.get("ContractOfficer"),


        # ----------------------------------------
        # COEmail → seller_email
        # ----------------------------------------

        "seller_email":
            gsa.get("COEmail"),


        # ----------------------------------------
        # COPhone → seller_phone
        # ----------------------------------------

        "seller_phone":
            gsa.get("COPhone"),


        # ----------------------------------------
        # Reserve → reserve
        # ----------------------------------------

        "reserve":
            clean_number(
                gsa.get("Reserve")
            ),


        # ----------------------------------------
        # AucIncrement → bid_increment
        # ----------------------------------------

        "bid_increment":
            clean_number(
                gsa.get("AucIncrement")
            ),


        # ----------------------------------------
        # ImageURL → photo_url
        # ----------------------------------------

        "photo_url":
            gsa.get("ImageURL")
    }

    return listing


# ============================================================
# PRINT VALUES
# ============================================================

def print_listing(listing):

    print("")
    print("========================================")
    print("GSA LISTING → ACTIVE_LISTINGS")
    print("========================================")

    for key, value in listing.items():

        print(
            f"{key}: {value}"
        )

    print("========================================")
    print("")


# ============================================================
# INSERT INTO active_listings
# ============================================================

def insert_listing(listing):

    with psycopg.connect(DATABASE_URL) as conn:

        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO active_listings (
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
                RETURNING *;
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

            inserted_row = cur.fetchone()

            column_names = [
                description.name
                for description in cur.description
            ]

        conn.commit()

    inserted = dict(
        zip(column_names, inserted_row)
    )

    print("INSERTED INTO active_listings:")
    print(inserted)

    return inserted
    # ============================================================
# COMPLETE IMPORT
# ============================================================

@app.route("/import-one")
def import_one():

    try:

        raw_listing = get_one_gsa_listing()

        listing = map_gsa_listing(
            raw_listing
        )

        print("GSA LISTING:")
        print(listing)

        inserted = insert_listing(
            listing
        )

        # Convert values to strings if Flask can't JSON encode them
        result = {}

        for key, value in inserted.items():

            if value is None:
                result[key] = None

            else:
                result[key] = str(value)

        return jsonify({
            "success": True,
            "message": "ROW INSERTED INTO active_listings",
            "inserted_row": result
        })

    except Exception as error:

        print("IMPORT ERROR:", repr(error))

        return jsonify({
            "success": False,
            "error": str(error)
        }), 500
        # ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def home():

    return jsonify({

        "success": True,

        "message":
            "GSA Auctions importer is running.",

        "database_table":
            "active_listings",

        "import_endpoint":
            "/import-one"

    })


# ============================================================
# IMPORT ONE LISTING
# ============================================================

@app.route("/import-one")
def import_one():

    try:

        listing = import_one_listing()

        # Decimal cannot automatically be JSON encoded
        response_listing = {}

        for key, value in listing.items():

            if isinstance(value, Decimal):

                response_listing[key] = str(value)

            else:

                response_listing[key] = value

        return jsonify({

            "success": True,

            "message":
                "One GSA listing was inserted into active_listings.",

            "listing":
                response_listing

        })

    except Exception as error:

        print("")
        print("========================================")
        print("IMPORT ERROR")
        print(repr(error))
        print("========================================")
        print("")

        return jsonify({

            "success": False,

            "error":
                str(error)

        }), 500


# ============================================================
# COUNT ROWS
# ============================================================

@app.route("/count")
def count_rows():

    try:

        with psycopg.connect(DATABASE_URL) as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT COUNT(*)
                    FROM active_listings;
                """)

                count = cur.fetchone()[0]

        return jsonify({

            "success": True,

            "table":
                "active_listings",

            "row_count":
                count

        })

    except Exception as error:

        return jsonify({

            "success": False,

            "error":
                str(error)

        }), 500


# ============================================================
# SHOW LAST 5 LISTINGS
# ============================================================

@app.route("/recent")
def recent():

    try:

        with psycopg.connect(DATABASE_URL) as conn:

            with conn.cursor() as cur:

                cur.execute("""
                    SELECT
                        title,
                        city,
                        state,
                        end_time
                    FROM active_listings
                    ORDER BY end_time DESC
                    LIMIT 5;
                """)

                rows = cur.fetchall()

        results = []

        for row in rows:

            results.append({

                "title":
                    row[0],

                "city":
                    row[1],

                "state":
                    row[2],

                "end_time":
                    str(row[3])
                    if row[3] is not None
                    else None

            })

        return jsonify({

            "success": True,

            "results":
                results

        })

    except Exception as error:

        return jsonify({

            "success": False,

            "error":
                str(error)

        }), 500


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
