import os
from decimal import Decimal, InvalidOperation

import requests
import psycopg
from psycopg.rows import dict_row
from flask import Flask, jsonify

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
GSA_API_KEY = os.environ.get("GSA_API_KEY")

GSA_API_URL = "https://api.gsa.gov/assets/gsaauctions/v2/auctions"
TABLE_NAME = "active_listings"

EXPECTED_COLUMNS = [
    "start_time",
    "end_time",
    "title",
    "address",
    "city",
    "state",
    "zip_code",
    "description",
    "seller_name",
    "seller_email",
    "seller_phone",
    "reserve",
    "bid_increment",
    "photo_url",
]


def clean_number(value):
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    text = text.replace("$", "").replace(",", "")

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def clean_zip(value):
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    if text.isdigit() and len(text) < 5:
        text = text.zfill(5)

    return text


def require_database_url():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing from Render Environment Variables."
        )


def get_table_schema(conn):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            '''
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                is_identity
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position;
            ''',
            (TABLE_NAME,),
        )

        return cur.fetchall()


def validate_active_listings_table(conn):
    schema = get_table_schema(conn)

    if not schema:
        raise RuntimeError(
            "Table 'active_listings' was not found in the public schema "
            "of the Neon database Render is connected to."
        )

    existing_columns = {row["column_name"] for row in schema}

    missing = [
        column
        for column in EXPECTED_COLUMNS
        if column not in existing_columns
    ]

    if missing:
        raise RuntimeError(
            "active_listings is missing these required columns: "
            + ", ".join(missing)
        )

    extra_required = []

    for row in schema:
        column = row["column_name"]

        if column in EXPECTED_COLUMNS:
            continue

        nullable = row["is_nullable"] == "YES"
        has_default = row["column_default"] is not None
        is_identity = row["is_identity"] == "YES"

        if not nullable and not has_default and not is_identity:
            extra_required.append(column)

    if extra_required:
        raise RuntimeError(
            "active_listings has additional NOT NULL columns with no default: "
            + ", ".join(extra_required)
            + ". Those columns must either get a default/identity value "
              "or be added to the importer."
        )

    return schema


def looks_like_gsa_listing(obj):
    return (
        isinstance(obj, dict)
        and "ItemName" in obj
        and ("SaleNo" in obj or "LotNo" in obj)
    )


def find_one_active_listing(obj):
    if isinstance(obj, dict):
        if looks_like_gsa_listing(obj):
            status = str(obj.get("AuctionStatus", "")).strip().upper()

            if status == "A":
                return obj

        for value in obj.values():
            found = find_one_active_listing(value)

            if found is not None:
                return found

    elif isinstance(obj, list):
        for item in obj:
            found = find_one_active_listing(item)

            if found is not None:
                return found

    return None


def get_one_gsa_listing():
    if not GSA_API_KEY:
        raise RuntimeError(
            "GSA_API_KEY is missing from Render Environment Variables."
        )

    print("Calling GSA Auctions API...", flush=True)

    response = requests.get(
        GSA_API_URL,
        params={
            "api_key": GSA_API_KEY,
            "format": "JSON",
        },
        timeout=60,
        allow_redirects=True,
    )

    print("GSA status:", response.status_code, flush=True)
    print("GSA final URL:", response.url, flush=True)

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "GSA responded, but the response was not valid JSON."
        ) from exc

    listing = find_one_active_listing(data)

    if listing is None:
        raise RuntimeError(
            "The GSA response contained no listing with AuctionStatus='A'."
        )

    return listing


def map_gsa_listing(gsa):
    return {
        "start_time": gsa.get("AucStartDt"),
        "end_time": gsa.get("AucEndDt"),
        "title": gsa.get("ItemName"),
        "address": gsa.get("PropertyAddr3"),
        "city": gsa.get("PropertyCity"),
        "state": gsa.get("PropertyState"),
        "zip_code": clean_zip(gsa.get("PropertyZip")),
        "description": gsa.get("LotDescript"),
        "seller_name": gsa.get("ContractOfficer"),
        "seller_email": gsa.get("COEmail"),
        "seller_phone": gsa.get("COPhone"),
        "reserve": clean_number(gsa.get("Reserve")),
        "bid_increment": clean_number(gsa.get("AucIncrement")),
        "photo_url": gsa.get("ImageURL"),
    }


def insert_listing(listing):
    require_database_url()

    with psycopg.connect(DATABASE_URL) as conn:
        validate_active_listings_table(conn)

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                '''
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
                    %(start_time)s,
                    %(end_time)s,
                    %(title)s,
                    %(address)s,
                    %(city)s,
                    %(state)s,
                    %(zip_code)s,
                    %(description)s,
                    %(seller_name)s,
                    %(seller_email)s,
                    %(seller_phone)s,
                    %(reserve)s,
                    %(bid_increment)s,
                    %(photo_url)s
                )
                RETURNING *;
                ''',
                listing,
            )

            inserted_row = cur.fetchone()

        conn.commit()

    if inserted_row is None:
        raise RuntimeError(
            "PostgreSQL did not return the inserted active_listings row."
        )

    return dict(inserted_row)


def json_safe(row):
    safe = {}

    for key, value in row.items():
        if isinstance(value, Decimal):
            safe[key] = str(value)
        elif value is None:
            safe[key] = None
        else:
            safe[key] = str(value)

    return safe


@app.route("/")
def home():
    return jsonify(
        {
            "success": True,
            "message": "GSA -> Neon importer is running.",
            "table": TABLE_NAME,
            "import_one": "/import-one",
            "schema_check": "/schema",
            "count": "/count",
        }
    )


@app.route("/schema")
def schema():
    try:
        require_database_url()

        with psycopg.connect(DATABASE_URL) as conn:
            table_schema = get_table_schema(conn)

        return jsonify(
            {
                "success": True,
                "table": TABLE_NAME,
                "columns": table_schema,
            }
        )

    except Exception as error:
        print("SCHEMA ERROR:", repr(error), flush=True)

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 500


@app.route("/import-one")
def import_one():
    try:
        print("Starting one-listing import...", flush=True)

        raw_listing = get_one_gsa_listing()
        mapped_listing = map_gsa_listing(raw_listing)

        print("Mapped listing:", mapped_listing, flush=True)

        inserted_row = insert_listing(mapped_listing)

        print("INSERT SUCCESS:", inserted_row, flush=True)

        return jsonify(
            {
                "success": True,
                "message": "One GSA listing was inserted into active_listings.",
                "inserted_row": json_safe(inserted_row),
            }
        )

    except Exception as error:
        print("IMPORT ERROR:", repr(error), flush=True)

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 500


@app.route("/count")
def count_rows():
    try:
        require_database_url()

        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM active_listings;"
                )

                count = cur.fetchone()[0]

        return jsonify(
            {
                "success": True,
                "table": TABLE_NAME,
                "row_count": count,
            }
        )

    except Exception as error:
        print("COUNT ERROR:", repr(error), flush=True)

        return jsonify(
            {
                "success": False,
                "error": str(error),
            }
        ), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
    )
