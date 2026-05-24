# Finnkino schedule 

Static HTML page showing Finnkino showtimes across all theaters for today and the next two days. Generated hourly and served via GitHub Pages — no server needed.

https://tmu-k.github.io/finnkino-schedule/

## How it works

1. A GitHub Actions cron job runs `generate.py` every hour on a **self-hosted runner**
2. The script fetches a JWT token embedded in the Finnkino website HTML
3. Uses the token to pull showtimes from `digital-api.finnkino.fi` for all 17 theaters
4. Renders a self-contained `index.html` with 3 days of data baked in as JSON
5. Commits the file back to the repo; GitHub Pages serves it

The page has a date picker (Tänään / Huomenna / Ylihuomenna) and dropdowns for filtering by theater and movie. It defaults to the first day that still has upcoming shows.

## Why a self-hosted runner?

Finnkino's site is behind Cloudflare, which hard-blocks GitHub's hosted runner IPs (Azure datacenters). A self-hosted runner on a home server bypasses this since it has a residential IP.

The runner is a Docker container (`myoung34/github-runner`) running on an Unraid server.

## Local usage

No dependencies — stdlib only.

```bash
python3 generate.py
xdg-open index.html   # or just open the file in your browser
```

## Self-hosted runner setup (Unraid)

Add a Docker container with image `myoung34/github-runner:latest` and these environment variables:

| Variable | Value |
|---|---|
| `REPO_URL` | `https://github.com/tmu-k/finnkino-schedule` |
| `RUNNER_SCOPE` | `repo` |
| `ACCESS_TOKEN` | GitHub PAT with `repo` scope |
| `RUNNER_NAME` | `unraid` (or anything) |
| `LABELS` | `self-hosted` |
| `RUNNER_WORKDIR` | `/tmp/github-runner` |

## GitHub Pages setup

1. Push this repo to GitHub
2. Go to **Settings → Pages**
3. Set source to **Deploy from a branch**, branch `main`, folder `/root`
4. The page will be live at `https://<user>.github.io/<repo>/`

Trigger the first run manually via **Actions → Generate Finnkino schedule → Run workflow**.
