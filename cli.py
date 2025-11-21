# cli.py
"""Simple CLI client for the image hosting server.
This is what we run from the terminal to test the API."""

import argparse
import json
import os
from pathlib import Path

import requests

# The server URL. On EC2, we still call 127.0.0.1:8000 because it's local to the VM.
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")

# Where we store the API key on the machine running the CLI
AUTH_FILE = Path.home() / ".imagehost_auth.json"


def load_auth():
    """Loads auth info from disk. If you never logged in, this returns None."""
    if not AUTH_FILE.exists():
        return None
    with AUTH_FILE.open() as f:
        return json.load(f)


def save_auth(data):
    """Saves auth info (api_key + uid) so we don't have to log in every time."""
    with AUTH_FILE.open("w") as f:
        json.dump(data, f)
    print(f"saved api key for {data.get('uid')}")


def call_api(path, method="GET", headers=None, params=None, files=None, json_body=None):
    """Tiny wrapper around requests so we don't repeat the base URL logic everywhere."""
    url = BASE_URL.rstrip("/") + path
    headers = headers or {}

    resp = requests.request(method, url, headers=headers, params=params, files=files, json=json_body)

    if not resp.ok:
        print(f"{method} {path} failed: {resp.status_code} {resp.text}")
        raise SystemExit(1)

    return resp.json()



# Commands
# -----------------------------
def cmd_login(args):
    """Asks the server for a dev API key and saves it locally."""
    data = call_api("/api/v1/dev/issue-key", method="POST", json_body={})
    payload = data["data"]
    save_auth({"api_key": payload["api_key"], "uid": payload["uid"]})


def cmd_upload(args):
    """Uploads a single image file."""
    auth = load_auth()
    if not auth:
        print("You need to run 'login' first.")
        raise SystemExit(1)

    api_key = auth["api_key"]

    filepath = Path(args.path)
    if not filepath.exists():
        print(f"File not found: {filepath}")
        raise SystemExit(1)

    # Open file in binary mode and send as multipart form data
    with filepath.open("rb") as f:
        files = {"file": (filepath.name, f)}
        headers = {"X-API-Key": api_key}

        resp = call_api("/api/v1/image/upload", method="POST", headers=headers, files=files)
        payload = resp["data"]
        print(f"uploaded: {filepath.name}")
        print(payload["url"])  # This should be the /api/v1/image/<iid> URL


def cmd_list(args):
    """Lists all images for the current user."""
    auth = load_auth()
    if not auth:
        print("You need to run 'login' first.")
        raise SystemExit(1)

    api_key = auth["api_key"]
    headers = {"X-API-Key": api_key}

    resp = call_api("/api/v1/image/list", method="GET", headers=headers)
    images = resp["data"]["images"]

    if not images:
        print("No images uploaded yet.")
        return

    # Print like a simple table
    for img in images:
        iid = img.get("id", "?")
        filename = img.get("filename", "?")
        mime = img.get("mime", "?")
        url = img.get("url", "?")
        print(f"{iid}\t{filename}\t{mime}\t{url}")


def main():
    parser = argparse.ArgumentParser(description="Image hosting CLI")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    # login
    p_login = subparsers.add_parser("login", help="Get a dev API key")
    p_login.set_defaults(func=cmd_login)

    # upload
    p_upload = subparsers.add_parser("upload", help="Upload an image")
    p_upload.add_argument("path", help="Path to the image file")
    p_upload.set_defaults(func=cmd_upload)

    # list
    p_list = subparsers.add_parser("list", help="List your images")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
