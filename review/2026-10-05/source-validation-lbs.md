# London Business School source validation — 6 October 2026

Two existing shortlist candidates were rechecked against official pages. They are recurring recruitment monitors, not two verified currently open vacancies. No registry activation or publication occurred.

| Candidate | Official evidence | Identity and date rules |
|---|---|---|
| [Economics](https://www.london.edu/faculty-and-research/economics/pre-doctoral-research-assistant) | London predoc role for academic year 2026/27; full-time, up to two years; GBP 43,250 annually. Hard application closing date: 27 March 2026. The application link targets [Interfolio 182127](https://apply.interfolio.com/182127). | Preserve the explicit past deadline. Do not publish this cohort as open merely because its recurring page remains accessible. Use the Interfolio vacancy identifier to reconcile aggregator copies. |
| [Marketing](https://www.london.edu/faculty-and-research/marketing/pre-doctoral-research-assistant-in-marketing) | London predoc role for academic year 2026/27; up to two years. Annual salary amount 43,250 is shown without an explicit currency symbol in the retrieved role section. Priority applications: 15 March 2026; review begins 16 March and continues until filled. Application target: [Interfolio 180599](https://apply.interfolio.com/180599). | Store priority/review dates separately from a hard deadline. Current filled/open status is unverified. Preserve mixed marketing/economics/psychology scope and apply configured field policy rather than inferring eligibility from institution alone. |

## Adapter and activation requirements

- Extract the advert section and its application link, excluding navigation, degree admissions and unrelated faculty recruitment links.
- Preserve department and cohort alongside the vacancy identifier; a new cohort on the same recurring URL must trigger reconsideration rather than permanent seen-URL suppression.
- Use explicit economics salary currency; keep marketing currency unknown unless independently established from the advert or application metadata. Location alone is insufficient currency evidence.
- Distinguish expired economics recruitment from rolling marketing recruitment. Availability requires an authoritative closure/open indication; Interfolio responses exposed no usable advert body through the current browser reader, so accessibility is not proof of openness.
- Add adapter fixtures for expired, rolling, renewed-cohort and missing-application-link states. Verify the real polite-client transport and source health before enabling either monitor.

These checks strengthen shortlist entries 03–04. The researched shortlist remains 19 pages; this pass adds validation depth, not new page count or active coverage.
