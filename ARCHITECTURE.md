# Architecture

## 1. Goal and constraints

Discover, deduplicate, and broadcast full-time **pre-doctoral** research
assistantships (economics, finance, public policy, quantitative social
science) located outside the United States, to a Telegram channel, on a
daily schedule, at **zero recurring dollar cost**.

The zero-cost constraint is the design's real spine. Every choice below is
downstream of it: no paid compute, no paid API tier, no paid storage. That
rules out a lot of otherwise-obvious architectures (a managed database, a
paid LLM tier with real rate-limit guarantees, a always-on server) and forces
the design toward *serverless-by-necessity*: a scheduled batch job with
everything it needs checked into version control.

## 2. System overview

```
GitHub Actions (cron, daily)
        |
        v
  +-----------+     +--------------+     +-------------+     +-----------+
  | Ingestion |---->| Deterministic|---->| Extraction   |---->| Dedup     |
  | (feeds,   |     | gate (rules, |     | (Gemini,     |     | (URL ->   |
  |  portals, |     |  multi-lang) |     |  2 backends) |     |  MinHash  |
  |  opt-in   |     +--------------+     +-------------+     |  -> fuzzy)|
  |  boards/  |                                              +-----+-----+
  |  social)  |                                                    |
  +-----------+                                                    v
        ^                                                   +-------------+
        |                                                   | SQLite      |
        |                                                   | (pending -> |
        |                                                   |  published) |
        |                                                   +------+------+
        |                                                          |
  config/sources.toml                                              v
        |                                                   +-------------+
        |                                                   | Telegram    |
        +---------------------------------------------------|  broadcast  |
                                                              +------+------+
                                                                     |
                                                                     v
                                                        data/listings.ndjson
                                                       (committed journal) +
                                                        docs/data/*.json
                                                        (GitHub Pages)
```

One run does, strictly in this order: restore state from the journal if the
database is empty → load sources → fetch (politely, with caching) → for each
item: check if already seen → run the deterministic gate → extract via LLM
(budget permitting) → coerce to the domain model → apply the confidence
threshold → deduplicate (three tiers) → insert as `pending` → broadcast →
mark `published` → expire past-deadline listings → prune old rows → write the
journal and dashboard exports → alert the maintainer if something looks
broken.

## 3. Tier-by-tier trade-off analysis

### 3.1 Ingestion

| Option | Cost | Reliability | ToS risk | Verdict |
|---|---|---|---|---|
| RSS/Atom feeds | Free | High — feeds are meant to be machine-read | None — this is exactly what syndication is for | **Default on.** `ingest/collectors.py::collect_feeds`. |
| Schema.org `JobPosting` on career pages | Free | Medium — depends on whether the ATS emits structured data, and whether it's on the index or detail page | Low — this markup exists specifically so machines (mostly search engines) can read it | **Default on.** `collect_portals`, with `follow_links` for the common case where JSON-LD lives on detail pages, not index pages. |
| Commercial job boards (LinkedIn, Indeed) via `python-jobspy` | Free (library), but scrapes sites with restrictive ToS | Medium — breaks whenever the target site changes its markup | **High** — see `COMPLIANCE.md` | **Default off.** Opt-in via `ENABLE_JOBSPY=true`. |
| Authenticated social search (X) via `twscrape` | Free (library), but requires real account credentials and violates X's ToS on automated access | Low — account-based scraping is adversarially rate-limited and accounts get suspended | **High** — see `COMPLIANCE.md` | **Default off.** Opt-in via `ENABLE_TWITTER=true`. |

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

**Chosen: SQLite as an ephemeral, gitignored cache; `data/listings.ndjson`
as the committed source of truth.** This is the most consequential design
change from the reviewed architecture (see `REVIEW.md` A1). Git stores a
whole new compressed blob for each version of a binary file — it cannot
delta SQLite b-tree pages, which move on nearly every write. Committing a
multi-megabyte database daily adds roughly a gigabyte of repository growth a
year and produces unresolvable binary merge conflicts the moment two
workflow runs overlap. An append-then-sorted-rewrite NDJSON file, by
contrast, diffs cleanly, compresses well, and is trivially mergeable (union
of lines) even in the rare case of a real conflict. `state.py::restore_if_needed`
rebuilds the SQLite cache from the journal whenever the database is empty —
a fresh clone, a cleared runner, and a corrupted `.db` file all recover the
same way.

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
Telegram broadcast (card or digest) --- success? ---> mark_published
                                    --- permanent failure? ---> mark_undeliverable
                                    --- transient failure? ---> stays pending,
                                                                  retried next run
```

## 5. Scaling beyond zero-cost

If this ever needs to grow past the free tier, in rough order of
cost-effectiveness:

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
