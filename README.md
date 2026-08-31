# Finnkino schedule 

Static HTML page showing Finnkino showtimes across all theaters for today and the next two days. Generated every 30 minutes and served via GitHub Pages — no server needed.

https://tmu-k.github.io/finnkino-schedule/

Disclaimer: This is an unofficial personal project with no affiliation to Finnkino.

## How it works

1. An Unraid User Scripts cron job (`*/30 * * * *`) triggers the GitHub Actions workflow via the GitHub API
2. GitHub Actions runs `generate.py` on a **self-hosted runner**
3. The script fetches a JWT token embedded in the Finnkino website HTML
4. Uses the token to pull showtimes from `digital-api.finnkino.fi` for all 17 theaters
5. Renders a self-contained `index.html` with 3 days of data baked in as JSON
6. Commits the file back to the repo; GitHub Pages serves it

The page has a date picker (Tänään / Huomenna / Ylihuomenna) and dropdowns for filtering by theater and movie. It defaults to the first day that still has upcoming shows.

## Why a self-hosted runner?

Finnkino's site is behind Cloudflare, which hard-blocks GitHub's hosted runner IPs (Azure datacenters). A self-hosted runner on a home server bypasses this since it has a residential IP.

The runner is a Docker container (`myoung34/github-runner`) running on an Unraid server.

## Why trigger from Unraid instead of GitHub's cron?

GitHub Actions' built-in scheduler can be unreliable — it sometimes stops firing after a force push or repository history rewrite. Triggering via `workflow_dispatch` from an external cron is more dependable.

The Unraid User Scripts cron runs this every 30 minutes:

```bash
curl -s -X POST \
  -H "Authorization: token YOUR_PAT" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/tmu-k/finnkino-schedule/actions/workflows/generate.yml/dispatches \
  -d '{"ref":"main"}'
```

The PAT needs **Actions: Read and write** permission on the repository.

## Local usage

Needs `curl_cffi` (see `requirements.txt`) to match Chrome's TLS fingerprint —
without it Cloudflare challenges most requests. It is optional: the script falls
back to `urllib` if the package is missing.

```bash
pip install -r requirements.txt
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
| `EPHEMERAL` | `true` |

`EPHEMERAL=true` makes the runner deregister and exit after every job, so each run starts from a fresh registration. Without it, an interrupted deregistration (e.g. during a GitHub Actions outage) can leave a half-written config in `/actions-runner` — which is not on a persistent volume, so a container restart won't clear it and only a remove-and-recreate recovers.

This requires a Docker restart policy, since the container exits after each job. On Unraid, set **Extra Parameters** (Advanced View) to `--restart=unless-stopped` — the Autostart toggle only covers array start and is not a restart policy.

## GitHub Pages setup

1. Push this repo to GitHub
2. Go to **Settings → Pages**
3. Set source to **Deploy from a branch**, branch `main`, folder `/root`
4. The page will be live at `https://<user>.github.io/<repo>/`

Trigger the first run manually via **Actions → Generate Finnkino schedule → Run workflow**.
