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

> [!TIP]
> An interactive visual architecture diagram with dark and light themes, narrative tours, and pan and zoom controls is available at [`docs/architecture.html`](docs/architecture.html).

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
| Academic Job Boards (`boards/`) | Free | High: specialized scrapers for PREDOC, EconJobMarket, EURAXESS, SOMMA, academics.de, and university portals | Low: respects pacing and fetches public job listings | **Default on.** Core ingestion source. |
| RSS/Atom feeds | Free | High: standard syndication structures | None: explicit public syndication channel | **Default on.** `ingest/collectors.py::collect_feeds`. |
| Schema.org `JobPosting` on career pages | Free | Medium: requires ATS structured microdata or JSON-LD | Low: machine-readable search engine markup | **Default on.** `collect_portals` with detail page link following. |
| Official X API v2 Search (`ingest/x.py`) | Free (Basic tier) | High: official authenticated REST endpoint | None: uses official API credentials | **Default on** when `X_BEARER_TOKEN` is configured. |
| Xquik Platform API (`ingest/xquik.py`) | Free/Freemium | High: managed scraping proxy endpoint | Low: offloads network proxying | **Default on** when `XQUIK_API_KEY` is configured. |
| Commercial job boards (LinkedIn, Indeed) via `python-jobspy` | Free (library) | Medium: breaks on markup changes | **High**: restrictive terms of service | **Default off.** Opt-in via `ENABLE_JOBSPY=true`. |
| Authenticated social scraping via `twscrape` | Free (library) | Low: aggressive rate-limits and account suspensions | **High**: automated browser session simulation | **Default off.** Opt-in via `ENABLE_TWITTER=true`. |

Feeds and portals form the ingestion backbone because they carry minimal
legal and operational risk. Publishers syndicate them for machine
consumption or embed Schema.org metadata for search engines.

### 3.2 Extraction

| Option | Cost | Determinism | Maintenance burden |
|---|---|---|---|
| Regex/keyword only | Free | High, but brittle: fails on paraphrased titles like "Assistant zur Erforschung von..." versus "Research Assistant" | Low ongoing cost, but lower recall on phrasing variations |
| LLM (Gemini free tier), loose JSON contract | Free (rate-limited) | Handles paraphrases and multilingual text; probabilistic | Endpoint shapes and rate limits can shift under the free tier. Dual-backend auto-probing mitigates this risk. |
| LLM (paid tier) | Recurring cost | Same as above, higher rate limits | Violates the zero-cost constraint |

**Design: deterministic gating (`core/gating.py`) precedes LLM extraction.**
The gate keeps model usage within free quotas. It rejects obvious
non-targets (PhD studentships, postdocs, faculty postings, paper
announcements) using regex filters and requires positive hiring-intent signals
in one of seven supported languages. This limits LLM calls to ambiguous listings
that require semantic parsing.

**Dual backends with auto-probing.** Google AI Studio documents both the
`/v1beta/interactions` endpoint (flagged for breaking changes) and the older
`:generateContent` endpoint. Availability varies across accounts and regions.
`extract/gemini.py` attempts `interactions` first, falls back to
`generate_content` on HTTP 400 or 404, and records the working endpoint in
the SQLite `meta` table to skip subsequent probes. When Google finalizes
migration to one format, adjusting configuration resolves the change without code
rewrites.

### 3.3 Deduplication

Three sequential tiers execute from cheapest to most computationally intensive:

**Tier 1: Canonical URL equality.** A SHA-256 hash of the canonicalized
application URL (tracking parameters removed, host lowercased, and query
parameters sorted in `core/urls.py`), indexed as `UNIQUE` in SQLite.
This provides O(1) lookups with zero false positives.

**Tier 2: MinHash and banded LSH over word 5-shingles.** Catches listings
cross-posted across different URLs with minor wording variations, such as
ads published concurrently on departmental pages and job boards.

For two token sets with Jaccard similarity `s` and a random permutation `h`,
`P[min h(A) = min h(B)] = s`. Averaging over `num_perm=128` independent
permutations yields an unbiased estimator with standard error ≈ 1/√128 ≈ 0.088.
Because of this variance, Tier 3 provides secondary validation.

Banded Locality-Sensitive Hashing (LSH) divides the 128-value signature into `b`
bands of `r` rows (`b·r = 128`). Two items become candidate pairs if at least
one band matches identically:

```
P(candidate | s) = 1 - (1 - s^r)^b
```

`core/minhash.py::_choose_bands` calculates `(b, r)` by numerically minimizing
the integral error against the default threshold (0.82). The standard library
implementation requires under 220 lines of arithmetic. Word 5-shingles prevent
the saturation common to character n-grams on longer descriptions. Ads under
24 words fall back to character trigrams to ensure sufficient signal.

**Tier 3: Fuzzy composite key.** Addresses brief social media posts lacking full
job descriptions. The system normalizes institution, title, and supervisor names
(stripping punctuation and sorting tokens), then calculates similarity with
`rapidfuzz.token_sort_ratio` (falling back to standard library Levenshtein
distance when optional dependencies are absent). Comparisons are partitioned by
the institution's primary token and restricted to a 14-day deadline window to
prevent false positives between distinct departmental openings.

### 3.4 Storage

| Option | Cost | Query capability | Git-friendliness |
|---|---|---|---|
| Managed Postgres | Non-zero | Full SQL | N/A |
| SQLite committed as binary | Free | Full SQL | Poor (binary churn on every commit) |
| SQLite cache + committed NDJSON journal | Free | Full SQL cache, diffable history | High |

**Design: SQLite (Schema v5) acts as an ephemeral cache; `data/listings.ndjson`
serves as the committed source of truth.** Git stores complete compressed blobs
for modified binary files. Because SQLite modifies B-tree pages on write, committing
the raw database produces merge conflicts and inflates repository size. The NDJSON
journal appends cleanly, produces readable diffs, and merges safely in version control.

`state.py::restore_if_needed` reconstructs the SQLite database from the NDJSON journal
when initializing fresh clones, running on ephemeral runners, or recovering from corruption.

**Schema v5 Optimizations**:
- **Partial covering index (`ix_listings_active`)**: Indexes `(status, first_seen_at DESC) WHERE status = 'active'` so dashboard generation and public queries scan only live records without reading closed or expired rows.
- **Pending recovery index (`ix_listings_pending`)**: Indexes `(status, first_seen_at ASC) WHERE status = 'pending'` to accelerate pending item recovery after workflow interruptions.
- **Identity expression index (`ix_listings_identity`)**: Indexes `(lower(institution), lower(title))` for O(1) candidate matching in fuzzy deduplication.
- **Decision index (`ix_seen_items_decision`)**: Indexes `(decision, item_hash)` to accelerate repeated gating lookups.
- **High-performance PRAGMAs**: Connection initialization configures `PRAGMA mmap_size = 268435456` (256 MB memory-mapped I/O), `PRAGMA cache_size = -65536` (64 MB page cache), `PRAGMA busy_timeout = 10000` (10s lock timeout), and `PRAGMA temp_store = MEMORY`.

### 3.5 Orchestration

| Option | Cost | Constraints |
|---|---|---|
| Dedicated server or container | Recurring cost | Continuous infrastructure maintenance |
| Scheduled GitHub Actions | Free for public repositories | Ephemeral environment requiring state commits |
| Serverless functions (Lambda, Cloud Functions) | Free tier limits | Additional external credentials and deployment complexity |

**Design: Scheduled GitHub Actions cron.** Workflows execute within the
repository that hosts the dashboard and registry, using built-in secret
management. Daily operation is bounded by external model quotas rather than
Actions runner minutes (documented in `REVIEW.md` F4).

### 3.6 Broadcasting and Publishing

| Channel | Format | Capabilities | Error Handling |
|---|---|---|---|
| Telegram Channel | HTML message cards and paged digests | Formatted title, institution, deadline, visa rules, and application link. Inline buttons (Interested, Dismiss, Applied). | Configuration errors keep listings in `pending` state for retry. Transient errors do not drop listings. |
| X/Twitter Feed | 280-character structured tweets | Formatted title, institution, application URL, and targeted hashtags (`#EconTwitter #Predoc`). | OAuth 1.0a or OAuth 2.0 user context. Duplicate or rate-limited posts fail without halting the pipeline. |
| GitHub Pages | Static JSON and interactive HTML | Client-side search and filtering across region, status, and deadline. | Regenerated locally or via Actions workflow. |
| RSS Syndication | Atom / RSS 2.0 XML | Standard syndication feed for RSS readers. | Exported directly from active listings. |

## 4. Data flow per item

```
RawItem (source, url, text)
   |
   v
seen_items lookup (url_hash) -> already judged with same content? -> skip
   |  no
   v
gating.evaluate() -> fails? -> mark_seen(rejected, reason) -> stop
   |  passes (rule_score computed)
   v
Extractor.extract() -> quota/rate-limit exhausted? -> stop run cleanly,
   |  resume tomorrow (item is NOT marked seen)
   v
ExtractionResult (loose wire schema)
   |
   v
coerce() -> not a vacancy, or missing title/institution? -> mark_seen
   |  ok (strict PredocListing)
   v
confidence = blend(model_confidence, rule_score) -> below threshold? ->
   |                                                mark_seen(rejected)
   v
Tier 1: URL hash lookup -> match? -> mark_seen(duplicate), add alt source
   |  no match
   v
Tier 2/3: Deduplicator.find() -> match? -> mark_seen(duplicate), add alt source
   |  no match
   v
insert_listing(status=pending) + mark_seen(accepted, listing_id)
   |
   v
[after all items processed]
   |
   v
Broadcast (Telegram & X) -> success? -> mark_published
                         -> permanent failure? -> mark_undeliverable
                         -> transient failure? -> stays pending, retried next run
```

## 5. Scaling beyond zero-cost

The pipeline currently runs with scale caps configured for high-volume collection:
2,500 detail enrichments, 12 concurrent source workers, 25 detail workers, and a
10,000 daily LLM request quota. If higher volume is needed in the future:

1. **Raise the LLM daily budget.** A paid API tier scales extraction linearly.
   `RateLimiter` and extraction backends accept quota parameters directly through
   environment variables.
2. **Expand feed and portal sources.** Adding sources carries zero financial cost.
   New sources require verification (`sources verify`) and URL link patterns for
   ATS portals.
3. **Enable optional scrapers (`jobspy` and `twscrape`).** These expand reach but
   introduce ToS risks and maintenance overhead as target HTML changes. Consult
   `COMPLIANCE.md` before activation.
4. **Adopt paid X API search endpoints.** If public scraping becomes unreliable,
   official search endpoints provide stable access at paid tier rates.
5. **Deploy dedicated background runners.** If sub-daily polling becomes necessary,
   workflows can migrate to an always-on container. Daily batch execution on
   GitHub Actions remains sufficient for academic recruitment cycles.

## 6. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Provider changes extraction API schema | Medium (occurred once during initial development) | Extraction fails until updated | Dual-backend auto-probing absorbs backward-compatible changes; distinct API formats require a targeted `_Backend` subclass isolated to `extract/` |
| Provider rate limits fall below configured targets | Medium (provider limits vary dynamically) | Rate limit errors (HTTP 429) | `RateLimiter` respects HTTP 429 `RetryInfo` headers over local estimates; `--safety-margin` defaults to 90% of configured quotas |
| Source markup changes, yielding zero items silently | High over time (standard web scraping entropy) | Undetected coverage loss | `_maybe_alert` in `pipeline.py` flags sources that fetch successfully but yield zero items once 3+ sources do so in a single run; `docs/data/health.json` publishes per-source yields to the dashboard |
| Telegram bot token leaked or revoked | Low | Broadcast posts halt | Tokens reside exclusively in GitHub Secrets; `export_feed()` publishes identical data to RSS independently of Telegram |
| Optional scraper account or IP suspended | Medium (when optional collectors are active) | Targeted source becomes inactive | Scrapers are disabled by default; `gather()` isolates collector exceptions so individual failures do not block the pipeline |
| Journal file expands over multi-year operations | Low near-term, moderate long-term | Slower repository clones and imports | `prune()` purges `seen_items` and `dlq` records past retention limits; `expire_past_deadline` archives inactive listings |
