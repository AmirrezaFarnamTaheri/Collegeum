# Architecture

## 1. Goal and constraints

Discover, deduplicate, and broadcast full-time **pre-doctoral** research
assistantships, fellowships, and research positions (economics, finance,
public policy, quantitative social science) across the UK, Europe, Canada,
the US, and international institutions, to Telegram and X/Twitter on a
daily schedule, at **zero recurring dollar cost**.

The zero-cost constraint governs every architectural decision: no paid compute,
no paid database tier, and zero-dependency fallbacks for every network service.
The pipeline operates as a scheduled batch job with committed state in version
control, executing cleanly on standard GitHub Actions runners.

## 2. System overview

```
GitHub Actions (cron, daily)
        |
        v
  +-----------+     +--------------+     +-------------+     +-----------+
  | Ingestion |---->| Deterministic|---->| Extraction   |---->| Dedup     |
  | (boards,  |     | gate (rules, |     | (Heuristic/ |     | (URL ->   |
  |  feeds,   |     |  multi-lang) |     |  Gemini)    |     |  MinHash  |
  |  portals, |     +--------------+     +-------------+     |  -> fuzzy)|
  |  X/Tw)    |                                              +-----+-----+
  +-----------+                                                    |
        ^                                                          v
        |                                                   +-------------+
        |                                                   | SQLite (v5) |
        |                                                   | (pending -> |
        |                                                   |  published) |
        |                                                   +------+------+
        |                                                          |
  config/sources.toml                                              v
        |                                                   +-------------+
        |                                                   | Broadcast   |
        +---------------------------------------------------| (Telegram & |
                                                            |  X/Twitter) |
                                                            +------+------+
                                                                   |
                                                                   v
                                                      data/listings.ndjson
                                                     (committed journal) +
                                                      docs/data/*.json
                                                      (GitHub Pages)
```

One run executes sequentially:
1. Rebuild SQLite cache from `data/listings.ndjson` and `data/seen.ndjson` if empty.
2. Ingest postings from enabled job boards, feeds, ATS portals, and X/Twitter.
3. Gate each item: check seen cache, evaluate deterministic regex rules.
4. Extract structured metadata: run heuristic extractor (or Gemini if key is provided).
5. Coerce to strict `PredocListing` domain model and evaluate confidence score.
6. Deduplicate across three tiers (URL hash, MinHash/LSH, fuzzy composite key).
7. Insert new listings as `pending` in SQLite.
8. Broadcast pending listings to Telegram channels and X/Twitter accounts.
9. Mark listings as `published` (or `undeliverable` on fatal errors).
10. Check filled/closed status for existing listings and expire past-deadline items.
11. Prune expired seen/DLQ entries and commit updated NDJSON journals.
12. Export JSON datasets and RSS feed for GitHub Pages dashboard.

## 3. Tier-by-tier trade-off analysis

### 3.1 Ingestion

| Option | Cost | Reliability | ToS risk | Verdict |
|---|---|---|---|---|
| Academic Job Boards (`boards/`) | Free | High — specialized scrapers for PREDOC, EconJobMarket, EURAXESS, SOMMA, academics.de, and university portals | Low — respects pacing and fetches public job listings | **Default on.** Core ingestion source. |
| RSS/Atom feeds | Free | High — feeds are structured for syndication | None — explicit public syndication channel | **Default on.** `ingest/collectors.py::collect_feeds`. |
| Schema.org `JobPosting` on career pages | Free | Medium — requires ATS structured microdata/JSON-LD | Low — machine-readable search engine markup | **Default on.** `collect_portals` with detail page link following. |
| Official X API v2 Search (`ingest/x.py`) | Free (Basic tier) | High — official authenticated REST endpoint | None — uses official API credentials | **Default on** when `X_BEARER_TOKEN` is configured. |
| Xquik Platform API (`ingest/xquik.py`) | Free/Freemium | High — managed scraping proxy endpoint | Low — offloads network proxying | **Default on** when `XQUIK_API_KEY` is configured. |
| Commercial job boards (LinkedIn, Indeed) via `python-jobspy` | Free (library) | Medium — breaks on markup changes | **High** — restrictive terms of service | **Default off.** Opt-in via `ENABLE_JOBSPY=true`. |
| Authenticated social scraping via `twscrape` | Free (library) | Low — aggressive rate-limits and account suspensions | **High** — automated browser session simulation | **Default off.** Opt-in via `ENABLE_TWITTER=true`. |

Feeds and portals are the ingestion backbone precisely because they carry the
least legal and reliability risk — they're either explicitly published for
machine consumption or embedded exactly so that machines (chiefly search
engines, but nothing distinguishes this pipeline from one) can read them.

### 3.2 Extraction

| Option | Cost | Determinism | Maintenance burden |
|---|---|---|---|
| Regex/keyword only | Free | High but brittle — can't handle "Assistant zur Erforschung von..." vs "Research Assistant" paraphrase | Low ongoing cost, but low recall on real-world phrasing variance |
| LLM (Gemini free tier), loose JSON contract | Free (rate-limited) | Handles paraphrase and multilingual text; not perfectly deterministic | Endpoint shape and rate limits can shift under the free tier (see below) — mitigated by dual-backend auto-probing |
| LLM (paid tier) | Not free | Same as above, better rate-limit guarantees | Violates the zero-cost constraint outright |

**Chosen: a cheap deterministic gate first (`core/gating.py`), LLM second.**
The gate is not a weaker substitute for the model — it's the thing that makes
the model affordable at all. It rejects the large, easy-to-pattern-match
classes (PhD studentships, postdocs, faculty postings, celebration posts,
paper announcements) *before* they cost a model call, and requires a positive
hiring-intent signal in one of seven languages before anything reaches
extraction. Model calls are the pipeline's scarcest resource; the gate's job
is to spend them only on things that plausibly need judgment.

**Two backends, not one, with auto-probing.** The provider's documentation
currently describes an `/v1beta/interactions` endpoint with its own
"breaking changes" notice, alongside the older, still-live
`:generateContent` endpoint. Betting the whole extraction layer on one shape
means betting on guessing right about which one is stable *for your account*
at *this moment*. `extract/gemini.py` tries `interactions` first, falls back
to `generate_content` on a 404/400, and caches whichever one worked in the
database's `meta` table so every subsequent run skips the probe. When the
provider finishes its migration in either direction, this needs a config
change or a version bump — not a rewrite.

### 3.3 Deduplication

Three tiers, cheapest first, each strictly narrower in scope than the one
before it:

**Tier 1 — canonical URL equality.** A SHA-256 hash of the canonicalized
application URL (tracking parameters stripped, host case-folded, query
params sorted — `core/urls.py`), enforced with a `UNIQUE` index in SQLite.
O(1) lookup, zero false positives by construction (two different canonical
URLs are, definitionally, different resources).

**Tier 2 — MinHash + banded LSH over word 5-shingles.** Catches the same
listing cross-posted to a different URL with reworded text (a common pattern
— the same predoc ad appears on a department page, an aggregator, and a
personal faculty page with slightly different wording each time).

The math, briefly: for two sets with true Jaccard similarity `s`, and a
random permutation `h` of the token universe, `P[min h(A) = min h(B)] = s`.
Averaging over `num_perm=128` independent permutations gives an unbiased
estimator with standard error ≈ `1/√128 ≈ 0.088`. That's why the estimate is
never trusted alone — Tier 3 exists specifically to catch what Tier 2's
variance lets through, not as a redundant safety net.

Banded LSH splits the 128-value signature into `b` bands of `r` rows each
(`b·r = 128`). Two items become *candidates* — worth an exact comparison —
if at least one band matches exactly:

```
P(candidate | s) = 1 - (1 - s^r)^b
```

`core/minhash.py::_choose_bands` picks `(b, r)` by numerically minimizing the
integral of this curve's error against the configured threshold (0.82 by
default) — the standard technique from the near-duplicate detection
literature, reproduced here rather than imported because the whole
implementation, banding included, is under 220 lines of pure arithmetic.
Word 5-shingles are used over character n-grams because character n-grams
saturate on long text — two genuinely unrelated English job ads share most of
their character trigrams, which makes trigram-based MinHash a poor
discriminator on anything longer than a tweet. Text under 24 words falls back
to character trigrams, where word-shingling has too little signal to work
with.

**Tier 3 — fuzzy composite key.** For short social-media posts with no real
description to shingle ("hiring a predoc, DM me"). Institution + title +
supervisor name, punctuation-stripped and token-sorted, compared with
`rapidfuzz.token_sort_ratio` (stdlib Levenshtein fallback if unavailable),
blocked on the institution's most distinctive token so a candidate is only
compared against the handful of prior listings from the *same* employer, and
gated on a 14-day deadline-proximity window so two genuinely different
postings from the same department don't collide just because their titles
are similar.

### 3.4 Storage

| Option | Cost | Query capability | Git-friendliness |
|---|---|---|---|
| Managed Postgres | Not free at any real scale | Full SQL | N/A |
| SQLite, committed as a binary file | Free | Full SQL | **Poor** — see below |
| SQLite as a rebuildable cache + NDJSON journal committed | Free | Full SQL (cache), diffable history (journal) | Good |

**Chosen: SQLite (Schema v5) as an ephemeral, gitignored cache; `data/listings.ndjson`
as the committed source of truth.** This is the most consequential design
change from the reviewed architecture (see `REVIEW.md` A1). Git stores a
whole new compressed blob for each version of a binary file — it cannot
delta SQLite b-tree pages, which move on nearly every write. Committing a
multi-megabyte database daily adds repository bloat and produces binary merge
conflicts when workflow runs overlap. An append-then-sorted-rewrite NDJSON file,
by contrast, diffs cleanly, compresses well, and merges safely.

`state.py::restore_if_needed` rebuilds the SQLite cache from the journal whenever
the database is empty — on fresh clones, cleared runners, or corrupted databases.

**Schema v5 Optimizations**:
- **Partial covering index (`ix_listings_active`)**: Indexes `(status, first_seen_at DESC) WHERE status = 'active'` so dashboard generation and public queries scan only live records without reading closed or expired rows.
- **Pending recovery index (`ix_listings_pending`)**: Indexes `(status, first_seen_at ASC) WHERE status = 'pending'` to accelerate pending item recovery after workflow interruptions.
- **Identity expression index (`ix_listings_identity`)**: Indexes `(lower(institution), lower(title))` for O(1) candidate matching in fuzzy deduplication.
- **Decision index (`ix_seen_items_decision`)**: Indexes `(decision, item_hash)` to accelerate repeated gating lookups.
- **High-performance PRAGMAs**: Connection initialization configures `PRAGMA mmap_size = 268435456` (256 MB memory-mapped I/O), `PRAGMA cache_size = -65536` (64 MB page cache), `PRAGMA busy_timeout = 10000` (10s lock timeout), and `PRAGMA temp_store = MEMORY`.

### 3.5 Orchestration

| Option | Cost | Constraint |
|---|---|---|
| Always-on server / container | Not free | N/A |
| GitHub Actions, scheduled | Free for public repos (unlimited minutes); 2,000 min/mo on private Free-plan repos | Runner is ephemeral — nothing persists except what's committed |
| Serverless function (Lambda, Cloud Functions) on a free tier | Free within limits | Extra platform to configure and hold credentials for, for no benefit over Actions here |

**Chosen: GitHub Actions, daily cron.** The repository already needs to
exist for the source registry and the dashboard; Actions is free compute
that reads and writes that same repository, with secrets management built
in. The real daily constraint is the model's request quota, not runner
minutes — see `REVIEW.md` F4.

### 3.6 Broadcasting and Publishing

| Channel | Format | Capabilities | Error Handling |
|---|---|---|---|
| Telegram Channel | HTML message cards & paged digests | Formatted title, institution, deadline, visa rules, and application link. Inline buttons (✅ Interested, ❌ Dismiss, 📝 Applied). | Set-up errors keep listings `pending` for retry. Transient errors do not drop listings. |
| X/Twitter Feed | 280-char structured tweets | Formatted title, institution, application URL, and targeted hashtags (`#EconTwitter #Predoc`). | OAuth 1.0a / OAuth 2.0 user context. Duplicate or rate-limited tweets fail gracefully without halting the pipeline. |
| GitHub Pages | Static JSON & interactive HTML | Client-side search, filtering by region, status, and deadline. | Regenerated locally or via Actions workflow. |
| RSS Syndication | Atom / RSS 2.0 XML | Standard syndication feed for RSS readers. | Exported directly from active listings. |

## 4. What runs where — data flow for one item

```
RawItem (source, url, text)
   |
   v
seen_items lookup (url_hash) --- already judged with same content? ---> skip
   |  no
   v
gating.evaluate() --- fails? ---> mark_seen(rejected, reason) ---> stop
   |  passes (rule_score computed)
   v
Extractor.extract() --- quota/rate-limit exhausted? ---> stop run cleanly,
   |  resume tomorrow (item is NOT marked seen)
   v
ExtractionResult (loose wire schema)
   |
   v
coerce() --- not a vacancy, or missing title/institution? ---> mark_seen
   |  ok (strict PredocListing)
   v
confidence = blend(model_confidence, rule_score) --- below threshold? --->
   |                                                    mark_seen(rejected)
   v
Tier 1: URL hash lookup --- match? ---> mark_seen(duplicate), add alt source
   |  no match
   v
Tier 2/3: Deduplicator.find() --- match? ---> mark_seen(duplicate), add alt source
   |  no match
   v
insert_listing(status=pending) + mark_seen(accepted, listing_id)
   |
   v
[after all items processed]
   |
   v
Broadcast (Telegram & X) --- success? ---> mark_published
                         --- permanent failure? ---> mark_undeliverable
                         --- transient failure? ---> stays pending, retried next run
```

## 5. Scaling beyond zero-cost

The pipeline currently runs with scale caps configured for high-volume collection:
2,500 detail enrichments, 12 concurrent source workers, 25 detail workers, and a
10,000 daily LLM request quota. If higher volume is needed in the future:

1. **Raise the LLM daily budget** (paid Gemini tier). Immediate, linear
   improvement in throughput, no architecture change — `RateLimiter` and the
   extraction backends are already parameterized by the settings that would
   change.
2. **Add more feed/portal sources.** Free. The gate and dedup logic don't
   care how many sources there are; the only cost is verifying each one
   (`sources verify`) and, for portals, tuning a `link_pattern`.
3. **Enable `jobspy` / `twitter`.** Free in dollars, costly in ToS risk and
   maintenance (scrapers break when target sites change markup). See
   `COMPLIANCE.md` before flipping either flag.
4. **X API v2 paid tier**, if `twscrape`'s scraping approach becomes
   untenable. As of the last time this was priced, the basic tier for search
   access started in the hundreds of dollars per month — a genuine
   architectural break from "zero cost," not a configuration change, and
   worth pricing again against current rates before committing to it.
5. **Move off GitHub Actions to a dedicated always-on worker**, only if a
   sub-daily cadence is ever needed. Nothing about the current design
   requires this — Actions' free tier and a daily cadence match the
   problem's actual urgency.

## 6. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Provider changes the extraction API shape again | Medium (it already did once during this project) | Extraction fails until fixed | Dual-backend auto-probe absorbs a same-family change automatically; a genuinely new API shape needs a new `_Backend` subclass, isolated to one file |
| Provider's actual rate limit is lower than configured | Medium — the provider itself says limits aren't guaranteed | Wasted quota, 429s | `RateLimiter` treats 429 `RetryInfo` as authoritative over the local estimate; `--safety-margin` defaults to 90% of the configured budget |
| A source's markup changes, yielding zero items silently | High over a long enough time horizon — this is normal web-scraping entropy | Silent coverage loss | `_maybe_alert` in `pipeline.py` flags any source that fetched successfully but yielded zero items, once 3+ sources do so in a run; `docs/data/health.json` makes per-source yield visible on the dashboard |
| Telegram bot token leaked or revoked | Low | Channel stops receiving posts | Token lives only in GitHub Secrets, never in the repo; `export_feed()` publishes the same data as RSS independent of Telegram, so a revoked token doesn't mean data loss, only a broadcast-channel outage |
| Optional scraper (`jobspy`/`twitter`) gets an account/IP blocked | Medium, if enabled | That source goes dark | Both are opt-in and off by default; failure in one collector never blocks the others (`gather()` isolates exceptions per collector) |
| Journal file grows very large over years of operation | Low near-term, real long-term | Slower clone, slower `import_rows` | `prune()` removes `seen_items` and `dlq` rows past their retention window; `expire_past_deadline` moves listings out of the "active" set (still in the journal for history, but excluded from the dashboard and RSS). A future archival split (e.g., yearly journal files) is a reasonable next step once this becomes a real cost. |
