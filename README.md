# price-checker

A local web app for video game resellers to quickly assess deal worthiness. Enter a list of game/console names and get average sold prices broken down by condition — Loose, Box+Disc, CIB, Sealed, and Sealed+Graded — sourced from eBay completed listings.

## Setup

```bash
cp .env.example .env
# Add your RAPIDAPI_KEY to .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

## Docker

```bash
docker compose up --build
```

## Config

| Variable | Default | Description |
|---|---|---|
| `RAPIDAPI_KEY` | required | RapidAPI key for eBay sold items API |
| `EBAY_MAX_RESULTS` | `120` | Listings fetched per query (60/120/240) |
| `CACHE_TTL_HOURS` | `24` | How long results are cached |
| `LOW_DATA_THRESHOLD` | `5` | Min sales before showing aggregated stats |
| `EBAY_CONCURRENCY_LIMIT` | `3` | Max simultaneous eBay API calls |
