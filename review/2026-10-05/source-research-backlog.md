# Source research backlog — 5 October 2026

The institution and aggregator leads below come from the supplied report and remain **unverified**. This backlog complements the [19 researched official candidate URLs](source-expansion.md); it does not replace their verification record or activate any sources.

Before integration, check current official endpoint, access/redistribution terms, adapter compatibility, detail-page selection, geographical scope, current opportunities and empty/error reporting. A mandatory minimum of two live vacancies would wrongly exclude legitimate sparse boards: validate representative details or historical fixtures when current vacancies are scarce. Never treat a source timeout as proof it is permanently dead.

Several institutions already have registry coverage or occur in the researched shortlist. Deduplicate by exact endpoint and purpose, not institution name: a new department or official RSS feed can be a useful distinct source. EURAXESS and INOMICS are expansion/refinement leads for existing coverage. Nuffield, CREST, BSE, NHH, Sciences Po, IZA, Bank of Canada, Western, Stanford GSB, Wharton/Penn and Northwestern/Kellogg should be checked against the earlier shortlist before duplicating research.

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



## Specific unresolved checks

- Fed Board: compare the configured singular assistant URL with the official plural assistants page and verify response status plus extracted vacancies before editing.
- AEA JOE: the supplied report's access/commercial-use restriction is a lead to verify against current official terms; it is not an independently established legal conclusion here.
- Jobbnorge and other previously problematic endpoints: establish current reachability and valid pagination, rather than enabling from institution names.
- J-PAL/IPA: resolve policy documentation conflicts before exclusion or expansion.
- Existing high-error/zero-yield sources: diagnose status, selector and discovery behavior before replacing them. Healthy zero-vacancy sources remain valid monitors.

For consolidated findings and claim reconciliation, see [merged-audit.md](merged-audit.md).
