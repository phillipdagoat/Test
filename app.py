import os
import psycopg
from flask import Flask, jsonify

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


@app.route("/")
def home():
    return jsonify({
        "success": True,
        "message": "Render Flask app is running"
    })


@app.route("/test-db")
def test_db():
    try:

        if not DATABASE_URL:
            return jsonify({
                "success": False,
                "error": "DATABASE_URL is not set in Render"
            }), 500

        with psycopg.connect(DATABASE_URL) as conn:

            with conn.cursor() as cur:

                # Create a completely separate test table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS render_test (
                        id BIGSERIAL PRIMARY KEY,
                        message TEXT
                    );
                """)

                # Actually create a row
                cur.execute("""
                    INSERT INTO render_test (message)
                    VALUES (%s)
                    RETURNING id;
                """, (
                    "Render successfully inserted this row into Neon",
                ))

                new_id = cur.fetchone()[0]

            conn.commit()

        return jsonify({
            "success": True,
            "message": "ROW CREATED IN NEON",
            "id": new_id
        })

    except Exception as e:

        print("DATABASE ERROR:", repr(e))

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
