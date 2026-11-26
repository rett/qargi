"""A dummy sign-in file for the tests of a runtime whose members' sign-in is a private copy (dispatch.home.link[].private): a JSON object whose access
token is JWT-shaped and ends in a chosen number of seconds. Every value is made up here; nothing in it is a credential and nothing reads a real file.

  python3 tests/dummy_signin.py [SECONDS]      prints the file (default: ten days of life)
  signin(seconds)                              the same, as text, for a test written in Python
"""
import base64
import json
import sys
import time


def b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def signin(seconds=864000):
    token = "%s.%s.dummy-signature" % (b64({"alg": "none"}), b64({"exp": int(time.time()) + int(seconds), "sub": "dummy"}))
    return json.dumps({"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "last_refresh": "2026-01-01T00:00:00Z",
                       "tokens": {"access_token": token, "id_token": "dummy-id-token", "refresh_token": "dummy-refresh-token", "account_id": "dummy-account"}}, indent=2) + "\n"


if __name__ == "__main__":
    sys.stdout.write(signin(int(sys.argv[1]) if len(sys.argv) > 1 else 864000))
