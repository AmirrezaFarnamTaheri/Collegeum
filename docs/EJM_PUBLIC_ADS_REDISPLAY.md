# EconJobMarket public ad feed: permission-gated recovery

**Status as of 2026-11-08:** The currently configured `econjobmarket` HTML
source remains active and its live zero-posting failure remains visible. The
optional `econjobmarket_ads` adapter is implemented and tested but **not
activated**, and Collegeum does not claim provider permission.

## Evidence and redistribution requirement

EJM's documentation names
`https://backend.econjobmarket.org/data/zz_public/json/Ads` as its public
advertisement-feed endpoint. The provider expressly allows personal/academic
research access but requires sites *redisplaying* its advertisements to notify
EJM, receive approval, and display the attribution and application guidance
specified by EJM. The terms and required display wording must be verified with
the provider, not guessed from the endpoint returning HTTP 200:

- https://support.econjobmarket.org/docs/ad-redisplay/Ad-Redisplay.0.md

This is the advertisement redisplay endpoint, **not** the authenticated
recruiter applicant-management API. Do not solicit or store applicant tokens.

## Activation checklist (authorized operator only)

1. Request written approval from EJM for the actual Collegeum website and
   downstream Telegram listings, explaining intended redistribution and
   attribution. Record a nonsecret approval reference and scope in an issue.
2. Confirm permitted usage and the required prominent provider/applicant
   attribution on every surfaced channel; do not activate if any channel is
   outside the granted scope.
3. After approval, switch **only** the `econjobmarket` entry in
   `config/sources.toml` to the following, retaining the existing identity
   and field defaults:

       type = "econjobmarket_ads"
       url = "https://backend.econjobmarket.org/data/zz_public/json/Ads"
       redistribution_approved = true

   Remove the old `urls` and `link_pattern` options. Explicit
   `redistribution_approved = true` is mandatory; otherwise **no request**
   is made. A changed endpoint is refused before contacting the provider.
4. Run the offline fixture tests, lint, type check and CI on both supported
   Python versions. Run a **read-only**, policy-compliant official endpoint
   probe only after approval. Confirm JSON array shape, stable exact-host
   vacancy URLs, bounded response size, and that source health is neither an
   invented verified empty nor a silent parsing failure.
5. Verify a later real scheduled pipeline commits new health with the source
   classified truthfully, and audit the dashboard, Telegram destinations,
   duplicates, source provenance and application links before considering the
   provider incident closed.

The adapter rejects non-EJM job links and invalid dates, does not retry an
HTTP 429, and treats malformed/empty feeds as degraded. Neither an available
public endpoint nor green offline tests prove production access.

If approval is denied or uncertain, **do not** enable the adapter, suppress
source errors by setting `may_be_empty`, fabricate application URLs, or
replay failed policy-limited requests. Keep the incident open.
