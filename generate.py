#!/usr/bin/env python3
"""
Fetches today's Finnkino schedule and writes a self-contained index.html.

Local use:
    python3 generate.py
    xdg-open index.html   # or just open the file in a browser

In CI (GitHub Actions), set TOKEN_WORKER_URL to the Cloudflare Worker URL
as a repository variable (Settings → Variables → Actions → New repository variable).
The Worker lives in cf-worker/ and bypasses Cloudflare's IP-level blocking.
"""
import datetime
import gzip
import json
import os
import re
import urllib.request
from pathlib import Path

# ── constants ───────────────────────────────────────────────────────────[...]

DIGITAL_API = "https://digital-api.finnkino.fi/WSVistaWebClient/ocapi/v1"
CINEMA_PAGE = "https://www.finnkino.fi/teatterit/finnkino-tennispalatsi/"
JWT_RE = re.compile(
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
)
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
# Full browser headers — work from residential IPs (local dev).
# GitHub Actions IPs are blocked by Cloudflare regardless of headers;
# use the CF Worker (TOKEN_WORKER_URL) in CI instead.
BROWSER_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "fi-FI,fi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
ATTR_RE = re.compile(
    r"^\dD$|^(IMAX|4DX|Dolby|ScreenX|D-BOX|LUXE|iSense|HFR|Laser|PLF|annisk)",
    re.I,
)
THEATER_URLS = {
    "Cine Atlas Tampere": "finnkino-cine-atlas",
    "Fantasia Jyväskylä": "finnkino-fantasia",
    "Flamingo Vantaa": "finnkino-flamingo",
    "Itis Helsinki": "finnkino-itis",
    "Kinopalatsi Helsinki": "finnkino-kinopalatsi-helsinki",
    "Kinopalatsi Turku": "finnkino-kinopalatsi-turku",
    "Kuvapalatsi Lahti": "finnkino-kuvapalatsi",
    "LUXE Mylly Raisio": "finnkino-luxe-mylly",
    "Maxim Helsinki": "finnkino-maxim",
    "Omena Espoo": "finnkino-omena",
    "Plaza Oulu": "finnkino-plaza",
    "Plevna Tampere": "finnkino-plevna",
    "Promenadi Pori": "finnkino-promenadi",
    "Scala Kuopio": "finnkino-scala",
    "Sello Espoo": "finnkino-sello",
    "Strand Lappeenranta": "finnkino-strand",
    "Tennispalatsi Helsinki": "finnkino-tennispalatsi",
}


# ── token acquisition ────────────────────────────────────────────────────────

def _token_via_worker(worker_url: str) -> str | None:
    """Call the Cloudflare Worker proxy to get the JWT."""
    req = urllib.request.Request(
        worker_url,
        headers={"Accept": "application/json", "User-Agent": "finnkino-schedule/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
        token = data.get("token", "").strip()
        if token:
            print("[token] acquired via CF Worker")
            return token
        print(f"[token] Worker returned no token: {data}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[token] Worker returned HTTP {e.code}: {body[:500]}")
    except Exception as e:
        print(f"[token] Worker call failed: {e}")
    return None


def _fetch_html(url: str) -> str | None:
    """Direct HTTP fetch — works from residential IPs, blocked in CI."""
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
        try:
            return gzip.decompress(raw).decode("utf-8", errors="replace")
        except Exception:
            return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[token] direct fetch failed: {e}")
        return None


def get_token() -> str:
    """Return a JWT token.

    In CI: calls TOKEN_WORKER_URL (Cloudflare Worker) — set as a GitHub
    repository variable (Settings → Variables → Actions).
    Locally: direct HTTP fetch with browser headers (works on residential IPs).
    """
    worker_url = os.environ.get("TOKEN_WORKER_URL", "").strip()
    if worker_url:
        token = _token_via_worker(worker_url)
        if token:
            return token
        raise RuntimeError("CF Worker failed to return a token — check the Worker logs")

    print("[token] TOKEN_WORKER_URL not set, trying direct HTTP (local dev)…")
    for url in [CINEMA_PAGE, "https://www.finnkino.fi/"]:
        html = _fetch_html(url)
        if html:
            m = JWT_RE.search(html)
            if m:
                print(f"[token] acquired from {url}")
                return m.group(0)
        print(f"[token] no JWT at {url}")

    raise RuntimeError(
        "Could not obtain JWT. In CI, set the TOKEN_WORKER_URL repository variable."
    )


# ── API helpers ──────────────────────────────────────────────────────────[...]

def _api_headers(token: str) -> dict:
    return {
        "authorization": f"Bearer {token}",
        "user-agent": BROWSER_UA,
        "accept": "application/json",
        "referer": "https://www.finnkino.fi/",
    }


def _get_json(url: str, headers: dict) -> dict | list:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_sites(headers: dict) -> list[dict]:
    print("[sites] fetching…")
    data = _get_json(f"{DIGITAL_API}/sites", headers)
    raw = data.get("sites", data) if isinstance(data, dict) else data
    sites = [
        {"id": str(s["id"]), "name": s["name"]["text"]}
        for s in raw
        if s.get("id") and s.get("name", {}).get("text")
    ]
    print(f"[sites] got {len(sites)} cinemas")
    return sites


def fetch_schedule(headers: dict, site_ids: list[str], date: str) -> dict:
    qs = "&".join(f"siteIds={i}" for i in site_ids)
    url = f"{DIGITAL_API}/showtimes/by-business-date/{date}?{qs}"
    print(f"[schedule] fetching {url[:100]}…")
    data = _get_json(url, headers)
    count = len(data.get("showtimes", [])) if isinstance(data, dict) else "?"
    print(f"[schedule] got {count} showtimes")
    return data if isinstance(data, dict) else {}


# ── data parsing ───────────────────────────────────────────────────────────[...]

def _fmt_time(dt_str: str) -> str:
    if not dt_str:
        return ""
    try:
        return datetime.datetime.fromisoformat(dt_str).strftime("%H:%M")
    except ValueError:
        return ""


def parse_shows(data: dict) -> list[dict]:
    showtimes = data.get("showtimes", [])
    rd = data.get("relatedData", {})

    films = {str(f["id"]): f for f in rd.get("films", [])}
    sites = {str(s["id"]): s for s in rd.get("sites", [])}
    screens = {str(s["id"]): s for s in rd.get("screens", [])}
    attrs = {str(a["id"]): a for a in rd.get("attributes", [])}
    ratings = {str(r["id"]): r for r in rd.get("censorRatings", [])}

    shows = []
    for s in showtimes:
        film = films.get(str(s.get("filmId", "")), {})
        site = sites.get(str(s.get("siteId", "")), {})
        screen = screens.get(str(s.get("screenId", "")), {})

        attr_names = " · ".join(
            label
            for aid in (s.get("attributeIds") or [])
            if (
                label := (
                    attrs.get(str(aid), {}).get("shortName", {}).get("text")
                    or attrs.get(str(aid), {}).get("name", {}).get("text")
                    or ""
                )
            )
            and ATTR_RE.match(label)
        )

        rating_id = str(film.get("censorRatingId", ""))
        rating_raw = ratings.get(rating_id, {}).get("classification", {}).get("text", "")
        num_match = re.match(r"^\d+", rating_raw)
        rating = f"K-{num_match.group(0)}" if num_match else rating_raw

        shows.append(
            {
                "start": _fmt_time(s.get("schedule", {}).get("startsAt", "")),
                "end": _fmt_time(s.get("schedule", {}).get("endsAt", "")),
                "title": film.get("title", {}).get("text", "?"),
                "originalTitle": film.get("originalTitle", {}).get("text", ""),
                "theater": site.get("name", {}).get("text", ""),
                "hall": screen.get("name", {}).get("text", ""),
                "attrs": attr_names,
                "rating": rating,
                "siteId": str(s.get("siteId", "")),
                "filmId": str(s.get("filmId", "")),
                "showtimeId": str(s.get("id", "")),
            }
        )

    shows.sort(key=lambda x: x["start"])
    return shows


# ── HTML generation ──────────────────────────────────────────────────────────[...]

def render_html(
    sites: list[dict],
    shows_by_date: dict[str, list[dict]],
    dates: list[str],
    generated_at: datetime.datetime,
) -> str:
    shows_by_date_js = json.dumps(shows_by_date, ensure_ascii=False, separators=(",", ":"))
    dates_js         = json.dumps(dates, ensure_ascii=False)
    sites_js         = json.dumps(sites, ensure_ascii=False, separators=(",", ":"))
    theater_urls_js  = json.dumps(THEATER_URLS, ensure_ascii=False)

    generated_display = (
        f"{generated_at.day}.{generated_at.month}.{generated_at.year} "
        f"klo {generated_at.strftime('%H:%M')}"
    )
    generated_iso = generated_at.isoformat()

    return f"""<!DOCTYPE html>
<html lang="fi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Finnkino näytösajat</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎬</text></svg>">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: #0f0f0f;
      color: #e8e8e8;
      min-height: 100vh;
    }}

    header {{
      padding: 0.75rem 1.5rem;
      border-bottom: 1px solid #222;
      display: flex;
      align-items: center;
      gap: 1rem;
      flex-wrap: wrap;
    }}

    header h1 {{ font-size: 1.1rem; font-weight: 600; letter-spacing: -0.02em; white-space: nowrap; }}
    header h1 span {{ color: #e5ac00; font-weight: 700; }}
    footer {{ padding: 1.25rem 1.5rem; font-size: 0.72rem; color: #555; border-top: 1px solid #1a1a1a; }}

    #stale-warning {{
      display: none;
      padding: 0.6rem 1.5rem;
      background: #2d1f00;
      border-bottom: 1px solid #5a3d00;
      color: #f0c060;
      font-size: 0.8rem;
    }}

    .date-tabs {{
      display: flex;
      gap: 0.375rem;
    }}

    .date-tab {{
      background: none;
      border: 1px solid #333;
      color: #777;
      padding: 0.3rem 0.7rem;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.78rem;
      display: flex;
      flex-direction: column;
      align-items: center;
      line-height: 1.25;
      transition: border-color 0.15s, color 0.15s, background 0.15s;
    }}
    .date-tab:hover {{ border-color: #555; color: #bbb; }}
    .date-tab.active {{
      border-color: #e5ac00;
      color: #e5ac00;
      background: rgba(229,172,0,0.08);
    }}
    .tab-label {{ font-weight: 600; }}
    .tab-sub   {{ font-size: 0.68rem; opacity: 0.75; }}

    .date-tab-more {{
      background: none;
      border: 1px solid #333;
      color: #777;
      padding: 0.3rem 0.5rem;
      border-radius: 6px;
      font-size: 0.78rem;
      cursor: pointer;
    }}
    .date-tab-more:focus {{ outline: none; border-color: #555; }}
    .date-tab-more.active {{ border-color: #e5ac00; color: #e5ac00; background: rgba(229,172,0,0.08); }}

    .filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      padding: 0.75rem 1.5rem;
      border-bottom: 1px solid #222;
      background: #141414;
    }}

    .filters select {{
      background: #1e1e1e;
      border: 1px solid #333;
      color: #e8e8e8;
      padding: 0.375rem 0.625rem;
      border-radius: 6px;
      font-size: 0.8rem;
      min-width: 180px;
    }}
    .filters select:focus {{ outline: none; border-color: #e5ac00; }}

    .show-count {{ padding: 0.6rem 1.5rem; font-size: 0.75rem; color: #555; }}

    .shows-grid {{
      padding: 1rem 1.5rem;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 0.625rem;
    }}

    .show-card {{
      background: #1a1a1a;
      border: 1px solid #2a2a2a;
      border-radius: 8px;
      padding: 0.625rem 0.875rem;
      display: flex;
      flex-direction: column;
      gap: 0.3rem;
      transition: border-color 0.15s;
    }}
    .show-card:hover {{ border-color: #444; }}

    .show-time {{ font-size: 1.1rem; font-weight: 700; color: #fff; letter-spacing: -0.03em; }}
    .show-time .end {{ font-size: 0.8rem; font-weight: 400; color: #666; margin-left: 0.35rem; }}
    .show-title {{ font-size: 0.875rem; font-weight: 600; color: #f0f0f0; line-height: 1.3; }}
    .show-title a {{ color: inherit; text-decoration: none; }}
    .show-title a:hover {{ color: #e5ac00; }}
    .show-orig {{ font-size: 0.75rem; color: #666; }}
    .show-meta {{ display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.15rem; }}

    .tag {{
      font-size: 0.7rem;
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
      background: #252525;
      color: #aaa;
      border: 1px solid #333;
    }}
    .tag.theater {{ color: #7eb8f7; border-color: #2a4a6a; background: #1a2d40; }}
    .tag.theater a {{ color: inherit; text-decoration: none; }}
    .tag.theater a:hover {{ color: #e5ac00; }}
    .tag.hall   {{ color: #9e9e9e; }}
    .tag.attr   {{ color: #a0e0a0; border-color: #2a4a2a; background: #1a2d1a; }}
    .tag.rating {{ color: #f0c060; border-color: #4a3a1a; background: #2d2010; }}

    #empty {{
      padding: 2rem 1.5rem;
      color: #555;
      font-size: 0.875rem;
    }}

    @media (max-width: 600px) {{
      header, .filters, .shows-grid, .show-count, #empty {{ padding-left: 1rem; padding-right: 1rem; }}
      .shows-grid {{ grid-template-columns: 1fr; }}
      footer {{ padding-left: 1rem; padding-right: 1rem; }}
    }}

    @media (max-width: 390px) {{
      header, .filters, .shows-grid, .show-count, #empty, footer {{ padding-left: 0.5rem; padding-right: 0.5rem; }}
      header {{ gap: 0.5rem; }}
      .date-tab {{ padding: 0.25rem 0.45rem; }}
      .date-tab-more {{ padding: 0.25rem 0.35rem; }}
    }}
  </style>
</head>
<body>

<header>
  <h1><span>Finnkino</span> näytösajat</h1>
  <div class="date-tabs" id="date-tabs"></div>
</header>

<div id="stale-warning"></div>

<div class="filters">
  <select id="theater-select"><option value="">Kaikki teatterit</option></select>
  <select id="movie-select"><option value="">Kaikki elokuvat</option></select>
</div>

<div class="show-count" id="show-count"></div>
<div class="shows-grid" id="shows-grid"></div>
<div id="empty" hidden>Ei näytöksiä valittuna päivänä.</div>
<footer>Päivitetty {generated_display}</footer>

<script>
const SHOWS_BY_DATE = {shows_by_date_js};
const DATES         = {dates_js};
const SITES         = {sites_js};
const THEATER_URLS  = {theater_urls_js};

const DAY_LABELS = ['Tänään', 'Huomenna', 'Ylihuomenna'];
const FI_WEEKDAYS = ['su','ma','ti','ke','to','pe','la'];

const tabsEl        = document.getElementById('date-tabs');
const theaterSelect = document.getElementById('theater-select');
const movieSelect   = document.getElementById('movie-select');
const showsGrid     = document.getElementById('shows-grid');
const showCount     = document.getElementById('show-count');
const emptyEl       = document.getElementById('empty');

// Default to first date that has shows; fall back to today
let activeDate = DATES.find(d => SHOWS_BY_DATE[d].length > 0) || DATES[0];

// Build date-tab buttons for first 3 days, date picker for the rest
DATES.slice(0, 3).forEach((d, i) => {{
  const [y, m, day] = d.split('-').map(Number);
  const weekday = FI_WEEKDAYS[new Date(y, m - 1, day).getDay()];
  const btn = document.createElement('button');
  btn.className = 'date-tab' + (d === activeDate ? ' active' : '');
  btn.dataset.date = d;
  btn.innerHTML = `<span class="tab-label">${{DAY_LABELS[i]}}</span>`
                + `<span class="tab-sub">${{weekday}} ${{day}}.${{m}}.</span>`;
  btn.addEventListener('click', () => {{ activeDate = d; extraDateSel.value = ''; update(); }});
  tabsEl.appendChild(btn);
}});

// Extra date picker for days 3–6 that have shows
const extraDates = DATES.slice(3).filter(d => SHOWS_BY_DATE[d].length > 0);
const extraDateSel = document.createElement('select');
extraDateSel.className = 'date-tab-more' + (extraDates.includes(activeDate) ? ' active' : '');
extraDateSel.innerHTML = '<option value="">···</option>';
extraDates.forEach(d => {{
  const [y, m, day] = d.split('-').map(Number);
  const weekday = FI_WEEKDAYS[new Date(y, m - 1, day).getDay()];
  const o = document.createElement('option');
  o.value = d;
  o.textContent = `${{weekday}} ${{day}}.${{m}}.`;
  if (d === activeDate) o.selected = true;
  extraDateSel.appendChild(o);
}});
extraDateSel.addEventListener('change', () => {{
  if (!extraDateSel.value) return;
  activeDate = extraDateSel.value;
  update();
}});
if (extraDates.length) tabsEl.appendChild(extraDateSel);

// Theater groups — selectable at the top of the dropdown
const THEATER_GROUPS = [
  {{ label: 'Pääkaupunkiseudun ohjelmisto', names: ['Flamingo Vantaa','Itis Helsinki','Kinopalatsi Helsinki','Maxim Helsinki','Omena Espoo','Sello Espoo','Tennispalatsi Helsinki'] }},
  {{ label: 'Tampereen ohjelmisto',         names: ['Cine Atlas Tampere','Plevna Tampere'] }},
  {{ label: 'Turun ja Raision ohjelmisto',  names: ['Kinopalatsi Turku','LUXE Mylly Raisio'] }},
];
const allSiteIds   = new Set(DATES.flatMap(d => SHOWS_BY_DATE[d].map(s => s.siteId)));
const availSites   = SITES.filter(s => allSiteIds.has(s.id));
const nameToId     = Object.fromEntries(availSites.map(s => [s.name, s.id]));
const groupedNames = new Set(THEATER_GROUPS.flatMap(g => g.names));

// Group options at the top
const ogGroups = document.createElement('optgroup');
ogGroups.label = 'Alueet';
THEATER_GROUPS.forEach(group => {{
  const memberIds = group.names.map(n => nameToId[n]).filter(Boolean);
  if (!memberIds.length) return;
  const o = document.createElement('option');
  o.value = 'g:' + group.label;
  o.textContent = group.label;
  o.dataset.siteids = memberIds.join(',');
  ogGroups.appendChild(o);
}});
theaterSelect.appendChild(ogGroups);

// Individual theaters below
const ogSingle = document.createElement('optgroup');
ogSingle.label = 'Teatterit';
availSites.sort((a, b) => a.name.localeCompare(b.name, 'fi')).forEach(s => {{
  const o = document.createElement('option');
  o.value = s.id; o.textContent = s.name;
  ogSingle.appendChild(o);
}});
theaterSelect.appendChild(ogSingle);

// Returns a Set of siteIds for the current selection, or null for "all"
function getFilterIds() {{
  const val = theaterSelect.value;
  if (!val) return null;
  if (val.startsWith('g:')) {{
    const ids = theaterSelect.options[theaterSelect.selectedIndex].dataset.siteids.split(',');
    return new Set(ids);
  }}
  return new Set([val]);
}}

function theaterUrl(name) {{
  const slug = THEATER_URLS[name];
  return slug ? `https://www.finnkino.fi/teatterit/${{slug}}/` : null;
}}

function updateTabs() {{
  tabsEl.querySelectorAll('.date-tab').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.date === activeDate)
  );
  const isExtra = extraDates.includes(activeDate);
  extraDateSel.classList.toggle('active', isExtra);
  if (!isExtra) extraDateSel.value = '';
}}

function updateMovieDropdown() {{
  const ids     = getFilterIds();
  const shows   = SHOWS_BY_DATE[activeDate];
  const visible = ids ? shows.filter(s => ids.has(s.siteId)) : shows;
  const prev    = movieSelect.value;
  const titles  = [...new Set(visible.map(s => s.title))].sort((a, b) => a.localeCompare(b, 'fi'));
  movieSelect.innerHTML = '<option value="">Kaikki elokuvat</option>';
  titles.forEach(t => {{
    const o = document.createElement('option');
    o.value = t; o.textContent = t;
    movieSelect.appendChild(o);
  }});
  movieSelect.value = titles.includes(prev) ? prev : '';
}}

function render() {{
  const ids    = getFilterIds();
  const title  = movieSelect.value;
  let filtered = SHOWS_BY_DATE[activeDate];
  if (ids)   filtered = filtered.filter(s => ids.has(s.siteId));
  if (title)  filtered = filtered.filter(s => s.title  === title);

  showsGrid.innerHTML = '';
  if (filtered.length === 0) {{
    showCount.textContent = '';
    emptyEl.hidden = false;
    return;
  }}
  emptyEl.hidden = true;
  showCount.textContent = `${{filtered.length}} näytöstä`;

  filtered.forEach(s => {{
    const url = theaterUrl(s.theater);
    const theaterTag = url
      ? `<a href="${{url}}" target="_blank" rel="noopener">${{s.theater}}</a>`
      : s.theater;
    const card = document.createElement('div');
    card.className = 'show-card';
    card.innerHTML = `
      <div class="show-time">${{s.start}}<span class="end">→ ${{s.end}}</span></div>
      <div class="show-title">${{s.showtimeId
        ? `<a href="https://www.finnkino.fi/liput/valitse-paikat/?showtimeId=${{s.showtimeId}}" target="_blank" rel="noopener">${{s.title}}</a>`
        : s.title}}</div>
      ${{s.originalTitle && s.originalTitle !== s.title
        ? `<div class="show-orig">${{s.originalTitle}}</div>` : ''}}
      <div class="show-meta">
        ${{s.theater ? `<span class="tag theater">${{theaterTag}}</span>` : ''}}
        ${{s.hall    ? `<span class="tag hall">${{s.hall}}</span>` : ''}}
        ${{s.attrs   ? `<span class="tag attr">${{s.attrs}}</span>` : ''}}
        ${{s.rating  ? `<span class="tag rating">${{s.rating}}</span>` : ''}}
      </div>`;
    showsGrid.appendChild(card);
  }});
}}

function update() {{
  updateTabs();
  updateMovieDropdown();
  render();
}}

// Restore saved theater selection
const savedTheater = localStorage.getItem('finnkino-theater');
if (savedTheater) theaterSelect.value = savedTheater;

// Staleness warning
const GENERATED_AT = new Date("{generated_iso}");
const hoursOld = (Date.now() - GENERATED_AT) / 3600000;
if (hoursOld >= 2) {{
  const w = document.getElementById('stale-warning');
  w.textContent = `⚠️ Tiedot saattavat olla vanhentuneita — päivitetty ${{Math.floor(hoursOld)}}h sitten`;
  w.style.display = 'block';
}}

theaterSelect.addEventListener('change', () => {{
  localStorage.setItem('finnkino-theater', theaterSelect.value);
  updateMovieDropdown();
  render();
}});
movieSelect.addEventListener('change', render);

update();
</script>
</body>
</html>"""


# ── main ────────────────────────────────────────────────────────────…[...]

def main() -> None:
    generated_at = datetime.datetime.now().astimezone()

    token = get_token()
    headers = _api_headers(token)

    sites = fetch_sites(headers)
    site_ids = [s["id"] for s in sites]

    # Fetch today + next 6 days so the user can browse the full week.
    today = datetime.date.today()
    dates = [today + datetime.timedelta(days=i) for i in range(10)]
    shows_by_date: dict[str, list[dict]] = {}
    for d in dates:
        raw = fetch_schedule(headers, site_ids, d.isoformat())
        shows_by_date[d.isoformat()] = parse_shows(raw)

    html = render_html(sites, shows_by_date, [d.isoformat() for d in dates], generated_at)

    total = sum(len(v) for v in shows_by_date.values())
    if total == 0:
        raise RuntimeError("No shows fetched across any of the 10 days — Finnkino API may have changed")

    out = Path(__file__).parent / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"[main] wrote {out} ({total} total shows across {len(dates)} days, {out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
