"""Conservative, offline query-coverage evidence; never rewrites job identity."""
from __future__ import annotations


def identical_nonempty_query_results(
    observed: list[tuple[str, set[str]]],
) -> bool:
    """Flag independent search URLs returning exactly the same nonempty URL set.

    This is **unverified query filtering**, not proof of a provider failure or
    that two job adverts share one requisition. Empty or incomplete observations
    must not be misdiagnosed as filter drift. The caller should retain all
    observed candidates, but mark its source-health check as partial.
    """
    if len({query_url for query_url, _ in observed}) < 2:
        return False
    first = observed[0][1]
    return bool(first) and all(urls == first for _, urls in observed[1:])
