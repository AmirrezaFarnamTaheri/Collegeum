"""Job-board scrapers, preference rules and filled-position checks (from predoc-bot).

These read the boards where econ/business predocs are actually posted -- PREDOC.org,
EconJobMarket, the European Job Market, jobs.ac.uk, EURAXESS, university Workday/Varbi
portals, department pages, LinkedIn -- and turn each posting into a ``RawItem`` for the
main pipeline. Everything here is heuristic: no model and no API key are needed.
"""
