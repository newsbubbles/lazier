# lazier — free media sources (2026-06-30)

From live research (verified June 30, 2026). Goal was "as free as possible." Two findings change the design; they're at the bottom.

## Wire order (all free)

### Tier 1 — wire first (clean API, commercial-safe, attribution-light)

1. **Pexels** (video + image) — one key, 200 req/hr + 20k/mo, keyword search → direct `.mp4`/`.jpg` URLs. Pexels License: commercial/monetized OK, attribution optional. Best single integration. https://www.pexels.com/api/documentation/
2. **Pixabay** (video + image) — free key, 100 req/60s, no attribution, commercial OK. Two rules: **cache responses 24h** and **download-then-rehost (no permanent hotlinking)** — both fine for a fetch-then-render pipeline. https://pixabay.com/api/docs/

Tier 1 alone covers most generic b-roll + images, fully safe for monetized output.

### Tier 2 — add for coverage

3. **Openverse** (images) — one integration aggregates Flickr + Wikimedia + more CC content. No key needed (higher limits with free OAuth). **Filter to `license=cc0,pdm` for zero-attribution safety**; exclude `nc`/`nd`; CC BY/BY-SA need attribution/share-alike. https://api.openverse.org/v1/
4. **Internet Archive** (video/audio) — free, no key for search (`/services/search/v1/scrape`). Public-domain lane for historical/archival footage. **Per-item license varies — filter on `licenseurl`/rights metadata.** ~60 req/min, back off on 429 (sticky IP block if you ignore it). https://archive.org/developers/

### Tier 3 — situational

5. **Mixkit** (video) — best license (monetized YouTube OK, no attribution, no signup) but **no API, needs a scraper**. Add when we want more polished b-roll and can maintain scraping. https://mixkit.co/license/
6. **Imgflip** (memes) — free tier generates captioned memes from ~100 popular blank templates (`get_memes` + `caption_image`). **Cleanest meme-monetization story since we compose the meme ourselves.** Search across 1M templates is premium ($9.99/mo) — skip it. https://imgflip.com/api
7. **Coverr** (video) — free key but production tier is paid, free tier requires credit, and its license forbids "video editors" from redistributing content (gray zone for a tool literally called lazier). Lower priority. https://coverr.co/license

## Quarantine lane (uncleared third-party IP — prototype only, see toggle below)

- **Giphy** (GIFs) — only viable GIF API now, free beta key (100/hr), but requires "Powered By GIPHY" mark and the GIFs carry uncleared TV/film/celebrity IP. Highest legal-risk lane. https://developers.giphy.com/docs/api/
- **Reddit meme subs** (`r/memes`, `r/dankmemes`) via OAuth/PRAW, ~60-100 req/min free. Also **meme-api.com** (`/gimme/{sub}`, no auth) as a zero-friction proxy. Content is user-uploaded, uncleared copyright.
- **Imgur** — user content, uncleared. Lower priority than Reddit.

## Dead / skip

- **Tenor — DEAD as of today (June 30, 2026).** Google sunset the API; existing integrations break July 1. Do not wire. (Klipy is the advertised drop-in replacement; unverified terms, flag for follow-up if we want a 2nd GIF source.)
- **Pushshift** — gone, don't plan around it.
- **Unsplash** — 50 req/hr demo cap + mandatory hotlink + download-tracking rules clash with a download-then-render pipeline. Pexels/Pixabay first.
- **Videvo, Know Your Meme** — no clean API and/or per-item license ambiguity unsuitable for automated monetized output.

## Scraping vs clean API

- **Clean keyword API → direct URLs:** Pexels, Pixabay, Openverse, Internet Archive, Flickr, Giphy, Imgflip, Reddit, Imgur, meme-api.com.
- **Scraping required:** Mixkit, Videvo, Know Your Meme.

---

## Finding 1: license must be a first-class field, tagged at fetch

Output may be monetized, so the design rule is: **the agent tags every fetched asset with its license at fetch time**, and the `timeline.place_clip` tool enforces a project-level posture before anything lands. This makes license a real field on `MediaAsset` (already in the data model), populated from the source's API response, not an afterthought.

## Finding 2: a per-project "rights posture" toggle, not a hard gate

This squares "memes are great" + "YouTube primary" (both uncleared) with "output is monetized." Rather than moralizing or hard-blocking, the project gets a **rights-posture setting** chosen at creation:

- **`commercial_safe`** — only CC0/PD, Pexels/Pixabay/Mixkit-licensed, or our own Imgflip-generated memes get placed. YouTube/Giphy/Reddit/Imgur are hidden from sourcing.
- **`anything_goes`** — everything is fair game (YouTube clips, memes, GIFs). The UI still **labels each placed asset with its license/quarantine status** so Nate sees exactly what's uncleared and clears rights himself. No silent placement of risky media; it's surfaced, not blocked.

Default is Nate's call. Given his stated "YouTube primary, memes great," default is likely `anything_goes` with clear labels, and `commercial_safe` available for client/published work. This respects the autonomy-don't-gatekeep stance while keeping the legal exposure visible instead of hidden.

## Source enum for `media-search` / `media-fetch` tools

`pexels`, `pixabay`, `openverse`, `internet_archive`, `mixkit` (scraper), `imgflip`, `coverr`, `giphy` (quarantine), `reddit` (quarantine), `imgur` (quarantine), plus `youtube` (separate yt-dlp path) and `pool` (local).
