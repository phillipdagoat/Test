from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>My Website</title>
        <style>
            html, body {
                margin: 0;
                width: 100%;
                height: 100%;
                background-color: red;
            }
        </style>
    </head>
    <body>
    </body>
    </html>
    """
