# Published-output audit — 11 October 2026

Baseline: latest committed \`main\` snapshot, \`docs/data/listings.json\`
(\`generated_at=2026-10-11T12:41:36Z\`) and matching state/RSS/health.
This report distinguishes **observed data** from source assumptions.
The draft [PR #16](https://github.com/AmirrezaFarnamTaheri/Collegeum/pull/16)
contains the deterministic code changes. Production artifacts remain unmodified
until the updated pipeline executes on main.

## Format and cross-artifact invariants

- State: 175 valid NDJSON records, with 174 published and one pending.
- Seen-state: 498 NDJSON records, readable and consistently shaped.
- Website: 134 public records; declared \`count=134\`.
- RSS: 100 items (configured export cap); all item links map to the dashboard
  and GUIDs are unique.
- No duplicate state listing IDs, apply URLs, or URL identity hashes were found.
- All compared dashboard fields matched persisted state **before** the
  corrective projection changes in this PR. Routing intentionally excludes
  some otherwise active non-US predoc records from the website.
- Three historical records (#1, #21, #27) were initially published **after
  their stated deadlines**; they are now expired and absent from the website.
- CI now runs a dependency-free strict verifier of publication formats,
  membership, link integrity, date formats, and recoverable JSON/XML validity.
  Semantic anomalies are warnings, not assertions that an employer has closed.

## Confirmed misleading actual outputs

| Record | Observed output | Correct treatment |
|---|---|---|
| #156 | German TV-L E 13 pay grade rendered as $13/year | Preserve original grade text; no numeric salary |
| #118 | TV-L 13 grade parsed as monetary 13 | Preserve original text only |
| #148 | Publication year 2026 parsed as salary amount | Preserve rate-note text only |
| #133 | UK Grade 6/7 pay bands parsed as £6–31,236/year | Preserve multiple-band original text until safely parsed |
| #131 | Australian dollar compensation labeled USD | Interpret bare dollar sign in known Australian location as AUD |
| #73 | French 3,400 EUR brut/mois has missing period | Recognize French monthly period |
| #55 | Generic Google sign-in page became the position summary and destination | Withhold login-page summary from website/RSS; unwrap safe Google Forms destination for legitimate records |
| #25 | Greenhouse \`?error=true\` presented as job application | Withhold error link pending independently verified replacement |
| #119 | Generic EJM homepage used as application URL | Verify precise ATS link; do not invent one |
| #46 | Employer is University of Chicago Booth, but vacancy summary describes Penn BCFG | Independently verify organization before amending persisted identity |
| #28 | UChicago neuroscience role appeared with Labor/Behavioral Economics tags | Re-evaluate economics field acceptance against actual job page; do not bulk-delete without evidence |
| #139 | Actual St. Gallen doctoral candidate role has \`min_degree=phd\` | Qualifying for PhD enrollment is not proof of completed doctorate |
| #77 | Bank of Canada completed-PhD researcher labeled \`phd\` (a PhD student role) | Distinguish completed-PhD hire from enrolled doctoral student |

The Bern \`Doktorand/in und Assistent/in\` (#173) was incorrectly assumed
off-field based on its LinkedIn employer name "CAS in Medication Safety
University of Bern". The source job text itself identifies a **Finance PhD**
at the University of Bern Institute for Financial Management. The Finance
subject is therefore supported. The **employer attribution** is what requires
correction. Do not discard the post solely because of its misleading LinkedIn
organization label.

## Source-health and operational context

Latest \`health.json\` shows 81 source identities: 44 successful, 12 empty,
22 completely failed, 3 partial. Historical outputs double-counted the
three partials as failures and marked several runs \`ok\` despite unsuccessful
source checks. PR #16 repairs aggregation and derived historical outcome
presentation. No historical run source evidence is rewritten.

## Remaining external gates

1. Confirm corrected URLs, role eligibility, and institution for each disputed
   record with an actual source vacancy or verified ATS response. A valid URL
   by itself does not establish an open position.
2. Confirm that the scheduled pipeline on main reexports clean dashboard and
   RSS after merge, including corrected home/self URL. Historical public
   Git commits cannot be erased by this procedure.
3. Validate life-sciences activation on its own PR branch separately; the
   audited public snapshot from main is still economics-heavy.
4. Run live Telegram opt-in/opt-out and receipt recovery checks; successful
   workflow status alone cannot prove messages were delivered.
5. Follow up recurrent source fetch/parse failures individually. Do not evade
   robots/access restrictions or claim they have been repaired without a
   successful live parser result.

## Decision

Structural format integrity is generally sound. **Semantic validity remains
the binding release gate.** Publication is not automatically trustworthy
merely because the GitHub job is green or a JSON schema validates.
