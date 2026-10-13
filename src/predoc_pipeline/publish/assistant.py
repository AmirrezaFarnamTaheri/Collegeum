"""AI interprets intent; validated read-only queries and factual rendering stay local."""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.textproc import escape_telegram_html as esc
from ..core.timeparse import format_ts, parse_datetime, utcnow
from ..settings import Settings
from .feedback import FeedbackStore

REFUSAL = ('I can query stored research vacancies and their deadlines, employers, locations, '
           'pay, qualifications and stated visa terms. I cannot answer unrelated questions, '
           'predict openings, decide personal eligibility, or invent missing facts. '
           'Try /ask Which economics positions close this month?')
ResultField = Literal['deadline', 'visa', 'salary', 'degree', 'tools', 'start', 'summary']
NOT_CONFIGURED = 'Database chat is not configured yet. Please try again later.'
UNAVAILABLE = 'Database AI is temporarily unavailable. Your tracking marks are unchanged.'


def _load_protocol(path: str) -> dict[str, Any] | None:
    """Reject unusable local configuration before reserving provider capacity."""
    try:
        protocol = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(protocol, dict):
        return None
    system, tool = protocol.get('system'), protocol.get('tool')
    if not isinstance(system, str) or not system.strip() or not isinstance(tool, dict):
        return None
    function = tool.get('function')
    if tool.get('type') != 'function' or not isinstance(function, dict):
        return None
    parameters = function.get('parameters')
    if function.get('name') != 'query_database' or not isinstance(parameters, dict):
        return None
    properties, required = parameters.get('properties'), parameters.get('required')
    if (parameters.get('type') != 'object' or parameters.get('additionalProperties') is not False
            or not isinstance(properties, dict) or not properties
            or any(not isinstance(value, dict) for value in properties.values())
            or not isinstance(required, list) or 'action' not in required
            or any(not isinstance(key, str) or key not in properties for key in required)):
        return None
    action = properties.get('action', {})
    actions = action.get('enum')
    if (action.get('type') != 'string' or not isinstance(actions, list)
            or not all(isinstance(value, str) for value in actions)
            or set(actions) != {'list', 'count', 'group', 'detail', 'refuse'}):
        return None
    return protocol


class DatabaseQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    action: Literal['list', 'count', 'group', 'detail', 'refuse']
    query: str = Field('', max_length=160)
    country: str = Field('', max_length=80)
    institution: str = Field('', max_length=120)
    kind: Literal['', 'predoc', 'phd', 'postdoc'] = ''
    visa: Literal['', 'explicit', 'inferred', 'not_offered', 'unknown'] = ''
    degree: str = Field('', max_length=40)
    deadline_before: str | None = None
    deadline_after: str | None = None
    status: Literal['open', 'closed', 'all'] = 'open'
    personal_status: Literal['', 'valid', 'applied', 'invalid'] = ''
    ids: list[int] = Field(default_factory=list, max_length=10)
    group_by: Literal['country', 'institution', 'kind', 'visa'] = 'country'
    fields: list[ResultField] = Field(default=['deadline'], max_length=7)
    limit: int = Field(4, ge=1, le=5)


def query_records(
    query: DatabaseQuery, rows: list[dict[str, Any]], marks: dict[str, dict[str, Any]], *,
    owner: bool,
) -> list[dict[str, Any]]:
    if query.personal_status and not owner:
        raise ValueError('Private application marks are available only to their owner')
    if any(i < 1 for i in query.ids):
        raise ValueError('Invalid listing ID')
    bounds = [date.fromisoformat(value) if value else None
              for value in (query.deadline_after, query.deadline_before)]
    if bounds[0] and bounds[1] and bounds[0] > bounds[1]:
        raise ValueError('Invalid deadline range')
    result = []
    now = utcnow()
    for row in rows:
        deadline = parse_datetime(row.get('deadline'))
        closed = bool(row.get('closed_at') or row.get('expired_at') or (
            deadline and deadline < now))
        if (query.status == 'open' and closed) or (query.status == 'closed' and not closed):
            continue
        if query.ids and row.get('id') not in query.ids:
            continue
        if query.personal_status and (marks.get(row.get('url_hash', '')) or {}).get(
            'status') != query.personal_status:
            continue
        if any(value.casefold() not in str(row.get(key) or '').casefold() for key, value in (
            ('country', query.country), ('institution', query.institution),
            ('min_degree', query.degree),
        ) if value):
            continue
        if query.kind and row.get('kind') != query.kind:
            continue
        if query.visa and (row.get('visa') or 'unknown') != query.visa:
            continue
        if any(term not in ' '.join(str(row.get(key) or '') for key in (
            'title', 'institution', 'summary', 'country', 'city', 'disciplines',
        )).casefold() for term in query.query.casefold().split()):
            continue
        if any(bound and (deadline is None or (
            deadline.date() < bound if i == 0 else deadline.date() > bound
        )) for i, bound in enumerate(bounds)):
            continue
        result.append(row)
    return sorted(result, key=lambda r: (r.get('deadline') or '9999', r.get('id', 0)))


def render_result(query: DatabaseQuery, rows: list[dict[str, Any]], *, snapshot: str) -> str:
    if query.action == 'refuse':
        return REFUSAL
    head = f'📚 <b>Database result · {len(rows)} matching record(s)</b>\n'
    foot = ('\n\nFacts from the stored snapshot, not a live eligibility decision. '
            f'Snapshot: {esc(snapshot)}. Unstated facts remain unknown.')
    if query.action == 'count':
        return head + 'Count computed from stored records and the requested filters.' + foot
    if not rows:
        return (head + 'No matching stored records. '
                'This does not establish that no such vacancy exists.' + foot)
    if query.action == 'group':
        groups: dict[str, int] = {}
        for row in rows:
            group = str(row.get(query.group_by) or 'Unstated')
            groups[group] = groups.get(group, 0) + 1
        lines = [f'{esc(k[:100])}: {v}' for k, v in
                 sorted(groups.items(), key=lambda item: (-item[1], item[0]))[:20]]
        return head + '\n'.join(lines) + foot
    blocks = []
    for row in rows[:query.limit]:
        lines = [f"<b>#{row['id']} · {esc(str(row['title'])[:140])}</b>",
                 esc(str(row['institution'])[:120])]
        for field in dict.fromkeys(query.fields):
            value: Any = None
            if field == 'deadline':
                value = row.get('deadline') or row.get('deadline_note')
            elif field == 'visa':
                value = (f"{row.get('visa') or 'unknown'} · "
                         f"{row.get('visa_note') or 'No supporting note stored'}")
            elif field == 'salary':
                value = row.get('salary_raw')
            elif field == 'degree':
                value = row.get('degree_note') or row.get('min_degree')
            elif field == 'tools':
                value = ', '.join(row.get('tools_required') or []) or None
            elif field == 'start':
                value = row.get('start_term') or row.get('start_date')
            elif field == 'summary':
                value = row.get('summary')
            lines.append(f'{field.capitalize()}: {esc(str(value or "Unstated")[:180])}')
        lines.append(f'<a href="{esc(row["apply_url"])}">Source advert ↗</a>')
        blocks.append('\n'.join(lines))
    from .telegram import pack_html_blocks

    footer = (f'\n\nShowing <b>SHOWN_COUNT</b> of {len(rows)} matching records. '
              'Ask for specific IDs to see omitted details.' + foot)
    pages = pack_html_blocks(blocks, header=head, footer=footer, page_size=query.limit)
    first = pages[0]
    return first.html.replace('<b>SHOWN_COUNT</b>', f'<b>{first.end - first.start}</b>')


def reserve_public_request(
    store: FeedbackStore, user_id: int, *, owner: bool, hourly_cap: int,
) -> str | None:
    if owner:
        return None
    now = utcnow()
    usage = store.data.setdefault('assistant_usage', {})
    if not isinstance(usage, dict):
        raise ValueError('Invalid assistant usage state')
    public = usage.get('public', [])
    users = usage.get('users', {})
    if not isinstance(public, list) or not isinstance(users, dict):
        raise ValueError('Invalid assistant usage state')
    # Persist reservations before invoking a provider, including failed requests.
    public = [stamp for stamp in public if isinstance(stamp, str)
              and (time := parse_datetime(stamp)) and now - timedelta(hours=1) < time <= now]
    recent = users.get(str(user_id), [])
    if not isinstance(recent, list):
        raise ValueError('Invalid assistant user rate state')
    recent = [stamp for stamp in recent if isinstance(stamp, str)
              and (time := parse_datetime(stamp)) and now - timedelta(minutes=1) < time <= now]
    if len(recent) >= 3:
        return 'You can ask 3 questions per minute. Try again in a moment.'
    if len(public) >= hourly_cap:
        return 'The shared hourly AI limit has been reached. Please try again later.'
    stamp = format_ts(now)
    usage['public'] = public + [stamp]
    users[str(user_id)] = recent + [stamp]
    # Expire inactive user counters so arbitrary user IDs cannot grow state forever.
    usage['users'] = {key: values for key, values in users.items() if isinstance(values, list)
                      and any(isinstance(s, str) and (t := parse_datetime(s))
                              and now - timedelta(minutes=1) < t <= now for s in values)}
    store.mark_dirty()
    store.save()
    return None


def _ask_database(
    question: str, rows: list[dict[str, Any]], store: FeedbackStore, settings: Settings,
    *, user_id: int, owner: bool, client: httpx.Client | None = None,
) -> str:
    if not question.strip():
        return '📚 Ask about vacancies: /ask Which economics roles close this month?'
    if len(question) > 1000:
        return 'Please keep your database question under 1,000 characters.'
    if not owner and not settings.telegram_ai_public_enabled:
        return 'Database chat is currently available to the configured owners.'
    keys = settings.get_openrouter_keys()
    if not settings.telegram_ai_enabled or not keys:
        return ('Database chat is not configured yet. '
                'Try again after OpenRouter is connected.')
    protocol = _load_protocol(settings.telegram_ai_protocol_path)
    if protocol is None:
        return NOT_CONFIGURED
    limited = reserve_public_request(store, user_id, owner=owner,
                                     hourly_cap=settings.telegram_ai_public_hourly_cap)
    if limited:
        return limited
    conversations = store.data.setdefault('assistant_queries', {})
    if not isinstance(conversations, dict):
        raise ValueError('Invalid assistant query state')
    previous = conversations.get(str(user_id))
    body = {
        'model': settings.openrouter_model, 'max_tokens': 600, 'temperature': 0,
        'messages': [
            {'role': 'system', 'content': protocol['system'] + f'\nUTC date: {utcnow().date()}.'
             + ('\nPersonal marks are private and unavailable to this user.' if not owner else '')},
            {'role': 'user', 'content': json.dumps({
                'question': question, 'previous_query': previous})},
        ],
        'tools': [protocol['tool']],
        'tool_choice': {'type': 'function', 'function': {'name': 'query_database'}},
    }
    owns_client = client is None
    http = client or httpx.Client(timeout=20)
    parsed: DatabaseQuery | None = None
    expires = time.monotonic() + 25
    provider_failed = False
    try:
        for key in keys[:5]:
            remaining = expires - time.monotonic()
            if remaining <= 0:
                return UNAVAILABLE
            try:
                response = http.post(
                    settings.openrouter_base_url.rstrip('/') + '/chat/completions',
                    headers={'Authorization': f'Bearer {key}'}, json=body,
                    timeout=min(20, remaining),
                )
            except httpx.RequestError:
                provider_failed = True
                continue
            if response.status_code == 429:
                continue
            if response.status_code != 200:
                return UNAVAILABLE
            try:
                message = response.json()['choices'][0]['message']
                if not isinstance(message, dict):
                    raise ValueError('Invalid provider message')
            except (ValueError, KeyError, IndexError, TypeError):
                provider_failed = True
                continue
            calls = message.get('tool_calls', [])
            if len(calls) != 1 or calls[0]['function']['name'] != 'query_database':
                return REFUSAL
            parsed = DatabaseQuery.model_validate_json(calls[0]['function']['arguments'])
            break
        if parsed is None:
            if provider_failed:
                return UNAVAILABLE
            return 'The AI provider is busy. Try again later or browse /positions.'
        if parsed.action == 'refuse':
            return REFUSAL
        results = query_records(parsed, rows, store.marks if owner else {}, owner=owner)
        conversations[str(user_id)] = parsed.model_dump()
        # Bounded, private follow-up memory contains validated filters, never raw questions.
        while len(conversations) > 500:
            conversations.pop(next(iter(conversations)))
        store.mark_dirty()
        store.save()
        snapshot = max((r.get('last_seen_at') or r.get('first_seen_at') or '' for r in rows),
                       default='not available')
        return render_result(parsed, results, snapshot=snapshot)
    except (httpx.RequestError, ValueError, KeyError, IndexError, TypeError, ValidationError):
        return REFUSAL
    finally:
        if owns_client:
            http.close()


def ask_database(
    question: str, rows: list[dict[str, Any]], store: FeedbackStore, settings: Settings,
    *, user_id: int, owner: bool, client: httpx.Client | None = None,
    request_id: int | None = None,
) -> str:
    """Cache a prepared reply so polling retries cannot recharge quota/provider work."""
    key = f'{user_id}:{request_id}' if type(request_id) is int and request_id > 0 else None
    replies = store.data.setdefault('assistant_replies', {})
    if not isinstance(replies, dict):
        raise ValueError('Invalid assistant reply state')
    cached = replies.get(key) if key else None
    if isinstance(cached, dict) and isinstance(cached.get('answer'), str):
        return str(cached['answer'])
    answer = _ask_database(question, rows, store, settings, user_id=user_id,
                           owner=owner, client=client)
    if key:
        replies[key] = {'answer': answer, 'stage': 'ready', 'at': format_ts()}
        while len(replies) > 200:
            replies.pop(next(iter(replies)))
        store.mark_dirty()
        store.save()
    return answer
