# CodeRabbit review response — PR #18

Reviewed the nine inline findings against commit 87abf28 and verified the
source-evidence findings before editing publication data.

| Comment | Change |
| --- | --- |
| 4252374752 | Removed unused webhook settings and sync token from the scraper step; scheduled snapshot refresh remains in telegram-sync. |
| 4252374772 | Scoped OpenRouter and Worker sync secrets to the private-command processing step that consumes them. |
| 4252374777 | Transport/provider JSON failures rotate keys within the retry budget and report unavailable. Invalid tool arguments still receive a scoped refusal. The Python mirror now follows the same distinction. |
| 4252374784 | Account-owned tokens fall back to the account token verification endpoint before the existing Worker account check. |
| 4252374790 | Empty and oversized slash/plain-text questions are validated before either public quota is reserved. |
| 4252374797 | Rejected Brown REQ209234 in the durable journal/seen state, preserving its historical record. A narrow title exclusion prevents repeat ingestion. Rebuilt public JSON and RSS omit it. |
| 4252374803 | Brown REQ210856 now carries Health Economics, Public Policy and Econometrics, supported by its advert; unrelated Labor/Environmental categories removed from journal, JSON and RSS. |
| 4252374813 | Royal Holloway ID179 now links to the position-specific source advert instead of the general jobs homepage. Stable historical identity is retained. |
| 4252374826 | Protocol file/JSON/schema validation runs before quota. Missing or invalid configuration returns a cached not-configured reply rather than blocking the update queue. |

Source evidence: [Brown fundraising advert](https://brown.wd5.myworkdayjobs.com/staff-careers-brown/job/South-Street-Landing/Senior-Research-Analyst_REQ209234),
[Brown health-economics advert](https://brown.wd5.myworkdayjobs.com/staff-careers-brown/job/121-South-Main-Street/Health-Economics-Research-Analyst_REQ210856),
[Royal Holloway position](https://www.jobs.ac.uk/job/DTF942/british-election-study-postdoctoral-research-fellow),
[Cloudflare account token API](https://developers.cloudflare.com/api/resources/accounts/).
The Brown records were verified through the official Workday JSON endpoints.

After integrating main's publication refresh through 3955b24, the inventory has
132 visible records (131 before that refresh). Regeneration preserves the
previous public visibility set, without reading or modifying encrypted owner
marks. The publication audit reports zero integrity errors; its existing
historical warnings and clock-skew warning remain visible. Health history is
not relabeled as a fresh discovery run merely because publications were rebuilt.

Validation includes malformed protocol/no-quota regressions, transport/key
fallback and bounded retry tests, account-token fallback, malformed-question
quota tests, title exclusion, lint/types and publication integrity checks.
Live provider delivery, deployment and webhook activation remain unverified.

Full verification before integrating the subsequent publication-only main
commits: 1,204 Python tests and 21 subtests passed; all 22 Worker checks passed,
including workerd/SQLite. Ruff and strict mypy passed (75 source files).

The automated docstring coverage warning is advisory and is not a repository CI
gate. No bulk docstrings were added to self-describing tests or historical
reproduction helpers just to change the bot's coverage percentage.
