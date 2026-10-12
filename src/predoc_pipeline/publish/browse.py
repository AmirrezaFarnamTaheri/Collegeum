"""Small, stateful Telegram screens built from the canonical listing/mark store."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import timedelta
from typing import Any

from ..core.textproc import escape_telegram_html as esc
from ..core.timeparse import parse_datetime, utcnow
from .feedback import ID_PREFIX, FeedbackStore

VIEWS = frozenset({'positions', 'valid', 'applied', 'hidden', 'closing', 'new', 'search'})


def menu_keyboard() -> dict[str, Any]:
    return {'inline_keyboard': [
        [{'text': '📋 Open positions', 'callback_data': 'view|positions|0'},
         {'text': '⏳ Closing soon', 'callback_data': 'view|closing|0'}],
        [{'text': '⭐ Saved', 'callback_data': 'view|valid|0'},
         {'text': '📝 Applied', 'callback_data': 'view|applied|0'}],
        [{'text': '🆕 New this week', 'callback_data': 'view|new|0'},
         {'text': '🙈 Hidden', 'callback_data': 'view|hidden|0'}],
        [{'text': '🔎 Search tips', 'callback_data': 'view|search|0'},
         {'text': '❔ Help', 'callback_data': 'view|help|0'}],
    ]}


def home(rows: list[sqlite3.Row], store: FeedbackStore) -> tuple[str, dict[str, Any]]:
    from .bot import select_rows

    counts = {kind: len(select_rows(kind, rows, store))
              for kind in ('positions', 'valid', 'applied', 'hidden')}
    text = ('🎓 <b>Collegeum · your research shortlist</b>\n\n'
            f"<b>{counts['positions']} open</b> · {counts['valid']} saved · "
            f"{counts['applied']} applied\n\n"
            'Browse vacancies, save promising roles, and track applications.\n'
            '🔎 Try <code>/search economics London</code>\n\n'
            'Dates and eligibility come from the advert. Check the original before applying.')
    return text, menu_keyboard()


def search_token(query: str, context: dict[str, Any]) -> str:
    query = query.strip()[:160]
    token = hashlib.sha256(query.encode()).hexdigest()[:12]
    searches = context.setdefault('searches', {})
    if not isinstance(searches, dict):
        searches = context['searches'] = {}
    searches[token] = query
    while len(searches) > 100:
        searches.pop(next(iter(searches)))
    return token


def screen(
    kind: str, rows: list[sqlite3.Row], store: FeedbackStore, *, page: int = 0,
    query: str = '', page_size: int = 5, max_items: int = 60, site_url: str = '',
    search_id: str = '',
) -> tuple[str, dict[str, Any]]:
    from .bot import build_pages, select_rows

    if kind not in VIEWS:
        raise ValueError('Unknown browse view')
    base = kind if kind in {'valid', 'applied', 'hidden'} else 'positions'
    chosen = select_rows(base, rows, store)
    now = utcnow()
    if kind == 'closing':
        chosen = [r for r in chosen if (when := parse_datetime(r['deadline']))
                  and now <= when <= now + timedelta(days=7)]
    elif kind == 'new':
        chosen = [r for r in chosen if (seen := parse_datetime(r['first_seen_at']))
                  and now - timedelta(days=7) <= seen <= now]
        chosen.sort(key=lambda r: r['first_seen_at'], reverse=True)
    elif kind == 'search':
        if not query.strip():
            return ('🔎 <b>Search positions</b>\n\n'
                    'Send <code>/search economics London</code> or '
                    '<code>/search finance</code>. All words must match the title, employer, '
                    'location, or description.', menu_keyboard())
        terms = query.casefold().split()
        chosen = [r for r in chosen if all(term in ' '.join(str(r[key] or '') for key in
                  ('title', 'institution', 'country', 'city', 'summary',
                   'principal_investigator')).casefold() for term in terms)]
    pages = build_pages(base, chosen, store, page_size=page_size, max_items=max_items,
                        site_url=site_url)
    page = max(0, min(page, len(pages) - 1))
    text, markup = pages[page]
    labels = {'closing': '⏳ Closing within 7 days', 'new': '🆕 Added in the last 7 days',
              'search': f'🔎 Search: {esc(query)}'}
    if kind in labels:
        text = labels[kind] + '\n\n' + text
        if not chosen:
            text = labels[kind] + '\n\nNo matches. Try another view or search.'
    if len(pages) > 1:
        text += f'\n\nPage {page + 1} of {len(pages)}'
    buttons = list((markup or {}).get('inline_keyboard', []))
    # Numbered detail buttons complement the compact feedback rows.
    for row in list(buttons):
        if row and row[0].get('callback_data', '').startswith('fb|'):
            prefix = row[0]['callback_data'].split('|')[-1]
            number = row[0]['text'].split()[-1]
            buttons.append([{'text': f'↗ Details {number}', 'callback_data': f'detail|{prefix}'}])
    nav_kind = f'search:{search_id}' if kind == 'search' else kind
    nav = []
    if page:
        nav.append({'text': '← Previous', 'callback_data': f'view|{nav_kind}|{page - 1}'})
    nav.append({'text': '⌂ Home', 'callback_data': 'view|menu|0'})
    if page + 1 < len(pages):
        nav.append({'text': 'Next →', 'callback_data': f'view|{nav_kind}|{page + 1}'})
    buttons.append(nav)
    return text, {'inline_keyboard': buttons}


def details(row: sqlite3.Row, store: FeedbackStore) -> tuple[str, dict[str, Any]]:
    from ..pipeline import _listing_from_row
    from .telegram import render_card, render_keyboard

    listing = _listing_from_row(row)
    keyboard = render_keyboard(listing, url_hash=row['url_hash'],
                               status=store.status(row['url_hash'])) or {'inline_keyboard': []}
    keyboard['inline_keyboard'].append([
        {'text': '← Open positions', 'callback_data': 'view|positions|0'},
        {'text': '⌂ Home', 'callback_data': 'view|menu|0'},
    ])
    return render_card(listing), keyboard


def valid_prefix(prefix: str) -> bool:
    return len(prefix) == ID_PREFIX and all(c in '0123456789abcdef' for c in prefix)
