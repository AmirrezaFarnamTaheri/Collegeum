# Iranian career platform integrations

Collegeum only collects **public vacancy listings** that can be obtained
without a user's hiring profile or session. A provider's internal requests
and candidate-management APIs are **not automatically authorized feeds**.
This inventory reflects research on 11 October 2026; external services
and access rules can change.

| Provider | Verified discovery surface | Public listing API? | Decision |
|---|---|---|---|
| [Jobinja](https://jobinja.ir) | Public vacancy searches and job detail links | No documented first-party API found | Conservative public HTML adapter, rotating one keyword per 4-hour run; robots and HTML changes fail visibly |
| [IranTalent](https://www.irantalent.com/en/jobs) | Public listings at `/en/jobs` and detail URLs | No first-party public vacancy API verified | Conservative public-page adapter; validate domain, path, occupation and **explicit Iranian location** |
| [Jobvision](https://jobvision.ir) | Jobs website; much of the listing UI is browser-rendered | No verified public jobs API; `candidateapi.jobvision.ir` is a *candidate-profile* API, not an open vacancy feed | **Not automatically polled**; seek a documented partner feed or use an allowed public export if offered |
| [e-estekhdam](https://www.e-estekhdam.com/search) | Public vacancy search and official Telegram job channel | No verified first-party public jobs API; public search accessibility is variable | **Not automatically polled**; require a reliable listing feed and runtime/robots validation |
| [Karboom](https://karboom.io) | Public recruitment portal | No verified public developer API | Deferred until a stable permitted vacancy source is confirmed |

Third-party **Parse.bot Jobinja API** offers structured search and details
under a commercial API-key/credit model. Its service is not a Jobinja-issued
developer API. Adding it would introduce account credentials, ongoing cost,
vendor dependence and an independent scraping layer. It is **not** part of
the default integration; consider it only after explicit approval and testing.
Source: [Parse.bot marketplace](https://parse.bot/marketplace/8a194aca-b477-4ddd-89d5-6dc312b6d104/jobinja-ir-api).

An independent extension demonstrates candidate-profile REST requests to
`candidateapi.jobvision.ir` but not a supported job-listing contract. Do
not borrow its user-token extraction approach. Source:
[Jobvision CV Sync](https://github.com/ssshojaei/jobvision-cv-sync).

## Provider constraints implemented

All three active provider adapters—Jobicy worldwide remote, Jobinja Iran,
and IranTalent Iran—use the existing `PoliteClient` with robots processing
enabled in production settings. No browser, CAPTCHA solving, session
impersonation, or undocumented authenticated endpoint is used.

- **Jobicy** has a documented public API: maximum two cursor pages plus one
  status batch of up to 100 IDs per four-hour collection. Only explicit
  closure suppresses a listing; remote restrictions are checked separately.
- **Jobinja** uses one rotating search keyword, validates known job URLs,
  and records access/parse errors instead of synthesizing vacancies. This is
  a provisional adapter until live HTML compatibility is verified.
- **IranTalent** uses one unfiltered request to
  `https://www.irantalent.com/en/jobs`; its
  [robots.txt](https://www.irantalent.com/robots.txt) disallows query searches
  and `/jobs-search`, so these are **not** used. Jobs with unclear
  location are excluded, not assigned to Iran on the basis of domain alone.
  The list can be dominated by unrelated positions; coverage is not
  guaranteed without a documented search feed.

Every source reports checked time, request count and qualifying matches in
`data/career_health.json`. Errors are recorded without subscriber IDs.
The private admin sees summary and error count; subscribers see a separate
allowlisted **Sources** view with only public-source health metadata.
A provider returning zero matches is not evidence the Iranian labor market
has zero vacancies.

The data journal, source status, and dedupe identifiers are separate from the
encrypted per-user subscription and delivery outbox.

## Adding an authorized API later

Before enabling a future official/partner API, require:

1. A stable documented endpoint and authentication model for **vacancies**,
   not recruiter/candidate account mutations.
2. Explicit permission for third-party aggregation or republication and an
   understood quota; never bypass robots, login or rate limits.
3. Grounded field mappings for canonical URL, title, company, location,
   publication time, job type, eligibility and closed/open status. Missing
   location or scope means **unknown**, not Iran or worldwide remote.
4. Bounded pagination, conditional requests, 429 behavior, schema/contract
   tests and sample fixtures, opt-in routing, source attribution and
   cross-provider deduplication.
5. A fail-visible rollout with success-rate monitoring and manual shutoff
   before automatic notifications are enabled.

Provider documentation and policies should be rechecked during rollout.
