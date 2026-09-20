#!/usr/bin/env python3
"""
Run locally, ONCE, to validate a Hevy auth token and print it for pasting
into the Lambda console's environment variable. Nothing is uploaded
anywhere by this script -- you copy/paste the value yourself.

Hevy's login endpoint (api.hevyapp.com/login) is now protected by Google
reCAPTCHA Enterprise, so it can't be driven from a plain script -- that's
bot-detection, and working around it isn't something this project does,
even for your own account. Instead, get the token by logging in normally
yourself (solving the CAPTCHA as a human) and copying it out of your
browser's DevTools:

  1. Open https://hevy.com/login in Chrome/Firefox/Edge
  2. Open DevTools (F12) > Network tab, and filter for "login"
  3. Log in with your normal Hevy email/password (or set one via
     "Forgot Password" first, if you normally use "Sign in with Google")
  4. Click the POST request to "login" in the Network tab > Response tab
  5. Copy the "auth_token" value (a UUID-formatted string) and paste it
     below when prompted

This script then verifies the token actually works (by calling Hevy's
/account endpoint) before telling you to use it, and saves it locally to
hevy_tokens.json (which .gitignore already excludes).

No known expiry for the token, but if HEVY_AUTH_TOKEN starts getting 401s
in CloudWatch, just repeat the steps above for a fresh one.

Usage:
    uv run setup_hevy_token.py
"""
import json

import requests

TOKEN_FILE = "./hevy_tokens.json"
ACCOUNT_URL = "https://api.hevyapp.com/account"
# Client key captured from Hevy's own web app -- see README.md if this
# starts getting rejected.
WEB_API_KEY = "shelobs_hevy_web"


def main():
    print(__doc__)
    auth_token = input("Paste your auth_token: ").strip()

    resp = requests.get(
        ACCOUNT_URL,
        headers={"auth-token": auth_token, "x-api-key": WEB_API_KEY},
        timeout=15,
    )
    if not resp.ok:
        print(f"\nToken check failed: HTTP {resp.status_code} {resp.reason}")
        print(f"Body: {resp.text!r}")
        resp.raise_for_status()

    account = resp.json()
    print(f"\nToken works -- logged in as {account.get('username')!r}.")

    with open(TOKEN_FILE, "w") as f:
        json.dump({"auth_token": auth_token}, f)

    print("\nIn the Lambda console, under Configuration > Environment variables,")
    print("add this (paste just the token, no quotes):\n")
    print("--- HEVY_AUTH_TOKEN ---")
    print(auth_token)


if __name__ == "__main__":
    main()
