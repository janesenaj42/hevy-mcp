# hevy-mcp

MCP server exposing your own [Hevy](https://www.hevy.com/) workout data
(recent workouts, workout count, routines, account basics) as tools Claude
can call, hosted as a single AWS Lambda function with a public Function
URL.

No S3, no SSM, no IAM policy authoring -- your Hevy auth token lives only
as a Lambda environment variable (encrypted at rest by Lambda's default
AWS-managed key). Free tier covers personal use (Lambda: 1M requests +
400k GB-s/month; Function URLs: no extra charge).

## Important: this uses Hevy's *private* app API, not their official one

Hevy has an [official public API](https://api.hevyapp.com/docs/), but it's
gated behind a **Hevy Pro** subscription just to get an API key. This
project instead talks to the same undocumented API Hevy's own mobile/web
apps use internally, reverse-engineered and documented by the community,
e.g. [dmzoneill/hevyapp-api](https://github.com/dmzoneill/hevyapp-api).
This is the same tradeoff [garmin-mcp](../garmin-mcp) makes with the
unofficial `garminconnect` library.

Implications:
- It could break without notice if Hevy changes their app's API.
- The `x-api-key` client keys baked into `setup_hevy_token.py` and
  `lambda_function.py` (`shelobs_hevy_web`, `klean_kanteen_insulated`) are
  captured from specific app builds, not a key issued to you -- if Hevy
  ever rotates or checks these more strictly, requests will start
  returning 401/403 and you'd need to re-capture fresh ones (see the
  "How to dissect https calls for yourself" section in the repo linked
  above) and set them via the `HEVY_WEB_CLIENT_KEY`/`HEVY_APP_CLIENT_KEY`
  env vars instead of the built-in defaults.
- Hevy's `/login` endpoint is now protected by Google reCAPTCHA Enterprise
  (added sometime after the 2023 captures the community docs are based
  on), so it can't be driven from a plain script -- `setup_hevy_token.py`
  doesn't attempt to log in for you. Instead, you log in normally
  yourself in a browser and copy the resulting token out of DevTools; see
  step 1 below. Every other endpoint this project calls (workouts,
  routines, account, workout count) is unaffected -- only the login step
  needed a human.
- This is outside Hevy's officially sanctioned integration surface. It
  only ever touches your own account's data, but use it at your own risk.

## Prerequisites

- An AWS account
- [`uv`](https://docs.astral.sh/uv/) -- used to run `setup_hevy_token.py`
  and to build the deployment zip, without needing a system Python/pip
  install or a pre-existing venv

## Setup

1. **Get your token locally**

   Hevy's login is behind reCAPTCHA, so this is a manual, one-time step:

   1. Open https://hevy.com/login in your normal browser
   2. Open DevTools (F12) > Network tab, filter for "login"
   3. Log in with your Hevy email/password (if you normally use "Sign in
      with Google" and have no password, use "Forgot Password" on that
      screen first to set one -- Google sign-in keeps working afterwards)
   4. Click the `login` request in the Network tab > Response tab, and
      copy the `auth_token` value (a UUID-formatted string)

   Then run:
   ```
   uv run setup_hevy_token.py
   ```
   and paste the token when prompted. It verifies the token actually
   works (calling Hevy's `/account` endpoint) and saves it locally to
   `hevy_tokens.json` (which `.gitignore` already excludes). Keep it
   handy -- you'll paste it in step 4 below.

2. **Build the deployment package**
   ```
   bash build.sh
   ```
   Produces `function.zip`, built for Python 3.12 / x86_64 to match the
   Lambda runtime in step 3 -- a mismatch there will fail to import at
   runtime.

3. **Create the Lambda function** (AWS Console > Lambda > Create function)
   - Author from scratch, name it `hevy-mcp`
   - Runtime: Python 3.12, Architecture: x86_64
   - Leave "Create a new role with basic Lambda permissions" selected
   - After it's created: Code > Upload from > .zip file > `function.zip`
   - Runtime settings > Handler: `lambda_function.handler`
   - Configuration > General configuration > Timeout: 30 sec

4. **Set environment variables** (Configuration > Environment variables)
   - `HEVY_AUTH_TOKEN` -- the token printed in step 1
   - `API_KEY` -- any random string, e.g. run `openssl rand -hex 16` locally
     (this is a *separate* secret from Hevy's own auth -- it's what gates
     access to this Lambda's Function URL, see step 5)

5. **Turn on a Function URL** (Configuration > Function URL > Create)
   - Auth type: `NONE`
   - Copy the URL it gives you, e.g. `https://abc123.lambda-url.us-east-1.on.aws/`

6. **Add the `ALLOWED_HOST` environment variable**
   - Back in Configuration > Environment variables, add `ALLOWED_HOST` set to
     just the hostname from step 5's URL (no `https://`, no trailing slash),
     e.g. `abc123.lambda-url.us-east-1.on.aws`
   - FastMCP rejects any request whose `Host` header isn't on this list (DNS
     rebinding protection) -- it's a second layer on top of the `X-Api-Key`
     header check, not a replacement for it.

7. **Test it before wiring it into Claude**
   ```
   curl -s -X POST "https://<your-function-url>mcp" \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -H "X-Api-Key: <your-API_KEY>" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
   ```
   Expect a JSON-RPC response listing 4 tools. If you get `401`, the
   `X-Api-Key` header doesn't match the `API_KEY` env var. If you get
   `421`, the `ALLOWED_HOST` value doesn't match your Function URL's
   hostname. If you get a 5xx or timeout, check **Monitor > View CloudWatch
   logs** on the Lambda console -- a 401 from Hevy itself there means
   `HEVY_AUTH_TOKEN` expired or the client keys got rejected (see the
   caveats above).

8. **Connect it to Claude**
   - claude.ai > Settings > Connectors > Add custom connector
   - URL: `<function-url>mcp` (your Function URL + `mcp`, e.g.
     `https://abc123.lambda-url.us-east-1.on.aws/mcp`) -- no secret in the
     URL itself
   - **Authentication: select "No sign-in"** ("for servers that use an API
     key instead of OAuth"). Claude auto-detects "Sign in now" by default
     for any server that returns a 401 to an unauthenticated probe, and in
     that mode Request headers are sent *alongside* an OAuth handshake, not
     instead of it -- this server has no OAuth support at all, so it'll
     fail to connect until you switch this.
   - Under **Request headers**, add: name `X-Api-Key`, value
     `<your-API_KEY>` (not `Authorization` -- Claude blocks that name as
     reserved for OAuth)
   - Add

The Hevy auth token's lifetime isn't documented; if it ever stops working
(401s in CloudWatch logs), re-run `setup_hevy_token.py` and update
`HEVY_AUTH_TOKEN`.

## Tools

- `get_workouts(limit=10)` -- most recent logged workouts, with exercises
  and sets, newest first
- `get_workout_count()` -- total workouts ever logged
- `get_routines()` -- saved routines (planned exercises/sets)
- `get_account_info()` -- username, follower/following counts, last
  workout timestamp
