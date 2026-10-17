# YouTube discovery

Discovery lists public YouTube videos as inspiration. It does not download
video, scrape pages, or treat titles as facts. Agent research still has to
check claims before a script uses them.

## Setup

1. In Google Cloud, enable **YouTube Data API v3** on one project.
2. Create an API key restricted to that API, and to your server IPs if you can.
3. Leave `YOUTUBE_API_KEY` empty in git. Set it in `.env` or on the Sources page.
   An env key wins over a stored key.
4. `PROVIDER_MODE=mock` uses fixture videos and never calls YouTube.
   `PROVIDER_MODE=live` calls YouTube only. A missing key is an error, not a
   silent mock result.

The dollar price is $0. YouTube still spends API quota. This app counts its own
daily allowance before each HTTP try, including retries:

- `YOUTUBE_SEARCH_DAILY_ALLOWANCE` default 20
- `YOUTUBE_VIDEOS_DAILY_ALLOWANCE` default 200

Those caps are per key hash, shared by every process on the same database.
They fail closed. Raise them only up to the Cloud project's real quota.

## Modes

- **Popular** (default): `videos.list` chart `mostPopular`. Region defaults to US.
  An optional category is allowed. Search text, lookback, and language are rejected.
- **Recent**: `search.list` ordered by date, then `videos.list` for details.
  Query is required (max 200 characters). Lookback is 1, 7, or 30 days (default 7).
  The page says these are recent references, not a chart.

Page size is 1 to 50 (default 25). A run keeps at most 100 videos and two search
pages. The next page needs an explicit request and the cursor this server issued.
Missing view, like, or comment counts stay empty. They are never stored as zero.

## Retention

Cached titles and counts live at most 30 days. The default is 24 hours
(`YOUTUBE_RETENTION_HOURS`). Rows are deleted, not hidden. Each discovery call
purges old rows. For an idle install:

```bash
uv run python scripts/purge_discovery.py
```

A production stores only platform, video id, canonical watch URL, and
`retrieved_at`. It does not copy the title or the statistics.

## Live smoke (optional, spends quota)

Do not run this in CI.

```bash
PROVIDER_MODE=live uv run python -c "from cineforge.runtime import get_runtime; print(get_runtime().providers.get('youtube').check('tenant_demo'))"
```
