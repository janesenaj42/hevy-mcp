#!/usr/bin/env python3
"""
Run locally, ONCE, to authenticate with Hevy (email + password, the same
credentials as the Hevy app) and print the auth token you paste into the
Lambda console's environment variable. Nothing is uploaded anywhere by this
script -- you copy/paste the value yourself.

This talks to Hevy's private, undocumented app API (not the official
Pro-only public API at api.hevyapp.com/docs), since that one requires a
Hevy Pro subscription to even get an API key. It works with a normal
(free) Hevy account, but it's reverse-engineered from the mobile app and
could break if Hevy changes it -- see README.md.

No known expiry for the resulting token, but if HEVY_AUTH_TOKEN starts
getting 401s in CloudWatch, just re-run this script and update the env var.

Usage:
    pip install requests
    python setup_hevy_token.py
"""
import getpass
import json

import requests

TOKEN_FILE = "./hevy_tokens.json"
LOGIN_URL = "https://api.hevyapp.com/login"
# Client key captured from Hevy's own web app login flow -- see README.md
# if this starts getting rejected.
WEB_API_KEY = "shelobs_hevy_web"


def main():
    email = input("Hevy email or username: ")
    password = getpass.getpass("Hevy password: ")

    resp = requests.post(
        LOGIN_URL,
        headers={"Content-Type": "application/json", "x-api-key": WEB_API_KEY},
        json={"emailOrUsername": email, "password": password},
        timeout=15,
    )
    resp.raise_for_status()
    auth_token = resp.json()["auth_token"]

    with open(TOKEN_FILE, "w") as f:
        json.dump({"auth_token": auth_token}, f)

    print("\nIn the Lambda console, under Configuration > Environment variables,")
    print("add this (paste just the token, no quotes):\n")
    print("--- HEVY_AUTH_TOKEN ---")
    print(auth_token)


if __name__ == "__main__":
    main()
