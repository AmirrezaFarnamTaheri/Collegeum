# CREST source validation — 5 October 2026

Candidate: [official opportunities index](https://crest.science/opportunities-2/).

The live index separates recruitment sections from placement biographies. Vacancy discovery must stay inside recruitment sections; unrestricted links would ingest alumni, personal websites and research papers. Current recruitment links include experimental-economics lab management and two postdoctoral adverts in other quantitative fields. Their presence is not proof that every role meets the configured field/category policy.

## Experimental-economics lab manager

The [official PDF advert](https://crest.science/wp-content/uploads/2026/09/Lab_Manager_Experimental_Economics_jobad.pdf) returned HTTP 200 through the local HTTP client and its PDF text extracted successfully in memory. The browser search tool could not fetch it. This demonstrates transport variability rather than permanent unavailability.

The advert states a three-year, full-time fixed-term role in Palaiseau, experimental design/data work, master's or PhD eligibility and selected hybrid/remote days with regular physical presence. It directs applications to Econ Job Market without giving a unique application URL. No numerical salary or sponsorship commitment is stated. Its raw deadline is `01/11/2026` and it also describes rolling processing; do not erase the fixed deadline merely because rolling processing is mentioned.

The [Econ Job Market category listing](https://econjobmarket.org/positions?category_id=5), independently found during this check, reports that the recruiter extended this role's deadline on 30 September 2026 to **1 February 2027**. Its start information also differs from the PDF. Preserve provenance and obtain the individual live application advert before activation: the static PDF is insufficient as the authority for the current deadline. This is an actual disagreement, not a hypothetical parser edge case.

## Judicial-analysis postdoc

The [linked official document](https://crest.science/wp-content/uploads/2026/06/Postdoc_Ollion_IJ_2026.pdf) timed out in the browser fetch and the direct local client hit a TLS connect timeout. Its open status, deadline and policy eligibility remain unverified. Do not classify this fetch failure as a closed vacancy or an empty healthy source.

## Integration decision

Keep CREST in the researched shortlist; this pass does not activate it. Required implementation remains section-scoped discovery, PDF detail handling, individual application-advert verification, date provenance/conflict handling and configured role/field filtering. A lab-manager title must not be silently rebranded as a predoc. The live ATS extension provides a concrete regression scenario for authoritative-date reconciliation. No production source, snapshot or journal was changed.
