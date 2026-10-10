# Collegeum audit — 5 October 2026

Reviewed site: [Collegeum](https://amirrezafarnamtaheri.github.io/Collegeum/). The corrected URL loads; the previous predoc-not-org URL is an outdated reference, not evidence that Collegeum is down.

This review covers the live dashboard interactions, committed output data, source registry, scraping and enrichment, filtering, extraction, persistence and recovery, publishing, quotas, and scheduled workflows. Findings below distinguish observed behavior from consequences inferred from code. Production files and remote resources were not changed.

## Assessment

A subsequent boundary/failure-path pass adds F39–F51 in [audit-addendum.md](audit-addendum.md), bringing the cumulative total to 51 findings. Its separate evidence harness adds 14 checks for output limits, cache replay, recovery, extraction policy and pagination.

The most serious problems affect which opportunities are published and whether the monitoring status can be trusted. Broad source defaults admit unrelated biomedical jobs and assign incorrect countries. Published web listings return to the pending queue. Source failures are hidden behind a recent update timestamp. Correct these before substantially increasing ingestion volume.

### Evidence snapshot

| Check | Result |
|---|---|
| Configured board entries | 75 entries, 74 distinct names |
| Enabled board entries | 69 entries, 68 distinct names; six disabled |
| Duplicate source name | `predoc_org`, with two different adapters |
| Latest saved source outcomes | 22 failures and 11 successful zero-result sources among 68 distinct board keys |
| Latest saved run | 4 October, 06:21–06:24 UTC; outcome `ok`, errors 0, ingested 0, published 48 |
| Public dashboard payload | 38 records, all marked United States and predoc |
| Stored health counts | 51 listings / 51 published; public export is a routed subset |
| Automated tests | 308 passed, 1 failed, 15 subtests passed |
| Test coverage | 74% overall |
| Lint | Passed |
| Strict type checking | 128 errors in 25 files; CI treats this check as advisory |

The 51-versus-38 difference is not itself a defect: routing intentionally limits the website while directing other eligible opportunities to Telegram. Similarly, optional PhD/postdoc support is a configured policy choice. The issue is incorrect classification or metadata within that policy.

## Findings

P1 means materially incorrect opportunities, broken operational behavior, or unreliable recovery. P2 means misleading output or a narrower functional failure. Each entry includes a repair direction and a meaningful acceptance check.

### F01 — P1: published website records are repeatedly pending

[`pending_listings`](../../src/predoc_pipeline/core/db.py#L520) selects records with no Telegram message ID even when their status is already published. Website-only records normally have no Telegram message ID. [`_broadcast`](../../src/predoc_pipeline/pipeline.py#L631) checks Telegram delivery but does not use an existing X post ID to suppress another X publication. The saved run's zero ingested / 48 published is consistent with this path.

**Impact:** repeat publication counts and timestamps; duplicate X posts when X publishing is enabled. Duplicate remote X posts were not exercised in this audit.

**Repair:** track delivery independently per destination and only queue destinations still needing delivery. **Check:** run twice with a website-only record and mocked X; the second run sends nothing and preserves the first publication timestamp.

### F02 — P1: broad `field_implied` bypasses explicit off-topic evidence

[`_collect`](../../src/predoc_pipeline/boards/collector.py#L269) rejects unwanted detail fields only when `field_implied` is false. The Chicago Workday source covers an entire university tenant but asserts that its field is implied. The second PREDOC adapter also asserts it across broad outbound links. The stored-policy recheck uses shorter metadata and does not repeat the full detail-field check ([policy.py](../../src/predoc_pipeline/policy.py#L127)).

**Observed:** listing 48 is pediatric genetics/genomics; 44 is a public-health/biostatistics analyst; 28 is Freedman Lab neuroscience. They appear in the economics-oriented feed as predocs.

**Repair:** explicit negative job evidence must override a source prior; only narrowly scoped department sources may imply a field. Recheck the existing inventory with full text. **Check:** economics RA accepted; neuroscience, pediatric genetics and unrelated university RA rejected from the same tenant.

### F03 — P1: source country defaults prevent correction from the actual job

[`make`](../../src/predoc_pipeline/boards/scrapers/base.py#L64) fills source country/institution defaults. [`apply_heuristics`](../../src/predoc_pipeline/boards/heuristics.py#L221) only revisits location when region is missing; [`assign_region`](../../src/predoc_pipeline/boards/filter.py#L188) returns early for a preset region. This locks global aggregators to their configured country.

**Observed:** listing 31 is labeled US while its summary identifies the University of Zurich; listing 12 is NYU Shanghai but also US. These errors affect routing as well as display.

**Repair:** distinguish defaults from verified job locations; prefer vacancy evidence and flag conflicting evidence. **Check:** a Zurich job from a US-based aggregator becomes Switzerland/Europe, and Shanghai becomes China/Asia.

### F04 — P1: application date moves to the next calendar day

The extractor represents date-only deadlines as `23:59:59Z` ([heuristic.py](../../src/predoc_pipeline/extract/heuristic.py#L106)). The browser formats that instant in the user's local timezone ([index.html](../../docs/index.html#L1683)). In Tehran this moves the displayed date forward.

**Observed:** Federal Reserve listing 38 says October 15 in its summary but October 16 in the dossier.

**Repair:** retain date-only values as calendar dates; preserve a separately stated time and source timezone when known. **Check:** the same date displays identically in UTC, Tehran and Los Angeles; actual timed deadlines retain their intended instant.

### F05 — P1: an already-seen board URL prevents updates and reopened vacancies

[`_collect`](../../src/predoc_pipeline/boards/collector.py#L244) skips known URLs before detail enrichment. [`_pre_extract`](../../src/predoc_pipeline/pipeline.py#L319) also skips board URLs regardless of changed content. A previous rejection, corrected posting, reopened vacancy or annual reuse of a URL can remain invisible until the long seen-retention window ends. Exact-URL matches later add alternate sources without refreshing existing metadata ([pipeline.py](../../src/predoc_pipeline/pipeline.py#L469)).

**Repair:** use content fingerprints and a bounded recheck schedule, with explicit reopening and update paths. **Check:** a rejected URL edited into an eligible job is reconsidered; unchanged pages do not trigger unnecessary model calls or reposts.

### F06 — P1: source failures do not make public health degraded

The latest saved health lists 22 failed board keys but the run is `ok` with zero errors. Source scraping errors are separate from item errors in [`_run`](../../src/predoc_pipeline/pipeline.py#L952). [`export_health`](../../src/predoc_pipeline/state.py#L250) drops source messages, while the dashboard reads only the generated timestamp ([index.html](../../docs/index.html#L2407)). A recent failed run can therefore look healthy.

**Repair:** publish separate run status, source success/failed/empty/skipped counts, last successful scrape timestamps, and sanitized failure explanations. **Check:** one failed critical source yields degraded status; a fatal run never turns green merely because its health export is new.

### F07 — P1: the source verification command does not verify the boards

[`sources_verify`](../../src/predoc_pipeline/cli.py#L494) calls the ingest loader, which handles feeds/portals rather than the 75 board entries. In this configuration those three feed/portal templates are disabled. Its denominator also includes disabled entries.

**Repair:** verify the board registry through the same adapter path used by normal ingestion; distinguish disabled, inaccessible, reachable-but-empty and parse failure. **Check:** a broken board is reported by verification, and an intentionally empty seasonal board is separately identified.

### F08 — P1: pending-broadcast CLI fails at import

[`broadcast_pending`](../../src/predoc_pipeline/cli.py#L147) imports `RunStats` from `models`; the class is defined in `pipeline.py`. It also imports `build_telegram`, which needs reconciliation with the actual publisher interface. The first incorrect import prevents the command from reaching publishing.

**Repair:** correct imports and use the tested publication orchestration. **Check:** invoke the command offline with mocked publishers and a temporary database; it should process a pending record without an import exception.

### F09 — P1: committed recovery changes listing IDs

[`import_rows`](../../src/predoc_pipeline/core/db.py#L796) intentionally excludes exported `id`. The website exposes links such as `#listing38` based on these numeric IDs. Restoration after ID gaps or reordered records assigns new IDs, so existing links may stop working or open a different job. Seen-state export also omits the listing association.

**Repair:** preserve stable identifiers during recovery, or use a durable public key independent of SQLite row allocation. **Check:** restore records with IDs 7 and 42 and verify both old deep links still identify the same jobs.

### F10 — P1: quota accounting is incomplete across fresh runs and concurrent requests

Daily model usage is persisted in SQLite, but committed journal restoration does not preserve that table; a fresh scheduled database resets the local daily estimate. [`RateLimiter.acquire`](../../src/predoc_pipeline/core/ratelimit.py#L100) checks budget without reserving a daily call until `record`, so several workers can all consume the last available allowance. Extraction acquires once before a loop that may make multiple backend/key attempts ([gemini.py](../../src/predoc_pipeline/extract/gemini.py#L498)).

**Repair:** persist daily usage across fresh scheduled runs, reserve atomically before every outbound model attempt, and account for retry attempts. **Check:** only one worker can reserve the last request, and restoration retains today's usage. Provider-side rejection remains possible even with correct local accounting.

### F11 — P2: CSV export ignores the selected category

The CSV handler repeats some filtering but omits `currentKind` and selected sorting ([index.html](../../docs/index.html#L2322)).

**Observed:** selecting Central banks shows 2 of 38 positions, but exporting reports 38 positions.

**Repair:** share one visible-results selector between rendering and export. **Check:** category, search, dropdowns and sort produce exactly the rows and order exported. The observed toast establishes the count discrepancy; the browser download could not be inspected in this session.

### F12 — P2: unknown values are turned into affirmative claims

[`deadlineBadge`](../../docs/index.html#L1712) labels missing deadlines/days as Rolling, conflating rolling recruitment with unknown or invalid dates. The dossier substitutes “Institutional salary scale”, “Full-time / Fixed-term” and a flexible start date when those facts are absent ([index.html](../../docs/index.html#L2186)).

**Observed:** an advert containing the invalid “November 31” appears as rolling. These defaults also inflate the rolling-deadline analytics.

**Repair:** display “Not stated” or “Could not verify”; show rolling only when explicitly supported. **Check:** absent salary, invalid date and unstated contract remain unknown, while an explicit rolling advert is correctly labeled.

### F13 — P2: countdowns age with the export, not the viewer's date

[`_public_record`](../../src/predoc_pipeline/state.py#L145) exports an integer `days_left`. The browser uses that stored number rather than recomputing it. During missed runs or across midnight, displayed urgency becomes stale; elapsed 24-hour floors also differ from calendar-day labels.

**Repair:** compute countdowns from a documented date/time policy at render time, refresh at midnight, and show data age separately. **Check:** yesterday's payload displays today's correct remaining days without a new pipeline run.

### F14 — P2: qualification and software mentions become requirements

[`_extract_degree`](../../src/predoc_pipeline/extract/heuristic.py#L203) returns the first degree mention, not the minimum required degree. A statement about preparing for a PhD can override a later bachelor's requirement. [`_extract_tools`](../../src/predoc_pipeline/extract/heuristic.py#L231) treats every mention as required, and its C++ boundary expression misses normal “C++ and Python” text.

**Observed:** the Federal Reserve RA displays PhD minimum; other records have organizations or prose fragments as investigator names.

**Repair:** distinguish required, preferred and contextual mentions; validate investigator names; preserve unknowns. **Check:** “prepares for PhD; bachelor's required; Python preferred” yields bachelor's required and Python preferred, with C++ recognized when present.

### F15 — P2: JavaScript shells can be accepted as job descriptions

Generic detail fetching treats HTML text as successful evidence ([base.py](../../src/predoc_pipeline/boards/scrapers/base.py#L104)). The Workday URL recognizer supports `myworkdayjobs.com` but misses `myworkdaysite.com/recruiting/...` ([university_ats.py](../../src/predoc_pipeline/boards/scrapers/university_ats.py#L110)). Enrichment has no substantive-job-content threshold.

**Observed:** NYU Shanghai listing 12 has navigation/copyright text instead of a useful vacancy description.

**Repair:** support the relevant ATS URL families and validate minimum vacancy evidence. Quarantine shell pages as unverified instead of publishing confident summaries. **Check:** an iCIMS shell cannot produce a confirmed listing; a Workday recruiting URL resolves structured job details.

### F16 — P2: application links and institutions can come from aggregator context

[`coerce_listing`](../../src/predoc_pipeline/models.py#L827) falls back to the source page when an application URL is missing. The broad second PREDOC adapter also uses surrounding card context for institution.

**Observed:** listing 46 says Chicago Booth but its summary refers to Penn's Behavior Change for Good; its application/source is the PREDOC opportunities index. “Apply Direct” overstates what that URL provides.

**Repair:** keep employer, aggregator and application URLs distinct; follow vacancy-specific links and mark unresolved application routes. **Check:** two jobs on one index remain distinct and each links to its own application or clearly labeled advert.

### F17 — P2: browser history and modal state diverge

Opening a dossier writes the listing hash, but there is no corresponding hash/popstate synchronization ([index.html](../../docs/index.html#L2149)).

**Observed:** browser Back removes `#listing38` while the dossier remains open.

**Repair:** derive dialog state from the URL and handle Back/Forward consistently. **Check:** Back closes the dossier, Forward restores it, and a deep link opens the correct job once data loads.

### F18 — P2: browser fallback paths fail misleadingly

The copy-link error handler still reports “Link copied” when clipboard access fails ([index.html](../../docs/index.html#L2240)). A view-preference `localStorage` read is unguarded ([index.html](../../docs/index.html#L1654)); denied storage can stop main initialization. These are code-confirmed paths, not failures forced on the live browser.

**Repair:** show copy failure and offer selectable text; guard storage operations with safe defaults. **Check:** denied clipboard never claims success, and denied storage still loads and filters jobs.

### F19 — P2: the registry count and duplicate names obscure monitoring coverage

There are 75 board entries but six are disabled and `predoc_org` appears twice. [`_collect`](../../src/predoc_pipeline/boards/collector.py#L299) keys statistics by name, so one duplicate overwrites another's evidence. Credential-dependent/skipped sources further reduce meaningful coverage. The hero's fixed count cannot reflect these distinctions. The live Analytics view also says "75 institutions" ([rendering](../../docs/index.html#L2032)), confusing page entries with distinct employers.

**Repair:** enforce unique source IDs, consolidate duplicate adapters, and derive configured/enabled/healthy counts from runtime state. **Check:** duplicate names fail configuration validation and coverage indicators reconcile to registry and health.

### F20 — P2: uncertainty in reachability and recovery is swallowed

[`check_still_open`](../../src/predoc_pipeline/boards/heuristics.py#L243) uses the same null-like result for an inaccessible page and no evidence of closure; [`_verify`](../../src/predoc_pipeline/pipeline.py#L864) advances verification bookkeeping even when access fails. [`import_rows`](../../src/predoc_pipeline/core/db.py#L796) catches SQLite errors and continues, and counts attempted `INSERT OR IGNORE` operations as inserted. A partial restore can be reported without explaining dropped records.

**Repair:** distinguish open, closed and unknown; retain last successful verification separately from last attempt. Report and validate restore failures and actual inserted counts. **Check:** timeout leaves a job unverified; malformed or duplicate journal records produce accurate recovery diagnostics.

## Extended repository investigation

The following findings were added after tracing less-visible paths and running isolated reproductions. [reproduce.py](reproduce.py) contains offline evidence checks using temporary databases and mocked HTTP. It does not publish or modify production state. These checks assert the currently faulty behavior; they should be converted into tests of corrected behavior during implementation.

### F21 — P1: text similarity suppresses distinct employers and recruitment cycles

[`Deduplicator.find`](../../src/predoc_pipeline/core/dedupe.py#L151) returns a MinHash match before checking institution, role, investigator or deadline compatibility. Only the later fuzzy tier checks deadlines.

**Reproduced:** identical template text for Alpha University/economics/2026 and Beta University/finance/2027 returns `minhash:1@1.000`. Different vacancies can be permanently recorded as duplicates.

**Repair:** use text similarity to propose candidates, then require compatible vacancy identity; exclude shared navigation/boilerplate. **Check:** these two jobs survive independently while genuinely syndicated copies merge.

### F22 — P1: URL normalization merges semantically different addresses

[`_normalise_pct`](../../src/predoc_pipeline/core/urls.py#L64) decodes reserved escapes. A path containing the encoded character `%2F` becomes a real path separator. Query values are decoded by `parse_qsl` and decoded again by `_normalise_pct`. A second URL normalizer in [boards/utils/text.py](../../src/predoc_pipeline/boards/utils/text.py#L70) additionally drops `position`, which can be a vacancy identifier, and is used on the actual posting URL.

**Reproduced:** `/jobs/a%2Fb` and `/jobs/a/b` have the same canonical identity; `?id=%252F` and `?id=%2F` also collide.

**Repair:** decode only unreserved characters, normalize each query value once, and remove only proven tracking parameters. Keep one identity policy separate from clickable URLs. **Check:** encoded separators, nested escapes and vacancy-identifying parameters remain distinct.

### F23 — P2: deadline distance depends on argument order

[`days_between`](../../src/predoc_pipeline/core/timeparse.py#L85) uses `abs(timedelta.days)`, applying integer flooring before absolute value.

**Reproduced:** two timestamps an hour apart yield 1 day in one direction and 0 in the other. Near the configured deduplication window this changes matching decisions.

**Repair:** define elapsed-days or calendar-days semantics and calculate symmetrically. **Check:** swapping arguments never changes the result, including sub-day differences at the 14-day boundary.

### F24 — P2: X formatting does not enforce its stated character budget

[`format_tweet`](../../src/predoc_pipeline/publish/x.py#L60) replaces `lines[3]`, the institution line, when intending to shorten the title at index 4. Its final minimal fallback leaves institution length unchecked.

**Reproduced:** a model-validated listing produces 449 characters according to the repository's own counter, exceeding 280. Emoji/CJK weighting is an additional verification gap in the simple codepoint counter; the reproduced overrun does not depend on those rules.

**Repair:** allocate and validate the full final payload budget, and apply a correct weighted counting implementation. **Check:** maximum validated institution/title values, Unicode and links always yield a publishable payload.

### F25 — P2: robots decisions can cross origins; board traffic ignores the preference

[`PoliteClient._robots_for`](../../src/predoc_pipeline/ingest/http.py#L104) caches by a canonical hostname that strips `www`, and does not distinguish HTTP/HTTPS or ports. Those are separate origins and can have different robots files. The board HTTP client has no robots check at all, although pipeline settings advertise `respect_robots_txt` and apply it to feed/portal traffic.

**Reproduced:** a deny rule from `www.example.org` is reused for `example.org` without fetching its allow rules. Depending on order, either incorrect refusals or incorrect permissions can result.

**Repair:** cache per origin and apply a consistent request policy to board details and redirects. **Check:** different hosts/schemes/ports use their own rules; turning on the setting also affects board collection.

### F26 — P2: discovered URLs are fetched without a public-network boundary

[`HttpClient.request`](../../src/predoc_pipeline/boards/http.py#L83) follows links/redirects without rejecting loopback, private, link-local or credential-bearing destinations. Public index pages supply some of these URLs; broad link patterns are not a network safety boundary.

**Reproduced using a mock only:** `http://127.0.0.1/private` reaches the transport unchanged. No internal endpoint was accessed. This establishes the missing guard, not a demonstrated compromise; impact depends on the runner's reachable services.

**Repair:** validate schemes, hostnames, resolved addresses and every redirect against the intended public-source policy, including DNS changes. This is consistent with [OWASP's SSRF prevention guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html). **Check:** private destinations and public-to-private redirects are rejected before any connection.

### F27 — P1: transient bot failures permanently acknowledge user updates

[`telegram_sync`](../../src/predoc_pipeline/publish/bot.py#L269) advances its offset before handling an update, catches processing failures, and saves the advanced cursor regardless. `commands` is incremented before delivery, so reported counts do not establish successful replies.

**Reproduced:** update 77 receives four mocked 503 responses; saved offset is nevertheless 78. The next poll skips the failed request.

**Repair:** persist retryable processing state and acknowledge only durable outcomes. Account separately for received, answered and failed commands. **Check:** a temporary outage retries the same request later without reapplying already successful marks.

### F28 — P1: quota-stop handling discards other completed extraction results

[`run`](../../src/predoc_pipeline/pipeline.py#L1148) breaks out of `as_completed` at the first quota/rate-limit exception and cancels futures. Already-running futures still finish as the executor exits, but their successful results are not consumed or persisted after the break.

**Impact inferred from control flow:** paid/limited requests can complete with no saved listing, requiring repeat work next run. This path was reviewed statically; a full concurrent end-to-end reproduction remains to be added.

**Repair:** stop scheduling new work, cancel tasks that have not started, and drain/persist successful in-flight results. **Check:** a batch with one early quota failure and two successful in-flight responses retains both successes exactly once.

### F29 — P1: fresh workflow installation lacks the X posting dependency

[`XClient._get_oauth_session`](../../src/predoc_pipeline/publish/x.py#L186) requires `requests_oauthlib`. It is absent from base dependencies and all named extras in [pyproject.toml](../../pyproject.toml), and the scheduled workflow installs only `[portals]`.

**Impact:** configuring valid X posting credentials on a fresh runner still fails before the first post. An existing local installation can conceal the packaging defect.

**Repair:** declare the posting dependency in an explicit extra/base set and install it in the publishing workflow. **Check:** install exactly the scheduled dependency set in a clean environment and exercise OAuth session construction with dummy credentials and no network.

### F30 — P2: malformed successful model responses bypass heuristic fallback

[`Extractor.extract`](../../src/predoc_pipeline/extract/gemini.py#L561) calls `response.json()` outside the fallback/error-accounting block.

**Reproduced:** a mocked HTTP 200 HTML response raises `JSONDecodeError`, never calls the configured fallback and never records that request through the success path.

**Repair:** include transport decoding and shape validation inside the managed failure path, with accurate request accounting. **Check:** malformed 200 payloads invoke fallback or return a deliberate extraction error rather than an uncontrolled decoder exception.

### F31 — P2: single-file distribution is substantially stale and incomplete

The manifest in [compile_project.py](../../compile_project.py) verifies its embedded snapshot, not agreement with the current repository. Read-only unpacking verified the embedded checksum and found **104 embedded files, 58 differing from current files**, with four current Python modules missing: `routing.py`, `publish/x.py`, `utils/pdf.py` and `utils/__init__.py`. The snapshot's advertised generation date is 26 September.

The builder's include list also omits `docs/rss.xsl`, although exported RSS points to it, and omits the authoritative listing/seen journals. Treat state migration separately from packaging: do not copy personal feedback into a public distribution by default.

**Repair:** regenerate from a declared release revision, add manifest drift verification in CI, include referenced static assets, and document how state is initialized/migrated. **Check:** release source files and references match the materialized output. This audit did not regenerate the large artifact or overwrite a target checkout.

### F32 — P2: disabling Pages does not disable push-triggered deployments

[pages.yml](../../.github/workflows/pages.yml#L35) allows the deploy job whenever the event is a push, regardless of `ENABLE_PAGES`. That conflicts with its documented opt-in setting.

**Repair:** define which explicit manual overrides are allowed and apply the enable flag consistently to automatic events. **Check:** a docs push with `ENABLE_PAGES=false` does not deploy; authorized manual behavior remains explicit.

### F33 — P1: valid preference input can deadlock collection

Preference concurrency fields lack lower-bound constraints ([config.py](../../src/predoc_pipeline/boards/config.py#L72)). [`_scrape_all`](../../src/predoc_pipeline/boards/collector.py#L116) acquires a semaphore before entering its per-source timeout, so a zero-sized semaphore is never covered by that timeout. Detail and recheck concurrency have similar validation gaps.

**Reproduced:** `max_concurrent_sources=0` validates successfully and collection waits indefinitely; an outer timeout in the audit harness is needed to stop it.

**Repair:** validate positive concurrency/page sizes and sensible nonnegative limits/timing values at configuration load. **Check:** zero/negative concurrency is rejected with an actionable setting name before a run starts.

### F34 — P1: a first review date becomes a hard application deadline

[`extract_deadline`](../../src/predoc_pipeline/boards/utils/dates.py#L102) recognizes first review/review-begins labels alongside closing dates and returns the date before considering the rolling wording. Downstream expiration then closes the vacancy.

**Reproduced:** “First review: October 1, 2026. Applications accepted until filled.” on October 5 returns an October 1 deadline.

**Repair:** store review dates separately from hard closing dates and preserve explicit rolling status. **Check:** the example remains open after first review; an explicit hard closing date still expires.

### F35 — P2: a flexible expected start is treated as proof of closure

[`apply_heuristics`](../../src/predoc_pipeline/boards/heuristics.py#L218) and open-job rechecks infer closure when a start date is sufficiently old and no future deadline exists, without honoring flexibility or explicit until-filled language.

**Reproduced:** a July 2026 expected start, explicitly flexible and open until filled, is marked closed when checked on October 5.

**Repair:** distinguish stale-ad suspicion from confirmed closure. Require explicit closure evidence or mark the record for verification. **Check:** flexible rolling vacancies stay unverified/open unless their ATS or advert actually closes them.

### F36 — P2: welcoming international applicants becomes explicit visa sponsorship

[`detect_visa`](../../src/predoc_pipeline/boards/heuristics.py#L53) treats international welcome and relocation assistance as positive sponsorship signals. [`visa_status`](../../src/predoc_pipeline/extract/heuristic.py#L82) upgrades the generated note to `explicit`. Conversely, citizenship preference is mapped to `not_offered`, despite preference and sponsorship availability being different facts.

**Reproduced:** “International applicants are welcome. Relocation assistance provided.” produces an explicit visa status with no sponsorship commitment in the text.

**Repair:** separate eligibility, preference, relocation and explicit sponsorship evidence. **Check:** international welcome alone remains unknown; an actual sponsorship commitment is explicit; citizen priority alone does not establish no sponsorship.

### F37 — P2: the stdlib similarity fallback changes deduplication decisions

[`fuzzy.ratio`](../../src/predoc_pipeline/core/fuzzy.py#L47) uses RapidFuzz's ratio when installed but normalized Levenshtein distance in the fallback. These are different metrics, not equivalent implementations.

**Reproduced:** `abcd` versus `abxcd` scores 88.89 with RapidFuzz and 80 with the stdlib fallback, crossing the default 88 threshold. The stdlib-only CI lane therefore cannot establish identical behavior to the installed production dependency.

**Repair:** implement equivalent semantics or explicitly treat the backends as separate policies with calibrated thresholds. **Check:** representative near-threshold cases have a documented consistent decision across supported environments.

### F38 — P2: narrow mobile layouts clip navigation and overflow horizontally

**Observed:** at a 360 × 800 browser viewport, the document's available width was 345 pixels and its scroll width was 410 pixels. The header's GitHub link and theme control extended beyond the visible right edge. The screenshot confirmed clipped navigation; this is more than a hypothetical breakpoint concern.

[`header .wrap`](../../docs/index.html#L128) places the brand and navigation on one fixed-height flex row. [`nav`](../../docs/index.html#L162) does not wrap; the mobile rules only reduce link spacing ([breakpoints](../../docs/index.html#L1338)). [`body`](../../docs/index.html#L107) clips horizontal overflow, hiding the excess instead of making the controls fit.

**Repair:** provide a compact or wrapping navigation at narrow widths and constrain overflowing listing content. **Check:** at 320, 360 and 390 pixels, every navigation control is visible and operable, and document scroll width does not exceed client width. Also check the dossier and filter controls with keyboard navigation.

## Investigation coverage and remaining limits

| Area | Review performed | Residual limit |
|---|---|---|
| Dashboard and public outputs | Live filtering, dossier, CSV count and Back behavior; no-result search/clear, Cards and Analytics switching; 360-pixel mobile layout; source rendering/export/date paths; saved data consistency | No complete breakpoint or screen-reader audit; downloaded CSV contents not captured |
| Board registry/adapters | All registry entries inventoried; shared collector/detail paths, ATS, links, RSS, LinkedIn, date/location/text logic traced | Every external source was not fully scraped live; saved failures lack root-cause messages |
| Ingest feeds/portals/social | HTTP/cache/robots, JSON-LD/detail following, collection selection and optional dependency paths reviewed | Authenticated social providers and paid API paths not called |
| Extraction/policy/models | Backend/key retries, fallback, quotas, schema/coercion, relevance, classification and metadata paths reviewed | Full provider contract validation requires separate mocked fixtures per API version |
| Core/persistence | URL identity, fuzzy/MinHash matching, time parsing, pending/delivery, imports, state export and recheck paths reviewed | Crash/recovery failure-injection matrix and large-volume stress tests remain |
| Bot/publish | Ownership checks, commands/callbacks, feedback persistence, cursor failures, Telegram/X formatting and delivery paths reviewed | No remote publishing; partial X-thread failure and very large Telegram pages need regression fixtures |
| Automation/distribution | All four workflows, dependency sets, shared concurrency and bundled-materializer drift reviewed | No deployment or remote workflow dispatch |
| Baseline quality/security | 59 production/tool Python files parsed; risky execution API scan, committed-file secret-pattern locations checked; existing test/lint/type suites | Syntax and pattern scans do not prove security; no secrets found by those specific patterns |

Offline CLI smoke passed. The golden gate evaluation passed its 30 fixtures with precision/recall 1.0, but those fixtures do not cover the real biomedical/location errors or the newly reproduced paths. The evidence harness passed all 19 defect checks and its own lint check. Existing production tests and lint were not changed.

Other bounded follow-up cases: partial X threads lose already-created tweet IDs on a later failure; configured Telegram page sizes are not limited by rendered message length; numeric date interpretation should follow source locale; expired flags can lag dashboard-only regeneration; XML control characters and spreadsheet-formula-leading CSV fields need output-boundary fixtures. These are reviewed risk paths, not asserted live failures.

The root cause of each of the 22 failed external sources still requires an adapter-specific live check with retained diagnostics. Review/repair F06 and F07 first so that expanded monitoring produces trustworthy evidence instead of another inflated count.

## Operational and quality gaps

- The workflow runs every six hours, while older text describes daily morning updates. Derive cadence and repository links consistently. The frontend GitHub constant/footer, README and project metadata still contain predoc-not-org references despite the Collegeum remote.
- Successful zero-result sources warrant investigation: academictransfer, bis, cemfi, ifo, niesr, ny_fed, rwi_essen, somma, uab_ufae, uzh and zew. `cemfi` and `uab_ufae` explicitly allow seasonal emptiness; empty does not automatically mean broken. Detect substantial changes relative to each source's history.
- Latest failed source keys: akadeus, bde_spain, carlo_alberto, cemfi_madrid, diw_berlin, ecb, eth_lawecon, eui_florence, fed_board, ifs, iies_stockholm, insead, iwh_halle, max_planck_econ, nber_ras, opportunity_insights, poverty_action, pse, pse_paris, stanford_siepr, tobin_yale and wzb. Saved health omits their messages, so it cannot establish individual failure causes.
- Strict type errors include optional dependency/stub issues and Pydantic constructor checking as well as genuine interface mismatches. The count is a quality signal, not 128 demonstrated runtime bugs. Prioritize CLI and publishing signatures, then tighten CI.
- The failing test is `test_deadline_label_same_day`: it builds “today” from host-local time but the formatter uses UTC. It failed around the local/UTC date boundary. This is a timezone-sensitive test fixture; it does not independently prove the production formatter has the dashboard's date-shift defect. Freeze a single clock/timezone in the fixture and add real multi-timezone display checks.
- Dates without a year can be silently rolled into the next year. The LEO record's June 30 / Tuesday text and inferred 2027 date disagree on weekday. Preserve ambiguity and verify the official posting rather than declaring it current solely from a rolled date.

## Recommended implementation sequence

1. Fix destination-specific pending state and source health reporting; repair verification and pending-broadcast entry points.
2. Tighten field/location evidence and quarantine the identified incorrect or unverified records for review. Do not infer new facts to repair them.
3. Correct calendar dates, unknown-value labels, shared CSV filtering and history behavior.
4. Preserve durable IDs and quota state; add update/reopening semantics and explicit verification uncertainty.
5. Validate unique source IDs, repair failed/disabled sources, then enable the expansion shortlist in small batches with recorded adapter fixtures.

Use acceptance checks above as regression scenarios, rather than tests that merely repeat implementation details. Include an end-to-end browser path covering filters → dossier → Back → filtered CSV, and a two-run publication/recovery scenario.

## Limits and preserved state

No live Telegram/X posts, paid model requests, credential changes, pushes or deployment were performed. Current external ATS access and bot publishing were not fully exercised with credentials. This is a broad evidence-based audit, not a claim that every possible defect has been exhausted. Existing user changes (`uv.lock` deletion, `.codegraph/`, `.statamcp/`) were preserved. Companion source research is in [source-expansion.md](source-expansion.md).
