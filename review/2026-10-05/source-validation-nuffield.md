# Nuffield source validation — 6 October 2026

Status: candidate endpoint validated; adapter, policy and application availability remain unverified. No source was activated.

The [official vacancy index](https://www.nuffield.ox.ac.uk/the-college/jobs-and-vacancies/) currently links one recruitment detail page. Navigation repeats that link, so discovery must deduplicate it and exclude navigation, contact and college-resource links. The endpoint is absent from the current registry.

The [official advert](https://www.nuffield.ox.ac.uk/the-college/jobs-and-vacancies/nuffieldswiss-national-science-foundation-research-engineer/) describes a research-engineering appointment based in Oxford, employed by Nuffield, with Lausanne collaborators. Its cutoff is 18 October 2026; earlier review does not replace that cutoff. Pay is £59,133 annually; duration is two years; the November start permits later commencement. These are employer-advert facts, not a verified pipeline extraction.

The application link resolves to [Interfolio 133602](https://apply.interfolio.com/133602). The research tool returned no readable application content. Record this as an unverified application destination, not proof of either closure or availability. No application was submitted.

Integration requirements:

- Parse vacancy entries from the main content, not all links; deduplicate repeated detail URLs.
- Read details before assigning eligibility. Research engineering is not automatically a predoc role; quantitative social-science context does not justify admitting every engineering vacancy.
- Use workplace/employer evidence rather than treating Swiss funding or collaboration as a Swiss location.
- Preserve the hard cutoff separately from review timing and the flexible start.
- Follow the explicit application route; a JavaScript shell must not replace the substantive employer advert.
- Retain response fixtures and verify parser output, eligible and ineligible roles, seasonal emptiness, closure and visible transport errors before activation.

This investigation improves the integration evidence for shortlist candidate 07; it adds no healthy monitor or verified eligible vacancy to reported coverage.
