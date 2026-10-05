import os
import psycopg


DATABASE_URL = os.getenv("DATABASE_URL")


def insert_active_listing(listing: dict):
    """
    Inserts one listing into the active_listings table.

    If the auction_id + lot_id already exists,
    the existing row is updated.
    """

    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set.")

    required_fields = [
        "auction_id",
        "lot_id",
        "title",
        "description",
        "current_bid",
        "start_time",
        "end_time",
        "city",
        "address",
        "zip_code",
        "seller_name",
        "seller_email",
        "seller_phone",
        "reserve",
        "bid_increment",
    ]

    missing_fields = [
        field for field in required_fields
        if field not in listing
    ]

    if missing_fields:
        raise ValueError(
            f"Listing is missing fields: {missing_fields}"
        )

    query = """
        INSERT INTO active_listings (
            auction_id,
            lot_id,
            title,
            description,
            current_bid,
            start_time,
            end_time,
            city,
            address,
            zip_code,
            seller_name,
            seller_email,
            seller_phone,
            reserve,
            bid_increment
        )
        VALUES (
            %(auction_id)s,
            %(lot_id)s,
            %(title)s,
            %(description)s,
            %(current_bid)s,
            %(start_time)s,
            %(end_time)s,
            %(city)s,
            %(address)s,
            %(zip_code)s,
            %(seller_name)s,
            %(seller_email)s,
            %(seller_phone)s,
            %(reserve)s,
            %(bid_increment)s
        )

        ON CONFLICT (auction_id, lot_id)

        DO UPDATE SET
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            current_bid = EXCLUDED.current_bid,
            start_time = EXCLUDED.start_time,
            end_time = EXCLUDED.end_time,
            city = EXCLUDED.city,
            address = EXCLUDED.address,
            zip_code = EXCLUDED.zip_code,
            seller_name = EXCLUDED.seller_name,
            seller_email = EXCLUDED.seller_email,
            seller_phone = EXCLUDED.seller_phone,
            reserve = EXCLUDED.reserve,
            bid_increment = EXCLUDED.bid_increment

        RETURNING auction_id, lot_id;
    """

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, listing)

            inserted_listing = cursor.fetchone()

    return inserted_listing
