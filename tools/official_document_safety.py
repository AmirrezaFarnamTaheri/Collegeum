"""Strict redirect policy for approved institutional document evidence fetches.

No redirect, including an apparently harmless same-host hop, is approved:
the final URL could represent an unreviewed or revised official document.
"""
from __future__ import annotations

import urllib.request
from typing import Any


class NoDocumentRedirect(urllib.request.HTTPRedirectHandler):
    """Fail before issuing a second request, even to the same origin."""

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int,
        msg: str, headers: Any, newurl: str,
    ) -> urllib.request.Request:
        raise ValueError("unsafe_redirect")
