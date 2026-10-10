# Collegeum consolidated audit — 5 October 2026

This report merges the [original audit](audit.md), [boundary pass](audit-addendum.md), and [supplied report](imported-report.md). It contains **67 distinct findings: 28 P1 and 39 P2**. F01–F51 retain their original identifiers; F52–F67 add validated defects or explicitly conditional risks. Severity reflects impact, not a claim that every failure has occurred.

Reviewed website: [Collegeum](https://amirrezafarnamtaheri.github.io/Collegeum/). Repository visibility is **public**, independently checked through GitHub. The currently tracked feedback file contains zero marks. An earlier statement that the repository was private misread `.private=false` and is corrected here.

## Evidence and verification

The earlier evidence scripts passed 19 and 14 checks. The [merge evidence script](reproduce-merged.py) passes 15 additional checks, including two extensions of existing findings; [captured results](merged-evidence.json) preserve the output. These assert the presence of defects, not successful repairs. Merge-script lint passes. The latest prior full test run passed 309 tests and 15 subtests; production files have not changed during this merge, so that run was not repeated. Passing existing tests does not invalidate the uncovered behaviors.

Live keyboard checks support F60. Workflow/provider claims were checked against current primary documentation. Historical output snapshots remain dated evidence; neither a saved failure nor an empty source proves its present external availability. No paid model requests or remote writes were used.

Primary references: [OpenAI JSON mode](https://developers.openai.com/api/docs/guides/structured-outputs#json-mode), [GitHub concurrency syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency), [larger concurrency queues](https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/), [Mem0 memory API](https://docs.mem0.ai/api-reference/memory/add-memories), and [GitHub Pages availability](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages).

## Extensions to existing findings

- **F01:** repeated web pending records also rewrite publication metadata and churn journal output. Do not infer duplicate successful X posts where the existing X post ID prevents them.
- **F22:** global removal of `cid`, `sid`, `ref`, `source` and `src` can remove functional identifiers. The new check reproduces collision of two different `cid` URLs.
- **F31:** the bundle also omits favicon.svg, logo.svg, rss.xsl and architecture.html, as well as the previously documented runtime modules and stale embedded files.
- **F49:** beyond the old extraction prompt, `pipeline._post_extract` reuses the title rejection regex without the configured PhD/postdoc allowances. An approved PhD extraction is discarded with `title:phd-studentship` in the new check. The empty dashboard category alone would not prove this cause.
- **F34/F35:** preserve the distinction between priority/review dates, hard deadlines and expected starts. A seasonal start or a weekday on a yearless deadline is contextual evidence, not sufficient proof that a vacancy has closed.

## Findings

P1 means materially incorrect opportunities, broken operational behavior, or unreliable recovery. P2 means misleading output or a narrower functional failure. Each entry includes a repair direction and a meaningful acceptance check.

### F01 — P1: published website records are repeatedly pending

At the audited revision, [`pending_listings`](../../src/predoc_pipeline/core/db.py#L520) selects records with no Telegram message ID even when their status is already published. Website-only records normally have no Telegram message ID. The saved run's zero ingested / 48 published is consistent with this path. The X publishing helper checks an existing X post ID, so this finding does not establish repeated successful X posts.

**Impact:** repeat publication counts and timestamps, journal churn and retries after failed X publication. Duplicate successful remote X posts were not demonstrated.

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


## Findings added while reconciling the supplied report

### F52 — P1: Non-Gemini extraction lacks a complete JSON/output contract

**Evidence:** The OpenAI-compatible body requests json_object while normal prompt messages contain no JSON instruction or complete field contract. The Anthropic request also lacks an output schema. The offline check verifies both bodies. OpenAI documents that JSON mode requires JSON in context and does not enforce a schema. Provider behavior varies; this does not prove the cause of every historical missing-field rejection.

**Code references:** `extract/gemini.py:315,365; extract/prompt.py:22` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Specify the complete output contract and use supported structured output; validate provider-specific requests.

### F53 — P1: Employer regex matches names inside unrelated words

**Evidence:** The double-escaped word class allows Fed inside Federico. University of Naples Federico II is reproduced as institutional/web.

**Code references:** `routing.py:46` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Use correct word boundaries and test legitimate abbreviations, nested words and case variants.

### F54 — P2: Boilerplate becomes economics discipline tags

**Evidence:** Work environment, legal authorization, microscopy and trade-offs produce International Trade, Environmental and Energy Economics, and Law and Economics tags.

**Code references:** `extract/heuristic.py:35,72` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Classify research content and structured disciplines; exclude employment boilerplate.

### F55 — P2: PI extraction crosses field boundaries and presentation invents titles

**Evidence:** Professor Amanda Gilmore Sponsoring Institution yields Amanda Gilmore Sponsoring. The UI blindly prefixes Prof., including organization/group values.

**Code references:** `boards/heuristics.py:94; docs/index.html:1880` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Stop at field boundaries; distinguish people, groups and organizations; preserve verified titles.

### F56 — P2: Geographic homonyms override contextual locations

**Evidence:** Durham, NC; York University; and Kent State University all resolve to United Kingdom. Hong Kong resolves to Other/Other, losing the explicit place.

**Code references:** `boards/utils/geo.py:180,192` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Prioritize explicit location fields and contextual disambiguation; preserve unknown place text.

### F57 — P2: Doctoral enrollment in descriptions defaults to predoc

**Evidence:** A Research Assistant whose description requires enrollment as a doctoral candidate and completion of a PhD dissertation is classified predoc. Description checks cover postdoc but not this doctoral condition.

**Code references:** `routing.py:51` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Separate predoctoral employment from doctorate-enrolled roles using explicit title and description evidence.

### F58 — P2: Salary parsing corrupts European amounts and dollar currencies

**Evidence:** EUR 3.776,10 per month becomes 3.7761 EUR/month. CAD $60,000/year becomes USD.

**Code references:** `models.py:473` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Parse regional numeric formats and give explicit currency codes precedence over dollar signs.

### F59 — P2: Invisible characters survive normalization and alter identity

**Evidence:** U+200B survives squish, and the normalized content hashes differ. A live title contains this character; specific duplicate/sort consequences remain conditional.

**Code references:** `core/textproc.py:88` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Normalize appropriate invisible formatting characters consistently before search and identity construction.

### F60 — P2: Rows and cards lack keyboard activation

**Evidence:** Live Enter and Space checks leave a focused row's aria-expanded false. Cards lack focusability and button semantics; click handlers alone do not provide keyboard activation.

**Code references:** `docs/index.html:1876,1911,1937,1966,2247` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Use native buttons or complete accessible focus, activation and state handling; test row/card/modal keyboard journeys.

### F61 — P1: Replaying an identical callback can undo a saved mark

**Evidence:** The same callback toggles the existing status. Saving marks, losing the newer cursor, then replaying that callback clears the mark in the offline check. A failed push alone is insufficient to establish this outcome when both state files roll back together.

**Code references:** `publish/bot.py:281,282,355` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Persist callback IDs and state atomically; separate retries from deliberate second taps.

### F62 — P1: Shared default concurrency can replace a pending pipeline run

**Evidence:** Both workflows share a group with cancel-in-progress false and the default single pending slot. GitHub replaces a previous pending run when another arrives. This is a supported failure mode, not an observed cancellation.

**Code references:** `.github/workflows/pipeline.yml:23; .github/workflows/telegram.yml:21` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Retain serialization for shared state and use queue: max or a coordinator. Splitting groups without another lock introduces races.

### F63 — P2: Canned English summaries invent research duties

**Evidence:** An administrative-support-only German snippet becomes an English statement claiming empirical research, academic coursework and preparation for doctoral studies.

**Code references:** `models.py:762` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Translate factual source content or state that detail is unavailable; avoid invented role facts.

### F64 — P1: One HTTP 404 permanently removes future open-status checks

**Evidence:** A mocked first 404 closes the listing. A later healthy response is never requested because closed listings are excluded from rechecks.

**Code references:** `boards/heuristics.py:243; pipeline.py:907; core/db.py:590,604` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Use confirmation and recovery states for ambiguous transport failures; provide periodic reopening checks.

### F65 — P2: Restored MinHash seeds use different text from new listings

**Evidence:** Restore drops signatures; seeding uses summary alone, whereas new signatures use title plus summary. A reproduced pair has Jaccard 0.5078125 instead of identical signatures. Other dedupe tiers can still match.

**Code references:** `core/db.py:789; core/dedupe.py:123; pipeline.py:490` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Use one versioned canonical dedupe representation for insertion and restoration.

### F66 — P2: Memo backend defaults to an unrelated local chat endpoint

**Evidence:** With a placeholder memo key, the constructed backend targets localhost:8000/v1/chat/completions. The nonempty custom default shadows the Mem0 fallback; Mem0's documented memory API does not match this chat request contract.

**Code references:** `extract/gemini.py:801; settings.py` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Require an explicit validated compatible endpoint, or implement a documented integration and remove misleading defaults.

### F67 — P1: Future personal application marks are committed into a public repository

**Evidence:** GitHub reports repository visibility public; feedback.json is tracked and workflows persist personal mark metadata. The current file has zero marks: no existing application-history leak was observed. Using the feature and publishing populated state would expose titles, institutions, URLs and applied timestamps.

**Code references:** `data/feedback.json; .github/workflows/telegram.yml` (Python modules are under `src/predoc_pipeline/`; other paths are repository-relative).

**Repair and verification:** Keep personal state in private storage; ensure public exports and commits exclude it. Pages does not universally require a public source repository.

## Reconciliation of the supplied report

| Supplied claim | Consolidated disposition |
|---|---|
| C1, web listings repeatedly pending | F01; confirmed, with publication metadata consequences |
| C2, PhD/postdoc feature dead | F49 extension; two concrete rejection paths verified; avoid universal conclusions from the empty chip |
| C3, outdated scope / incomplete provider contract | F49 and new F52; missing-field rejection causation remains a hypothesis |
| C4, employer regex | New F53; Federico II reproduced |
| C5, deadline semantics | F34/F35; year inference and seasonal ambiguity remain explicit limitations |
| H1, H6 | F02 and F03; broad field/country source defaults |
| H2, H4, H5 | New F54, F55, F56; tags, PI fields and homonyms reproduced |
| H3 | F14; incidental degree mentions are already covered; do not treat every mention as a requirement |
| H7 | F49 plus new F57; doctoral role description reproduced; seniority and degree policy need explicit product rules |
| H8 | F16; aggregator apply links covered. A shortened link or error query alone does not establish a dead vacancy |
| H9 | F15 and new F63; shell text and invented generic duties are separate mechanisms |
| H10, H11 | New F58 and F59; salary and zero-width normalization reproduced |
| H12, J-PAL/IPA contradiction | Configuration/documentation drift; current intended exclusion policy requires a decision. Do not delete listings based only on an old comment |
| H13 | F19 and F16; duplicate names and broad discovery patterns already counted |
| Broadcast import, verifier, missing X dependency | F08, F07, F29. Current verifier templates are two feeds plus one portal, all disabled: three templates, not two |
| Fed Board URL typo | Repair lead: registry uses singular assistant; the official plural assistants page exists. The attempted singular-page probe did not establish an HTTP status, so permanent failure is not newly asserted |
| X length/header | F24; category wording should follow the classified role |
| Privacy | New F67; future public-state exposure is supported, current marks are empty. Public repository requirement is not universal |
| Callback replay | New F61; partial persistence/cursor loss reproduced. Failed push alone can roll back both files and does not prove an undo |
| Shared workflow concurrency | New F62; keep shared-state serialization. A simple group split is unsafe |
| Schedule drift / free-minute estimates | Documentation/operational gap; six-hour cron contradicts daily instructions. Recompute estimates from actual duration and frequency |
| Quota-stop red status / rate defaults | Operator-policy gap plus F10/F28; limits depend on provider and plan, so constant 429s cannot be asserted from defaults alone |
| Push-triggered Pages | F32; current repository is public, so a private-repository failure is not observed here |
| Single-response closure | New F64; closed items leave rechecks |
| Reused URLs / cache starvation | F05 and F46/F47; CI cache persistence differs from a local SQLite cache |
| Restore errors / seed mismatch | F45 and new F65; signature mismatch does not prove every duplicate will evade other tiers |
| Tracking identifiers | F22 extension; identity collision reproduced |
| Compliance documentation and browser headers | F25 and documentation drift; no legal violation inferred without site-specific terms |
| Memo provider | New F66; wrong default endpoint reproduced |
| Storage, history, countdown, CSV, IDs, source counts | F18, F17, F13, F11/F42, F09, F19 |
| Keyboard access | New F60; row activation checked live |
| Visa/remote rates | F12/F36; unknown values must remain unknown |
| Client-side sector fallback | Unbounded substring fallback is an additional repair target related to F53; server fallback activation is conditional |
| Contact email differences / unused constants | Housekeeping; intended address needs confirmation, not a newly verified runtime defect |
| Schema/PRAGMA/test count documentation | Historical documentation drift; use implementation and current executed checks as authority |
| Bundle omission / missing PHONY targets / limiter defaults | F31 plus low-impact housekeeping; differing defaults merit explicit construction documentation |

The supplied report is preserved verbatim for provenance. Its suggestions to purge seen rows, split workflow groups or activate sources are proposals, not actions performed here. Permanent seen-state changes require a carefully scoped migration and replay plan.

## Source expansion and monitoring coverage

The saved registry has 75 board entries, 69 enabled, and duplicate source names; entries are not equivalent to 75 successfully monitored unique pages. The earlier snapshot contains 22 errors and 11 successful zero-result sources. Their failure causes still need source-specific probes: timeouts do not establish IP blocking, and zero items can mean no vacancies or selector failure.

Keep the [19 previously researched official URLs](source-expansion.md) as the verified candidate shortlist. The supplied report's broader institution list is now a separate [source research backlog](source-research-backlog.md). It is not added to the enabled registry. Distinguish new endpoints from institutions already represented, prefer structured feeds/APIs, test vacancy-detail selection, and avoid broad department assumptions.

## Repair order and review limits

1. Fix web pending selection, scope consistency, routing boundaries, dependencies and trustworthy health reporting.
2. Protect personal state, make callback persistence replay-safe, and retain workflow serialization while improving queue behavior.
3. Fix closure/reopening decisions, durable restoration, cache replay and canonical identity.
4. Correct salary, geography, PI, discipline, degree and summary extraction; preserve uncertainty in dates and eligibility.
5. Repair keyboard/navigation, exports and output-size boundaries.
6. Probe failed sources and verified candidates before enabling more ingestion.

This merge does not claim exhaustive absence of other defects. Live external source status, provider-specific enforcement, rate limits, historical rejection causation and ambiguous source policy remain bounded uncertainties. Existing production code, preferences, source registry and remote resources are unchanged; findings are review artifacts, not deployed fixes.
