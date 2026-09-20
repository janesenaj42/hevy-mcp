"""
MCP server exposing your own Hevy workout data as tools.
Deploy as a Lambda Function URL; add that URL to Claude as a
custom connector (Settings > Connectors > Add custom connector).

Talks to Hevy's private, undocumented app API (api.hevyapp.com, no /v1
prefix) rather than the official public API (api.hevyapp.com/docs), since
the official one requires a Hevy Pro subscription just to get an API key.
This one works with a normal free account -- see README.md for the
reverse-engineering caveats.
"""
import hmac
import os

import requests
from mangum import Mangum
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

API_KEY = os.environ["API_KEY"]
EXPECTED_API_KEY = API_KEY.encode()
# Bare hostname of your Function URL, e.g. abc123xyz.lambda-url.ap-southeast-2.on.aws
# (no scheme, no path) -- FastMCP rejects any request whose Host header isn't
# on this list as a DNS-rebinding defense. The X-Api-Key header check below
# already gates every request, so this is a second, narrower layer, not the
# only one.
ALLOWED_HOST = os.environ["ALLOWED_HOST"]

# The token setup_hevy_token.py prints from a one-time email/password login.
HEVY_AUTH_TOKEN = os.environ["HEVY_AUTH_TOKEN"]
# Client keys Hevy's own apps send alongside the auth token. Captured from
# the web app (login/account) and the Android app (everything else) --
# these look tied to the client build rather than the user, so they're
# env-var overridable in case Hevy rotates them and this starts 403ing.
HEVY_WEB_CLIENT_KEY = os.environ.get("HEVY_WEB_CLIENT_KEY", "shelobs_hevy_web")
HEVY_APP_CLIENT_KEY = os.environ.get("HEVY_APP_CLIENT_KEY", "klean_kanteen_insulated")

HEVY_BASE_URL = "https://api.hevyapp.com"


def _app_headers() -> dict:
    return {
        "accept": "application/json, text/plain, */*",
        "x-api-key": HEVY_APP_CLIENT_KEY,
        "auth-token": HEVY_AUTH_TOKEN,
        "User-Agent": "okhttp/4.9.3",
    }


def _hevy_get(path: str) -> dict:
    resp = requests.get(f"{HEVY_BASE_URL}{path}", headers=_app_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def _hevy_post(path: str, body: dict) -> dict:
    resp = requests.post(f"{HEVY_BASE_URL}{path}", headers=_app_headers(), json=body, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _trim_sets(sets: list) -> list:
    return [
        {
            "indicator": s.get("indicator"),
            "weightKg": s.get("weight_kg"),
            "reps": s.get("reps"),
            "distanceMeters": s.get("distance_meters"),
            "durationSeconds": s.get("duration_seconds"),
        }
        for s in sets or []
    ]


def _trim_exercise(e: dict) -> dict:
    # Hevy's raw exercise dict carries a title in ~10 languages plus video/
    # thumbnail URLs -- none of that matters for judging what was trained.
    return {
        "title": e.get("title"),
        "muscleGroup": e.get("muscle_group"),
        "otherMuscles": e.get("other_muscles"),
        "equipmentCategory": e.get("equipment_category"),
        "exerciseType": e.get("exercise_type"),
        "supersetId": e.get("superset_id"),
        "restSeconds": e.get("rest_seconds"),
        "sets": _trim_sets(e.get("sets")),
    }


def _trim_workout(w: dict) -> dict:
    return {
        "id": w.get("id"),
        "name": w.get("name"),
        "startTime": w.get("start_time"),
        "endTime": w.get("end_time"),
        "routineId": w.get("routine_id"),
        "nthWorkout": w.get("nth_workout"),
        "estimatedVolumeKg": w.get("estimated_volume_kg"),
        "exercises": [_trim_exercise(e) for e in w.get("exercises") or []],
    }


def _trim_routine(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "title": r.get("title"),
        "folderId": r.get("folder_id"),
        "updatedAt": r.get("updated_at"),
        "exercises": [_trim_exercise(e) for e in r.get("exercises") or []],
    }


def _build_asgi_app():
    # FastMCP's StreamableHTTPSessionManager can only be .run() once per
    # instance -- it's designed for a long-lived server process's lifespan,
    # not a per-request cycle. Mangum, though, drives a fresh ASGI lifespan
    # startup/shutdown pair on every single Lambda invocation, and this
    # module is reused across warm invocations. So a brand-new FastMCP
    # instance (and its session manager) is built fresh per invocation
    # instead of once at import time, to avoid "run() can only be called
    # once per instance" on the second request a warm container handles.
    mcp = FastMCP(
        "hevy",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=[ALLOWED_HOST]),
    )

    @mcp.tool()
    def get_workouts(limit: int = 10) -> list:
        """Most recent logged workouts (name, exercises, sets, volume), newest first."""
        data = _hevy_get("/feed_workouts_paged")
        workouts = sorted(data.get("workouts") or [], key=lambda w: w.get("start_time") or 0, reverse=True)
        return [_trim_workout(w) for w in workouts[:limit]]

    @mcp.tool()
    def get_workout_count() -> dict:
        """Total number of workouts ever logged on the account."""
        data = _hevy_get("/workout_count")
        return {"workoutCount": data.get("workout_count")}

    @mcp.tool()
    def get_routines() -> list:
        """Saved workout routines (planned exercises/sets), as templates for future sessions."""
        data = _hevy_post("/routines_sync_batch", {})
        return [_trim_routine(r) for r in data.get("updated") or []]

    @mcp.tool()
    def get_account_info() -> dict:
        """Account profile basics: username, follower/following counts, and last workout timestamp."""
        resp = requests.get(
            f"{HEVY_BASE_URL}/account",
            headers={"auth-token": HEVY_AUTH_TOKEN, "x-api-key": HEVY_WEB_CLIENT_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "username": data.get("username"),
            "fullName": data.get("full_name"),
            "followerCount": data.get("follower_count"),
            "followingCount": data.get("following_count"),
            "createdAt": data.get("created_at"),
            "lastWorkoutAt": data.get("last_workout_at"),
        }

    return mcp.streamable_http_app()


_asgi_app = None


async def app(scope, receive, send):
    global _asgi_app
    # Mangum sends one lifespan startup/shutdown pair per invocation, ahead
    # of the actual http scope call below -- rebuild the ASGI app here each
    # time so its session manager is always a fresh, never-yet-run instance.
    if scope["type"] == "lifespan":
        _asgi_app = _build_asgi_app()
        await _asgi_app(scope, receive, send)
        return

    # MCP clients (Claude included) probe OAuth-discovery paths like
    # /.well-known/oauth-authorization-server and /register when adding a
    # connector, to decide whether OAuth is available -- independent of any
    # header-based auth configured for the actual tool-call endpoint. Let
    # these fall through to FastMCP's app (which doesn't define them, so
    # they 404 cleanly) instead of the API-key gate below: a blanket 401
    # here reads as "OAuth is required" and sends the client down a doomed
    # dynamic-client-registration attempt instead of just using X-Api-Key.
    path = scope.get("path", "")
    if path.startswith("/.well-known/") or path == "/register":
        await _asgi_app(scope, receive, send)
        return

    # Shared-secret gate: a Lambda Function URL with auth-type NONE is
    # otherwise reachable by anyone who has the URL. Claude's "Add custom
    # connector" dialog has a Request headers field for exactly this case
    # (an API key instead of OAuth), so the secret travels as a custom
    # header rather than sitting in the URL where it could end up in
    # browser history or incidental logging. Not "Authorization" -- Claude
    # blocks that one as a reserved/OAuth-managed header name.
    got_key = b""
    for name, value in scope.get("headers") or []:
        if name == b"x-api-key":
            got_key = value
            break
    if not hmac.compare_digest(got_key, EXPECTED_API_KEY):
        await send({"type": "http.response.start", "status": 401, "headers": []})
        await send({"type": "http.response.body", "body": b"unauthorized"})
        return
    await _asgi_app(scope, receive, send)


handler = Mangum(app)
