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
# A bare Content-Type + x-api-key gets a blank 400, apparently filtered
# upstream of Hevy's own login logic (a WAF/Cloudflare fingerprint check,
# most likely) -- these extra headers mimic a real browser hitting
# hevy.com's login form closely enough to get through.
BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Content-Type": "application/json",
    "DNT": "1",
    "Origin": "https://www.hevy.com",
    "Pragma": "no-cache",
    "Referer": "https://www.hevy.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Google Chrome";v="111", "Not(A:Brand";v="8", "Chromium";v="111"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "x-api-key": WEB_API_KEY,
}


def main():
    email = input("Hevy email or username: ")
    password = getpass.getpass("Hevy password: ")

    resp = requests.post(
        LOGIN_URL,
        headers=BROWSER_HEADERS,
        json={"emailOrUsername": email, "password": password},
        timeout=15,
    )
    if not resp.ok:
        print(f"\nLogin failed: HTTP {resp.status_code}")
        print(resp.text)
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
