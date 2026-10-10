# Collegeum audit: boundary and failure-path pass — 5 October 2026

This pass adds **13 findings (F39–F51)** to the [38-finding audit](audit.md). Five are P1 and eight are P2. Together, the reports contain 51 findings; this is a cumulative count, not a claim that every possible defect has been exhausted. Production code, configuration, monitored sources and remote resources were not changed.

The new [offline evidence harness](reproduce-boundaries.py) passed **14 checks** and lint; its captured results are in [boundary-evidence.json](boundary-evidence.json). It uses temporary databases/files and mocked HTTP/publishing. Several findings turn previously listed uncertain follow-up cases into reproduced behavior. The workflow-budget finding is a calculation from the current configuration, not an observed GitHub timeout. The CSV check mirrors the exporter expression without executing a spreadsheet formula. No live provider calls or posts were made.

The most consequential additions are recovery silently discarding state, fetched feed items becoming unrecoverable before processing, extraction contradicting the current vacancy policy, and a configured source budget longer than the workflow allows.

## New findings

### F39 — P2: the Telegram card's last-resort truncation breaks escaped HTML

[`render_card`](../../src/predoc_pipeline/publish/telegram.py#L174) budgets the summary against the fixed fields, but those fields are not all bounded. Compensation, location, start and requirements can already consume the budget. Its final fallback ([line 234](../../src/predoc_pipeline/publish/telegram.py#L234)) slices raw HTML, rather than plain text or complete HTML entities.

**Reproduced:** a validated listing with 6,000 `<` characters in `salary_raw` produces a card cut inside an escaped entity. Parsing the resulting markup fails at line 10, column 3873. This demonstrates broken serialization; an actual Telegram rejection was not requested. The model allows unrestricted compensation/location strings ([fields](../../src/predoc_pipeline/models.py#L78)).

**Effect:** a single oversized field can make an otherwise eligible listing undeliverable. Retrying the same rendering cannot repair it. The docstring's guarantee that cards fit the limit is incomplete.

**Repair:** bound every variable field before escaping; reserve space for tags, separators and links; truncate plain text by the remaining visible-character budget. Preserve complete entities and tags. **Acceptance:** long compensation, location and requirement fields containing `&`, `<`, `>` and Unicode render valid Telegram HTML within the limit, without cutting a URL or entity.

### F40 — P2: digest pages are limited by item count, not rendered size

[`render_digest_pages`](../../src/predoc_pipeline/publish/telegram.py#L291) chunks by `page_size`. It does not split a page when its actual text exceeds the message limit. [`TelegramPrefs`](../../src/predoc_pipeline/boards/config.py#L91) accepts arbitrary page sizes, and even the default size cannot guarantee safety when location strings are unbounded.

**Reproduced:** 30 otherwise small validated listings, a configured page size of 30, 110-character titles and 90-character institutions produce one page with **7,356 visible characters**. Telegram's documented text limit is 4,096 after entity parsing. [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage).

**Effect:** in enabled digest mode, a permanently overlong page remains pending and can fail identically on every run ([delivery loop](../../src/predoc_pipeline/pipeline.py#L762)). The shipped digest threshold defaults to zero, so this reproduces a supported configuration rather than claiming the current channel sent this page.

**Repair:** pack pages by rendered length and item count; cap individual fields; handle an oversized single item separately. Apply the same rule to bot command pages ([build_pages](../../src/predoc_pipeline/publish/bot.py#L151)). **Acceptance:** every generated page fits for supported settings, and one unusually long listing cannot block the others.

### F41 — P2: one invalid XML character breaks the entire RSS feed

[`_xml_escape`](../../src/predoc_pipeline/state.py#L286) replaces XML metacharacters but retains forbidden control characters. [`export_feed`](../../src/predoc_pipeline/state.py#L325) passes titles, summaries and other source-derived values through that function.

**Reproduced:** a published row containing U+0001 in its summary successfully exports one item, but parsing the written feed fails at line 15, column 95. The exporter reports success even though its output is not valid XML. XML escaping and validating the permitted character repertoire are separate requirements. [W3C XML character rules](https://www.w3.org/TR/xml/#charsets).

**Repair:** remove or replace characters forbidden by XML 1.0, then validate the completed feed before atomically replacing the public file. Retain the previous valid feed if generation fails. **Acceptance:** control-character fixtures produce valid XML and a failed export cannot publish a partially written feed.

### F42 — P2: CSV quoting does not neutralize spreadsheet formulas

The [CSV exporter](../../docs/index.html#L2352) doubles quotation marks and wraps text cells, but preserves a formula-leading value from source data. Quoting is necessary for CSV structure; it does not make spreadsheet formulas inert. [OWASP CSV Injection](https://owasp.org/www-community/attacks/CSV_Injection).

**Verified expression:** a valid title `=1+1` becomes the CSV cell `"=1+1"`. The harness uses the same expression as the exporter and benign arithmetic; no spreadsheet was opened, no formula executed, and no malicious live record is asserted.

**Repair:** choose an explicit spreadsheet-safe export policy for source-derived text, including leading `=`, `+`, `-`, `@`, tabs and line breaks. Apply it consistently to all text columns while preserving legitimate numeric values. **Acceptance:** representative formula-leading text remains text in the supported spreadsheet applications; quoted commas, multiline text and Unicode still round-trip correctly.

### F43 — P2: partial X threads lose the IDs of already-created posts

[`XClient.post_thread`](../../src/predoc_pipeline/publish/x.py#L252) keeps created IDs in a local list and returns it only when every request succeeds. If a later post fails, the exception does not carry the successful IDs. [`post_listing(as_thread=True)`](../../src/predoc_pipeline/publish/x.py#L262) cannot checkpoint the partial thread either.

**Reproduced:** the first mocked post returns `created-1`; the second raises `XError`. Two calls occur, but the caller receives no completed-post IDs with the error. A retry from the beginning can duplicate the first post.

**Scope:** this affects the supported thread API; the current pipeline invokes the single-post default. It is not evidence that live threads were duplicated.

**Repair:** persist each created ID immediately, return partial progress in a structured failure, and resume at the unsent segment with the correct reply ID. **Acceptance:** failure after any segment preserves all prior IDs and a retry never recreates an acknowledged segment. Also distinguish an acknowledged failure from an uncertain network outcome after submission.

### F44 — P1: malformed personal state silently resets marks and cursor

[`_read_json`](../../src/predoc_pipeline/publish/feedback.py#L31) returns an empty dictionary on malformed JSON, exactly as it does for a missing file. `FeedbackStore` then initializes empty marks and [`save`](../../src/predoc_pipeline/publish/feedback.py#L79) replaces the file. Bot cursor loading uses the same reader. Valid JSON with an invalid nested shape is also accepted until later code crashes.

**Reproduced:** truncated feedback JSON becomes `{"marks": {}}` after a load/save; truncated cursor JSON becomes `{}`. `{"marks": null}` instead crashes when the hidden set is read. These are temporary files, not the user's private state.

**Effect:** existing hidden/interested/applied marks can disappear, and the missing cursor can allow retained Telegram updates to be replayed. A replayed toggle can undo a prior mark. Unknown state should not be interpreted as an affirmative empty state.

**Repair:** distinguish absent, valid and corrupt files; validate nested shapes and cursor types; preserve corrupt files with diagnostics and avoid destructive replacement. Recover from a known-valid backup or stop the affected operation with an actionable error. **Acceptance:** malformed and wrong-shaped state cannot silently erase marks or reset the offset; the previous file remains recoverable.

### F45 — P1: partial journal restore can replace the only durable copy

[`read_journal`](../../src/predoc_pipeline/state.py#L58) skips malformed lines without exposing their count or positions. [`restore_if_needed`](../../src/predoc_pipeline/state.py#L99) treats the surviving rows as a successful restore. Normal and fatal-run cleanup then rewrite the journal from that partial database ([finally block](../../src/predoc_pipeline/pipeline.py#L1271)). The same reader is used for seen state.

**Reproduced:** a two-line journal containing one valid listing and one malformed line restores one row; `write_journal` then replaces it with a one-line file. The damaged line is no longer available for inspection or repair. No warning records the incomplete restore.

**Effect:** a fresh runner can permanently lose durable listing/delivery history or seen verdicts. That can remove public records or cause a previously processed opportunity to be reconsidered. F20 covered misleading import counts; this is the distinct destructive recovery consequence.

**Repair:** report malformed lines and failed imports, validate restoration completeness, preserve the original journal, and block replacement by a partially restored database. **Acceptance:** a damaged listing or seen journal remains intact, valid rows can be inspected safely, and recovery cannot silently commit a smaller state snapshot.

### F46 — P1: unchanged HTTP content suppresses items that never reached processing

[`PoliteClient.get`](../../src/predoc_pipeline/ingest/http.py#L173) records the content hash at fetch time. [`collect_feeds`](../../src/predoc_pipeline/ingest/collectors.py#L94) and [`collect_portals`](../../src/predoc_pipeline/ingest/collectors.py#L272) skip a subsequently unchanged response. The cache does not know whether its emitted items were accepted, rejected, deferred by a limit, or lost before processing.

**Reproduced:** two identical mocked HTTP 200 feed responses produce one item on the first collection and zero on the second, while the database still has zero listings and zero seen verdicts. The second source result says unchanged. No conditional HTTP 304 is needed to trigger it.

**Effect:** in a persistent database/cache, a crash, quota stop or run limit after collection can make unprocessed items disappear from future collection until the source body changes. A dry run also performs cache-writing collection before returning without processing ([run ordering](../../src/predoc_pipeline/pipeline.py#L1023)), so it exposes the same sequence. An unchanged portal index also prevents revisiting linked adverts whose own contents changed. This differs from F05's per-posting URL seen gate: the fetch cache suppresses work even before a posting has any verdict.

**Repair:** separate fetched content from processing completion. Keep enough cached content or a durable candidate queue to replay outstanding work, and schedule detail-page rechecks independently of unchanged index HTML. **Acceptance:** stop a run after collection, restart with identical/304 responses, and prove every unprocessed item remains available exactly once for processing. A dry run followed by a real run must retain the same candidates. New ephemeral CI databases do not persist this particular HTTP cache; persistent local deployments do.

### F47 — P2: case-folding a fetched document hides case-sensitive link changes

[`content_hash`](../../src/predoc_pipeline/core/urls.py#L163) collapses whitespace and lowercases the whole fetched document. `PoliteClient` uses that value to skip unchanged feeds/portals. This lowercases URLs inside HTML/XML as well as prose, even though the URL identity implementation correctly preserves path case.

**Reproduced:** a feed changes an item link from `/jobs/A` to `/jobs/a`; the hashes are equal, the second collection emits zero items, and the source is marked unchanged. These can identify different resources on a case-sensitive site.

**Repair:** use a byte-preserving response/content digest for HTTP change detection, or a structure-aware digest that preserves semantically significant URL and identifier case. Keep normalized prose hashing separate. **Acceptance:** link/identifier case changes are detected, while any deliberately ignored cosmetic changes have documented semantics.

### F48 — P1: configured stage budgets exceed the workflow's hard deadline

Current [HTTP preferences](../../config/preferences.toml) allow 12 concurrent sources and 600 seconds per source. There are 69 enabled board entries. [`_scrape_all`](../../src/predoc_pipeline/boards/collector.py#L113) starts each source timeout after acquiring the semaphore and waits for all source tasks before later stages proceed. The [pipeline workflow](../../.github/workflows/pipeline.yml#L30) permits 40 minutes for the entire job, including installation, extraction, enrichment and publication.

**Verified calculation:** six batches × 600 seconds = **3,600 seconds for source scraping alone**, versus a 2,400-second job limit. This is an allowed worst-case schedule, not a prediction of typical runtime or an observed workflow cancellation. Details (up to 2,500), model work, rechecks (up to 500), and publishing consume additional time.

**Effect:** enough slow sources can prevent processing/export from starting before the job is killed. A hard runner timeout is not guaranteed to execute Python cleanup or the later state-commit step. Larger source coverage increases this exposure.

**Repair:** define a total run deadline, reserve time for export/persistence, derive bounded stage budgets from it, and checkpoint completed source/candidate work incrementally. Defer remaining work explicitly instead of waiting beyond the outer deadline. **Acceptance:** simulate many slow sources with a scaled clock; completed work is preserved, deferred work is visible, and the run exits before the workflow limit with time left to commit state.

### F49 — P1: extraction still implements the former predoc-only policy

The current preferences allow PhD positions, and [`_pre_extract`](../../src/predoc_pipeline/pipeline.py#L344) passes `allow_phd` plus `allow_postdoc=True` to the gate. But the shared [system prompt](../../src/predoc_pipeline/extract/prompt.py#L22) describes a predoc feed outside the US and explicitly instructs rejection of postdocs and doctoral positions. That prompt is sent unchanged by the [LLM transport](../../src/predoc_pipeline/extract/gemini.py#L521), rather than reflecting the current policy/routing. The wire schema also describes vacancy eligibility as predoc-only ([schema](../../src/predoc_pipeline/models.py#L179)).

The heuristic backend has a related inconsistency: its [text path](../../src/predoc_pipeline/extract/heuristic.py#L307) applies title/doctoral exclusions, while its [board path](../../src/predoc_pipeline/extract/heuristic.py#L273) returns a vacancy directly from the board hints.

**Reproduced:** a hiring advert for a funded economics PhD passes the gate with the current allowances. The same advert is rejected by heuristic text/feed extraction (`not_a_vacancy`) but accepted when supplied as a board item. The prompt conflict is verified in the actual request-building path; no assertion is made about how a live model would disobey or comply with it.

**Effect:** supported categories can be lost according to source format and configured backend. Since model rejection is marked seen ([post-extraction](../../src/predoc_pipeline/pipeline.py#L400)), later policy corrections can also require deliberate reconsideration of old verdicts.

**Repair:** have one eligibility policy flow through the gate, heuristic backend, model prompt/schema and post-extraction checks. Extract factual vacancy type before applying destination rules. Version seen verdicts when policy changes. **Acceptance:** equivalent predoc, PhD and postdoc adverts yield consistent outcomes across board/feed/portal inputs and supported backends under both inclusion and exclusion settings; US eligibility follows the current routing policy.

### F50 — P2: explicit month-first format instructions are ignored

[`find_dates`](../../src/predoc_pipeline/boards/utils/dates.py#L74) follows its numeric date patterns without interpreting an explicit format annotation. The global day-first default was designed for a mainly European corpus, but it should not override a source that states the convention.

**Reproduced:** `Application deadline (MM/DD/YYYY): 03/04/2027` becomes **3 April 2027**, although the stated format means **4 March 2027**. This example is unambiguous; it does not infer a convention merely from the employer's country.

**Repair:** honor explicit format cues first, then source-specific locale, and retain uncertainty when neither is available. **Acceptance:** explicit MM/DD/YYYY and DD/MM/YYYY examples parse correctly; ambiguous unlabeled values are not assigned a false certainty. Test the board parser and model instructions against the same fixtures.

### F51 — P2: Workday pagination caps return incomplete coverage without a partial signal

[`WorkdayScraper.fetch_raw_postings`](../../src/predoc_pipeline/boards/scrapers/university_ats.py#L49) fetches at most `max_pages` per search term (default three), even when the API advertises more results. It does not expose the remaining total or truncation. [`BaseScraper.run`](../../src/predoc_pipeline/boards/scrapers/base.py#L85) returns the parsed count, and the collector treats a completed call as successful; it has no coverage-completeness field.

**Reproduced:** a mocked API advertises 61 distinct jobs and returns 20 per page. The scraper makes three requests and returns/reports 60; the 61st is never fetched and the output carries no partial-coverage signal.

**Scope:** a bounded cap is a reasonable resource control. The defect is presenting a capped result without making the lost coverage visible or retaining a continuation strategy. Actual loss depends on each source's configured terms, cap, result order and total; this is not a claim that a particular live vacancy was missed.

**Repair:** report `total`, fetched pages and truncated status; retain a continuation cursor or partition searches so that relevant results do not remain perpetually beyond the same first pages. **Acceptance:** a total larger than the cap yields an explicit partial result with resumable work; totals below the cap report complete coverage, and duplicate results across terms do not inflate it.

## Cross-checks and verification boundaries

| Area revisited | Additional work | What remains unverified |
|---|---|---|
| Outputs and I/O | Rendered-card entity integrity; digest visible length; RSS parser validation; CSV expression and formula-leading values | Live Telegram rejection, spreadsheet application behavior, complete Unicode-length matrix |
| Recovery and persistence | Corrupt marks/cursor, wrong nested JSON shape, partial journal restoration/rewrite | Power-loss/fsync durability, concurrent local writers, full corruption/import schema matrix |
| Ingestion and cache | Identical feed replay with zero committed verdicts; case-sensitive URL change; Workday pagination totals | Each of the 22 saved failed sources still needs adapter-specific live diagnosis |
| Core policy and extraction | Current allowances versus prompt/schema and heuristic board/text paths; explicit date-format conflict | Paid/provider model adherence and provider-version contract tests |
| Caps and orchestration | Actual source concurrency/timeouts, enabled count, hard workflow limit and later-stage caps | Full stress/load test and a real workflow timeout; no remote job was dispatched |
| Publishing | Mocked partial X thread; current default path distinguished from optional API | Uncertain-success network failures, live posting, complete resumable delivery implementation |

The earlier boundary observations were checked before promoting them to findings. The output contracts above are supported by source traces and the harness. The CSV and workflow-budget checks are intentionally narrower than an end-to-end exploit or cancellation demonstration. `clean_url` does enforce HTTP/HTTPS schemes in the extraction path; a blanket claim that that path accepts JavaScript URLs would be incorrect and was excluded. Configuration caps alone were not treated as bugs unless they lose work, produce invalid output or conceal incomplete coverage.

The boundary harness contains 14 successful checks across 13 new findings; F44 has two shape/corruption checks. The prior harness contains 19 checks. Both are audit evidence and assert current defective behavior, so they should not replace regression tests that assert the repaired behavior. Existing production tests were not edited.

After resuming, the full suite completed with **309 tests and 15 subtests passed in 41.82 seconds**. Lint passed across production code, existing tests and both evidence harnesses. This supersedes the earlier captured test run for the current clock, without changing the earlier audit's historical evidence. The previously failing host-local/UTC deadline fixture passed this time, consistent with the time-dependent failure already described; it was not patched. No new coverage percentage is claimed because this rerun did not collect coverage. A green suite does not disprove the separately reproduced boundary defects.

## Repair order

1. Preserve state before attempting recovery: F44 and F45. Add explicit corrupt/partial outcomes and forbid destructive rewrite of incomplete state.
2. Preserve pending work across collection and time limits: F46 and F48, coordinated with the earlier quota and future-cancellation findings.
3. Align eligibility across every backend and source format: F49, including versioned reconsideration of rejected URLs.
4. Enforce output contracts before public file replacement or message submission: F39–F42; add real renderer/export fixtures and length validation.
5. Correct date cues, content change detection and capped coverage reporting: F47, F50 and F51. Make partial X progress durable before enabling threads (F43).

The existing [source expansion shortlist](source-expansion.md) remains researched but inactive. Adding more sources before the recovery, health and budget defects are addressed will make completeness harder to establish. The review remains broad and evidence-based, with its residual checks stated explicitly rather than claiming no issues remain.
