# Final report: predoc-pipeline / Collegeum review

**How I did this.** I read the code, config, workflows, fixtures, the committed state (`listings.ndjson`, `seen.ndjson`, `health.json`, `listings.json`) and `docs/index.html`. I did not run the code. Where I infer a bug from reading the code, I say so. Where the committed data confirms it, I cite the evidence.

**On the source expansion.** My live searches were thin: they confirmed little beyond that AEA JOE exists and INOMICS exposes RSS. Everything in Part 2 beyond that is a candidate list from my own knowledge and is **unverified**. It needs a live probe before you add any entry.

---

## Part 1: Bugs and flaws, by severity

### Critical: they break core behaviour

**C1. Web-routed listings are re-processed on every run.**
- `Database.pending_listings()` selects `telegram_message_id IS NULL`, and web listings are published with a NULL message id by design.
- Every run therefore re-selects all ~40–50 web listings. It re-checks each link (bit.ly 40+ times per run), re-runs the X post path, and calls `mark_published` again.
- Evidence:
  - Every old row in `listings.ndjson` has `published_at` and `last_checked_at` set to `2026-10-04T06:23:57Z`.
  - The latest `health.json` run shows `ingested: 0` but `published: 48`.
- Consequences:
  - Every run rewrites the journal and dirties the commit.
  - The "N consecutive empty runs" alert can never fire, because `published` is never 0.
  - The `first published` timestamp is lost.
  - Failed X posts are retried every run and push the outcome to `partial`.
- Fix: add a `channel` column, or restrict pending to `status IN ('pending','unpublished')`. Don't rely on `telegram_message_id IS NULL`.

**C2. The PhD/postdoc routing feature is dead.**
- `_post_extract` applies `gating._TITLE_RE` with no `allow_phd`/`allow_postdoc` flags.
- The LLM prompt also tells the model to reject postdocs and PhD studentships.
- Evidence: all 38 entries in `listings.json` have `kind: predoc`. The "Postdocs & PhDs" chip is always empty, and `seen.ndjson` is full of `not a vacancy: postdoc` and `phd_studentship`.
- No test covers this path. The e2e test excludes the US and asserts the dashboard count is 0.

**C3. The LLM prompt contradicts the current scope and is incomplete for non-Gemini backends.**
- `prompt.py` still says "outside the United States".
- `seen.ndjson` contains about 20 permanent rejections such as "Position is located in the United States… feed only tracks positions outside the US". These were valid US predocs.
- Only Gemini receives the JSON schema. The OpenAI-compatible and Anthropic bodies carry no schema, and the prompt never names `title`, `institution`, `country`, `deadline` or `disciplines`.
- That is a plausible root cause of the mass `missing title or institution` rejections, which are also marked seen permanently.
- OpenAI and Groq `json_object` mode also expect the word "JSON" in the messages.
- Fix:
  - Update the prompt scope.
  - State the output keys explicitly.
  - Don't `mark_seen` on `CoercionError` or LLM-only rejections for curated boards.
  - Purge the bad rows. For example, delete seen rows whose reason contains "United States" or "outside".

**C4. `routing.py` has a regex escaping bug.**
- `re.compile(r"(?<![\\w-])" + …)` is a raw string, so `[\\w-]` is a class of `\`, `w` and `-`. The word-boundary guard is effectively absent.
- `Fed`, `UN`, `CRA`, `RAND`, `BIS` and `ILO` therefore match inside other words. "University of Naples **Fed**erico II" would be classed as a central bank and routed to the web.
- `boards/filter.py` has the correct single-backslash form.

**C5. Deadline semantics are wrong in two ways.**
- *Soft dates become hard deadlines.*
  - "First review date Oct 7, then rolling" (Columbia, Notre Dame, Booth "Nov 15, then rolling", Brown "priority Oct 31") is stored as a deadline.
  - `expire_past_deadline` then removes roles that are still open.
  - The "Closing ≤ 7 days" chip is also misleading for these.
- *Year-less dates roll forward.*
  - `_mk` assumes the next occurrence. The Notre Dame LEO ad says "Tuesday, June 30th". June 30, 2026 was a Tuesday, yet it is stored as 2027-06-30 and shown live.
  - The Fed Minneapolis ad ("start Spring/Summer 2026") is still live. `start_date_passed` handles only month+year, not seasons.
- Fix: add a `deadline_kind` field (hard, review or rolling). Use the weekday and the posted date to infer the year. Never auto-expire soft deadlines.

### High: wrong output reaches users

| # | Finding | Evidence |
|---|---|---|
| H1 | `field_implied = true` on university-wide Workday boards (UChicago, Brown) skips the field check. | Biomedical roles are published: pediatric genetics, public health, a neuroscience lab. They carry hallucinated "Labor Economics" tags. |
| H2 | `disciplines_for` scans page text, so "work environment", "legal authorization", "micro-scopy" and "trade-offs" produce tags. | "Environmental and Energy Economics" and "Law and Economics" appear on unrelated ads. |
| H3 | `_extract_degree` takes the first degree word anywhere. "PhD programs" yields `phd`, and "MA" (Cambridge, MA) yields masters. | Fed Board RA, Harvard CID and a neuroscience RP all show `min_degree: phd`. The modal then says "Doctorate (PhD)" for predocs. |
| H4 | Principal investigator (PI) parsing leaks garbage, and the UI prefixes "Prof." blindly. | A 300-character sentence (Brookings), "Amanda Gilmore **Sponsoring**", "Primary investigators (PIs)…", "Federal Reserve Board", "Multiple". |
| H5 | `detect_location` takes the earliest match, with ties broken alphabetically. It confuses US campuses abroad and homonyms. | NYU-Shanghai is classed as US. "Durham, NC" goes UK, and the same applies to "York University" (Toronto) and "Kent State". The "Other" country is always the literal string "Other", so CUHK shows `country: ""`. |
| H6 | Source-level `country` overrides the page's real location. | J-PAL is stamped "United States" while its summary is about Zurich. |
| H7 | Job-type misclassification: `kind` comes from the title only, and `exclude_phd_positions = false` also disables the "PhD required" rule. | Vienna "University Assistant Predoctoral" ("completing a PhD dissertation"), Ilmenau "Research assistant (f/m/d)" (own dissertation) and a UCL "Research Fellow" (£44–54k, `min_degree: phd`) went to the non-US predoc channel. "Senior Community-based Research Analyst" also passed. |
| H8 | Bad apply URLs. | Booth coordinator's `apply_url` is the predoc.org index page. BFI's is `greenhouse…/bfiprep?error=true` (a not-found redirect that `detect_closed` misses). Several are raw `bit.ly` links. |
| H9 | Summary corruption: `apply_heuristics` overwrites a short structured snippet with raw page text. | NYU Shanghai summary is "Click to see full trail Careers at NYU Shanghai…". German ads get a canned summary that invents role details ("academic coursework", "suitable for candidates preparing for doctoral studies"). |
| H10 | `parse_salary` strips commas, which breaks European number formats. | The Vienna ad shows `salary_min: 3.7761` for "EUR 3.776,10". `$` is always mapped to USD. |
| H11 | Zero-width spaces survive normalisation. | `"Research Assistant​"` (U+200B) is in a title, which affects dedupe and sorting. |
| H12 | Config contradictions on J-PAL. | `sources.toml` and `CHANGES.md` say J-PAL and IPA were removed and blocked. But `jpal_global` and `poverty_action` are still defined, and `excluded_employers = []`. A J-PAL listing is live (id 31). |
| H13 | Two `[[board]]` entries share `name = "predoc_org"`. | Stats overwrite each other. The second entry's pattern `…\.(edu\|org\|com\|gov)` matches nearly every link, so the index page itself is picked up as a "job" (C-listing 46) and produces dozens of `not_a_vacancy` rejections. |

### High: code paths that crash or cannot work

- `predoc-pipeline broadcast-pending` imports `build_telegram` from `publish/telegram.py`, which does not define it, so it raises `ImportError`.
- `sources verify` loads only `[[feed]]` and `[[portal]]`. Those are two disabled templates, so it never checks the ~70 boards. The README, Makefile and REVIEW all call it the mandatory first command.
- `fed_board` points to `…careers-research-assistant.htm`, but the live ad URL is `…assistants.htm`. The source fails permanently.
- `requests-oauthlib` is imported by the X client but is not in `pyproject.toml`. With the four keys set, every post raises `XError`.
- X tweet length uses `len()` with URLs counted as 23. X counts emoji as 2, and the format uses six or more emojis, so tweets can exceed 280. The header "New Pre-Doctoral Opening" is also hard-coded for PhD, postdoc and bank posts.

### Medium: reliability, security, privacy

- **Privacy leak.** `data/feedback.json` stores titles, institutions, URLs and applied-timestamps from your 📝/✅/❌ taps. The file is committed, and the repo must be public for Pages and free minutes. Your application history would be public.
- **Telegram taps are not idempotent.** Taps toggle ("tap again = undo"), but the update offset is committed only at job end. If the push fails or the job dies, the updates replay and silently undo the marks.
- **Workflow concurrency.** Pipeline and sync share one concurrency group. GitHub keeps only the latest pending run per group, so a queued daily run can be dropped by a later sync run.
- **Schedule drift.** `pipeline.yml` cron is `0 */6 * * *`, but README, SETUP, OPERATIONS and the file's own header say daily at 04:00. The free-minute estimates are therefore wrong.
- **Quota-stopped runs show red.** The run exits 1 on `quota-stopped`, although OPERATIONS calls that normal.
- **`pages.yml` is not off by default.** Its `if:` allows every `push`, so it fails on private repos on each `docs/**` push.
- **Rate-limit defaults.** `Settings` defaults to 200 RPM and 10,000 RPD, which contradicts the "conservative defaults" claim and will trigger constant 429s on free tiers. The first 429 with one key aborts the whole run, even though a heuristic fallback exists.
- **Closures are irreversible.** One 404 or 410 from a CDN or bit.ly permanently closes a listing, and `mark_closed` has no reopen path. Require two consecutive confirmations.
- **Recall gaps.**
  - Board URLs are judged once, forever.
  - `listing_by_url` matches closed and expired rows, so annually reused URLs (PI pages, `ra-position.html`) are never re-announced.
- **`http_cache` lives only in the gitignored SQLite file.** Conditional GET never helps on CI. Locally it can starve items after a quota stop, because a 304 hides the unprocessed entries.
- **Dedupe seed mismatch.** Journal restore drops MinHash signatures. `Deduplicator.seed` rebuilds them from `summary` alone, while incoming items use `title. summary`. Tier-2 scores are skewed.
- **`import_rows` can silently drop records.** A `sqlite3.Error` on an unknown column skips the row, and the counter still increments.
- **Tracking-param list is too aggressive.** `ref`, `source`, `src`, `cid` and `sid` are real identifiers on some ATSs, so distinct vacancies could merge.
- **Compliance drift.**
  - COMPLIANCE.md says commercial boards are default-off, but the `linkedin` board is ON.
  - The board client rotates browser User-Agent strings and `Sec-Ch-Ua` headers and does not consult robots.txt.
  - The doc says never to ship a spoofed UA, and the default UA contains `USER` and `MAINTAINER@example.org`.
  - `memo` (Mem0) is offered as an extraction backend although it is a memory API.

### Webpage (`docs/index.html`)

| Severity | Issue |
|---|---|
| High | `let viewMode = localStorage.getItem(...)` is unguarded. Blocked storage (Safari private mode, some in-app browsers) throws and the whole board fails to load. |
| High | Keyboard and a11y: `.row-main` (div, `role=button`, `tabindex=0`) and `.job-card` have no Enter/Space handler. Keyboard users cannot expand rows or open cards. |
| Medium | `days_left` is frozen at export time, so the page shows stale countdowns. Compute it client-side from `deadline`. |
| Medium | Deep links and sharing use SQLite `id`, which is reassigned on journal restore. Use `url_hash` instead. |
| Medium | The CSV export ignores the active chip filter, so the exported set differs from what is displayed. It also doesn't neutralise leading `= + - @`, so a scraped title can become a spreadsheet formula. |
| Medium | "75" is hard-coded in the hero, meta description and analytics. Actual state is below. |
| Low | "Visa friendly" and "Remote eligible" are computed from fields that are `unknown` or `false` for most listings, so they read near 0%. |
| Low | The JS `sector` fallback regex (`rand`, `bis`, `bank`) has no word boundaries. It is only used when the server omits `sector`. |
| Low | The contact email differs between pages: `taherifarnam@gmail.com` in the footer, `taheri.farnam@gmail.com` in `pyproject.toml`. |
| Low | Unused constants, plus no `hashchange` handling, so the Back button doesn't close the modal. |

### Docs and housekeeping

- ARCHITECTURE describes schema v5 and indexes keyed on `status='active'`, but the code is schema v6 and no row ever has that status. The PRAGMA values also differ.
- Test counts disagree (282 vs 295).
- `compile_project.py` is a large generated blob that is already stale.
- Its include globs omit `docs/favicon.svg`, `docs/logo.svg`, `docs/rss.xsl` and `docs/architecture*`, so a rebuild gives a broken dashboard. Add a CI freshness check, or stop committing it.
- `Makefile` `.PHONY` omits `eval` and `run-dry`.
- `RateLimiter` dataclass defaults (10 RPM, 200 RPD) differ from `Settings`.

---

## Part 2: Source coverage

### What "75 monitored pages" really is (from the latest `health.json` run)

- 75 `[[board]]` entries, 6 of them disabled → **69 enabled**.
- **~22 return errors.** The 15–20 s timeouts suggest GitHub runner IPs are blocked or the URL is dead: `ecb`, `ifs`, `insead`, `wzb`, `diw_berlin`, `iwh_halle`, `eui_florence`, `eth_lawecon`, `max_planck_econ`, `nber_ras`, `opportunity_insights`, `stanford_siepr`, `tobin_yale`, `poverty_action`, `pse`, `pse_paris`, `cemfi_madrid`, `carlo_alberto`, `bde_spain`, `akadeus`, `iies_stockholm`, plus `fed_board` (typo URL).
- **~11 return zero items but report `ok`:** `bis`, `cemfi`, `ifo`, `niesr`, `ny_fed`, `rwi_essen`, `somma`, `uab_ufae`, `uzh`, `zew`, `academictransfer`. Several of these are probably selector or pattern rot.
- **~11 return many items but zero relevant:** `eief`, `tse`, `bocconi_igier`, `crei`, `econjobmarket`, `inomics`, `bank_of_england` and others. Their `link_pattern` is too broad (for example `^https?://`), so they scrape navigation links.
- **Productive sources are about 30**, led by `predoc_org`, `linkedin`, `jobs_ac_uk`, `academics_de`, `uchicago_bfi` and `copenhagen`.

**Recommendation:** fix and replace the ~33 broken or empty sources first. That is cheaper than adding new ones. Then expand.

### How to add sources safely

1. Prefer machine-readable endpoints, in this order: Workday or SmartRecruiters JSON, Greenhouse or Lever boards, per-institution RSS, then `link_scan`. The repo's own `[[feed]]` template already notes that many UK university vacancy systems expose `/rss/rss.aspx?cat=<id>`. Verify per institution.
2. Add a `sources probe <url>` command that reports HTTP status, item count and a sample of titles. Verify at least two live items before enabling.
3. Narrow `link_pattern` to detail-page URLs. Never use a bare domain regex.
4. For JS-only boards (Academic Positions is already in the file as disabled), either enable the optional Playwright render path or skip them.
5. Don't set `field_implied` on multi-department sources.

### Candidates (all unverified; sorted by expected yield and feasibility)

**Aggregators**
- **EURAXESS:** add more query variants and country filters. It is already included.
- **INOMICS:** it exposes RSS, and tag and category pages carry an RSS link. Add category feeds (for example "Research Assistant / Technician" and "Graduate / Traineeship") rather than only the general feed.
- **AEA JOE:** mostly faculty and PhD-level, so yield is low. Its listings page says the content is for personal use and that commercial use is prohibited. Use it only as a manual cross-check, or ask the AEA about access. Do not scrape and redistribute it.
- **Others to evaluate:** HigherEdJobs, AcademicJobsOnline, Interfolio and Nature Careers. These skew US and need per-site checks.

**UK**
- Warwick Economics/CAGE, Oxford (Economics, Nuffield, Blavatnik), Cambridge Economics, UCL, Essex, Bristol, Manchester, Edinburgh, St Andrews, QMUL and Exeter. Try each one's RSS.
- LSE STICERD, via jobs.ac.uk department filters.
- Resolution Foundation, Bank of England's own careers site, and IFS (fix its URL).

**Continental Europe**
- Tinbergen Institute, CPB, Erasmus School of Economics, KU Leuven, Bruegel, CEPR and IZA.
- SAFE Frankfurt, MPI Collective Goods and Tax Law, HU Berlin and the Bonn/Cologne research institutes.
- BSE, UPF, IAE-CSIC, ESADE, Sciences Po, HEC Paris, CREST, CEPII, OFCE and Banque de France.
- WU Wien, IHS and WIFO.
- NHH, BI, Uni Oslo (the old Jobbnorge search URL 404s, so use the new path or EURAXESS), Aalto/VATT/ETLA, Gothenburg/IFAU, CBS, Aarhus and Rockwool.
- HEC Lausanne, Geneva, Basel, St. Gallen, SNB, and ETH (repair the broken URL).
- Banca d'Italia, EIEF and Collegio Carlo Alberto (repair).

**Canada**
- Bank of Canada, HEC Montréal, Université de Montréal, Waterloo, Alberta, SFU, Queen's, McMaster, Western and Carleton.

**International and policy organisations**
- IMF, World Bank, IDB, EBRD, EIB, ADB, WTO, ILO, UNU-WIDER, CGD and IFPRI. Several use Workday or SmartRecruiters.

**US (feeds the web page)**
- The NBER RA page (fix the existing entry) and the Chicago Booth Research Professional job-ads page.
- Each Federal Reserve Bank's research analyst page.
- Harvard, Stanford, Yale, Penn, Princeton, Duke and Northwestern economics department RA pages.
- Mathematica, Urban, RAND, MDRC and Abt.

---

## Part 3: Suggested order of work

1. **Stop the bleeding (small diffs):** C1 (pending query), C4 (regex), the `broadcast-pending` import, the `fed_board` URL, the duplicate `predoc_org` name, and `requests-oauthlib`.
2. **Scope consistency:** fix the prompt scope and output keys. Decide the J-PAL policy. Make postdoc/PhD handling consistent (C2, H7).
3. **Data quality:** structured-field-first discipline tagging, degree extraction, PI validation, ZWSP stripping, European salary parsing, the geography tie-break, and a `deadline_kind` field.
4. **Privacy and ops:** move `feedback.json` out of the public repo (a private repo, an encrypted artifact or an external store), make taps idempotent, split the concurrency groups, and fix the schedule docs and `pages.yml`.
5. **Webpage:** guard `localStorage`, add keyboard handlers, compute `days_left` client-side, use stable ids, sanitise CSV, and make the source count dynamic.
6. **Coverage:** repair or replace broken sources, narrow the over-broad patterns, then add sources from the candidate list through the probe step.
7. **Tests to add:** web-routed listings are not re-published; postdoc and PhD flow end to end; soft-deadline expiry; routing regex with "Federico II"; a locale-safe salary parser.

I can turn items 1–3 into concrete patches next. The first batch is only a handful of lines.
