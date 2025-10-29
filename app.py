from flask import Flask, send_from_directory
import os


app = Flask(__name__)


@app.route("/")
def serve_index():
    project_root_directory = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(project_root_directory, "index.html")


@app.route("/script.js")
def serve_script():
    project_root_directory = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(project_root_directory, "script.js")


@app.route("/style.css")
def serve_style():
    project_root_directory = os.path.dirname(os.path.abspath(__file__))
    return send_from_directory(project_root_directory, "style.css")


@app.route("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    debug_mode = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)


