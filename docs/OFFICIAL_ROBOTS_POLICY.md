# Shared official-source robots policy

This protects the separate Collegeum PhD admissions, funded-call HTML, and
manual PDF/DOCX review fetchers. A nominal HTTP 200 response to
`/robots.txt` is not proof of crawler permission: university login,
anti-bot or maintenance pages can return HTML or JSON with status 200.

The stdlib-only `tools/official_robots.py` validates a bounded UTF-8
robots body, requires a real `User-agent:` directive, and rejects
HTML/JSON interstitials, unexpected control bytes and malformed directives
before invoking the same standard `urllib.robotparser.RobotFileParser`
already used by the engine. The ordinary 404 no-robots response remains
a distinct, explicitly handled allowance. All other failures are
`robots_unavailable` and must never be reclassified as an empty source.

An HTML source's robots request must finish at the exact originally
requested `https://<approved-host>/robots.txt`; a rewritten policy URL
is held. The PhD admissions checker also validates the robots response
HTTP status and final URL before trusting it. PDF/DOCX review fetchers
continue to disallow *all* redirects and require exact source approval,
per-target robots permission, matching content type and isolated bounded
parsing. No external document fetching is scheduled automatically.

Tests in `tests/integration/test_official_robots_fail_closed_20261121.py`
exercise the same malicious 200 responses across all four consumers,
plus explicit rejection of rewritten robots and non-200 policy responses.
These checks concern access permission, not the existence or eligibility
of any funded position. A source can be inaccessible without being empty;
never use alternate accounts, mirrors or fingerprints to circumvent denial.
