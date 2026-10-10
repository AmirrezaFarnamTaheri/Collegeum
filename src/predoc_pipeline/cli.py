"""Command-line interface.

Every command that touches the database or the network degrades gracefully:
missing credentials produce a clear error rather than a stack trace, and
``--dry-run`` is available wherever it makes sense so a maintainer can see what
would happen before spending a model call or sending a message.
"""

from __future__ import annotations

import time
from pathlib import Path
from tempfile import TemporaryDirectory

import typer

from .boards.config import load_preferences
from .core.db import Database
from .core.db import init as init_db
from .core.timeparse import format_ts
from .ingest.discover import discover_in_html
from .ingest.http import PoliteClient
from .ingest.sources import load_sources
from .logging_setup import configure as configure_logging
from .logging_setup import get_logger
from .routing import Router
from .settings import Settings

app = typer.Typer(
    name="predoc-pipeline",
    help="Discover, deduplicate and broadcast non-US predoctoral research positions.",
    no_args_is_help=True,
)
sources_app = typer.Typer(help="Manage the source registry (config/sources.toml).")
app.add_typer(sources_app, name="sources")

log = get_logger(__name__)


def _settings() -> Settings:
    configure_logging()
    return Settings()


@app.command()
def run(
    dry_run: bool = typer.Option(
        False, help="Ingest and gate, but call no model and send nothing."
    ),
    only: str | None = typer.Option(
        None,
        help="Comma-separated collectors ('boards,feeds') or board sources ('cemfi,linkedin').",
    ),
    limit: int | None = typer.Option(None, help="Process at most this many ingested items."),
) -> None:
    """Run one full cycle: ingest, gate, extract, dedupe, publish."""
    from .pipeline import EXIT_FATAL, EXIT_OK
    from .pipeline import run as run_pipeline

    settings = _settings()
    only_set = {s.strip() for s in only.split(",")} if only else None
    try:
        stats = run_pipeline(settings, only_sources=only_set, dry_run=dry_run, limit=limit)
    except Exception as exc:  # pragma: no cover - top-level safety net
        typer.secho(f"fatal: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(EXIT_FATAL) from exc

    typer.echo(
        f"ingested={stats.ingested} gated={stats.gated} extracted={stats.extracted} "
        f"duplicates={stats.duplicates} published={stats.published} errors={stats.errors} "
        f"llm_calls={stats.llm_calls} outcome={stats.outcome}"
    )
    raise typer.Exit(EXIT_OK if stats.outcome in ("ok", "dry-run", "partial") else 1)


@app.command()
def init() -> None:
    """Create the database and directory layout, without touching the network."""
    settings = _settings()
    init_db(settings.db_path)
    for path in (settings.state_path, settings.dashboard_json, settings.health_json):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.sources_config).parent.mkdir(parents=True, exist_ok=True)
    typer.echo(f"initialised database at {settings.db_path}")


@app.command()
def stats() -> None:
    """Print database counts and the last few runs."""
    settings = _settings()
    init_db(settings.db_path)
    with Database(settings.db_path) as db:
        counts = db.counts()
        typer.echo("counts: " + " ".join(f"{k}={v}" for k, v in counts.items()))
        typer.echo("\nrecent runs:")
        for row in db.recent_runs(limit=10):
            typer.echo(
                f"  {row['started_at']}  outcome={row['outcome']:<14} "
                f"ingested={row['ingested']:<4} published={row['published']:<3} "
                f"errors={row['errors']}"
            )


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query string (keyword, institution, or field)"),
    all_status: bool = typer.Option(False, "--all", help="Include closed/expired/pending listings"),
    limit: int = typer.Option(20, help="Maximum number of results to display"),
) -> None:
    """Search listings in the local database by title, institution, or summary."""
    settings = _settings()
    init_db(settings.db_path)
    with Database(settings.db_path) as db:
        results = db.search_listings(query, active_only=not all_status, limit=limit)
        if not results:
            typer.echo(f"No listings found matching '{query}'.")
            return
        typer.echo(f"Found {len(results)} listing(s) matching '{query}':\n")
        for r in results:
            status_tag = f"[{r['status']}] " if all_status else ""
            typer.echo(f"- {status_tag}{r['title']} @ {r['institution']}")
            typer.echo(f"  Apply: {r['apply_url']}")
            if r["deadline"]:
                typer.echo(f"  Deadline: {r['deadline']}")
            typer.echo("")


@app.command()
def dashboard() -> None:
    """Regenerate docs/data/*.json from the current database, without a run."""
    from . import state
    from .publish.feedback import FeedbackStore

    settings = _settings()
    init_db(settings.db_path)
    hidden = FeedbackStore.from_settings(settings).hidden
    router = Router(load_preferences(settings.preferences_config))
    with Database(settings.db_path) as db:
        state.restore_if_needed(db, settings.state_path, settings.seen_state_path)
        count = state.export_dashboard(db, settings.dashboard_json, hidden=hidden, router=router)
        state.export_feed(db, settings.feed_path, site_url=settings.site_url,
                          hidden=hidden, router=router)
    # health.json is left alone: it is the run history, rebuilt only by `run`.
    typer.echo(f"wrote {count} active listings to {settings.dashboard_json}")


@app.command("feedback-key")
def feedback_key() -> None:
    """Print a new key for FEEDBACK_ENCRYPTION_KEY (store it as a repository secret)."""
    from .publish.feedback import generate_key

    typer.echo(generate_key())


@app.command("broadcast-pending")
def broadcast_pending() -> None:
    """Broadcast unposted pending predoc positions directly to Telegram and update state."""
    from . import state
    from .pipeline import RunStats, _broadcast, _listing_from_row
    from .publish.feedback import FeedbackStore
    from .publish.telegram import TelegramClient

    settings = _settings()
    if not settings.telegram_configured:
        typer.secho(
            "Telegram credentials not configured; cannot broadcast.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    init_db(settings.db_path)
    prefs = load_preferences(settings.preferences_config)
    router = Router(prefs)
    feedback = FeedbackStore.from_settings(settings)
    with Database(settings.db_path) as db:
        state.restore_if_needed(db, settings.state_path, settings.seen_state_path)
        pending_rows = db.pending_listings()
        accepted = []
        for row in pending_rows:
            if row["url_hash"] not in feedback.hidden:
                accepted.append((int(row["id"]), _listing_from_row(row)))

        typer.echo(f"Found {len(accepted)} pending position(s) eligible for broadcast.")
        if not accepted:
            return

        stats = RunStats(run_id="broadcast-manual")
        telegram = TelegramClient(bot_token=settings.telegram_bot_token)
        try:
            _broadcast(
                accepted,
                telegram,
                settings,
                db,
                stats,
                router=router,
                feedback=feedback,
                digest_page_size=prefs.telegram.digest_page_size,
            )
        finally:
            telegram.close()

        state.write_journal(db, settings.state_path)
        state.export_dashboard(
            db, settings.dashboard_json, hidden=feedback.hidden, router=router
        )
        state.export_feed(
            db,
            settings.feed_path,
            site_url=settings.site_url,
            hidden=feedback.hidden,
            router=router,
        )
        typer.echo(f"Broadcast completed: published={stats.published} errors={stats.errors}")


@app.command()
def vacuum() -> None:
    """Prune old dead-letter and seen-item rows, then VACUUM the database."""
    settings = _settings()
    init_db(settings.db_path)
    with Database(settings.db_path) as db:
        before = Path(settings.db_path).stat().st_size if Path(settings.db_path).exists() else 0
        db.prune()
        db.vacuum()
        after = Path(settings.db_path).stat().st_size if Path(settings.db_path).exists() else 0
    typer.echo(f"database: {before:,} -> {after:,} bytes")


@app.command()
def smoke() -> None:
    """Offline self-check: settings load, schema init, gate and dedupe sanity.

    Runs no network calls and needs no credentials. This is what CI runs on
    every push, and what a maintainer runs first when something looks wrong.
    """
    import json as _json

    from .core import gating
    from .core.dedupe import Deduplicator
    from .models import EXTRACTION_JSON_SCHEMA

    settings = Settings()
    typer.echo(f"settings ok (db_path={settings.db_path})")

    if "$ref" in _json.dumps(EXTRACTION_JSON_SCHEMA):
        raise RuntimeError("extraction schema must not use $ref")
    typer.echo("extraction schema ok (no $ref, JSON-serialisable)")

    real = gating.evaluate(
        "We are hiring a predoctoral research assistant in economics. "
        "Applications are invited. Closing date 1 March 2027."
    )
    phd = gating.evaluate(
        "Applications are invited for a PhD studentship in economics. "
        "The doctoral candidate will work on macro modelling. Deadline March."
    )
    if not real.passed or phd.passed:
        raise RuntimeError("gate sanity check failed")
    typer.echo("gate sanity ok (accepts predoc, rejects PhD studentship)")

    dedup = Deduplicator()
    dedup.add(1, text="a" * 200, institution="Test University", title="Predoc")
    if dedup.find(text="a" * 200, institution="Test University", title="Predoc") is None:
        raise RuntimeError("dedupe sanity check failed")
    typer.echo("dedupe sanity ok")

    with TemporaryDirectory() as directory:
        path = Path(directory) / "smoke.db"
        init_db(path)
        with Database(path) as db:
            db.set_meta("smoke", format_ts())
            if db.get_meta("smoke") is None:
                raise RuntimeError("database sanity check failed")
    typer.echo("database sanity ok")

    typer.secho("smoke check passed", fg=typer.colors.GREEN)


@app.command()
def eval(
    fixtures: str = typer.Option("tests/fixtures/golden.jsonl", help="Path to labelled examples."),
) -> None:
    """Score the deterministic gate against a labelled fixture set.

    Each fixture line is ``{"text": ..., "title": ..., "expect_pass": bool}``.
    Reports precision and recall for the gate alone -- the cheap, always-on
    layer -- so a change to the lexicon or the reject patterns has a number
    attached to it rather than a vibe.
    """
    import json as _json

    from .core import gating

    path = Path(fixtures)
    if not path.exists():
        typer.secho(f"no fixtures at {path}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    tp = fp = tn = fn = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        record = _json.loads(line)
        result = gating.evaluate(record["text"], title=record.get("title", ""))
        expected = bool(record["expect_pass"])
        if expected and result.passed:
            tp += 1
        elif expected and not result.passed:
            fn += 1
            typer.echo(f"FN reason={result.reason}: {record['text'][:80]!r}")
        elif not expected and result.passed:
            fp += 1
            typer.echo(f"FP score={result.score:.2f}: {record['text'][:80]!r}")
        else:
            tn += 1

    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    typer.echo(
        f"\nn={total} tp={tp} fp={fp} tn={tn} fn={fn} "
        f"precision={precision:.3f} recall={recall:.3f}"
    )


@app.command("telegram-sync")
def telegram_sync_cmd() -> None:
    """Answer /positions etc. and save your ✅ ❌ 📝 button taps (run every 30 min)."""
    from .publish.bot import telegram_sync
    from .publish.telegram import TelegramError

    settings = _settings()
    try:
        summary = telegram_sync(settings)
    except TelegramError as exc:
        typer.secho(f"Telegram sync failed due to error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"answered {summary['commands']} command(s), saved {summary['taps']} button tap(s), "
        f"ignored {summary['ignored']} message(s) from other people"
    )


@app.command("telegram-chat-id")
def telegram_chat_id() -> None:
    """Print your chat id. First open your bot in Telegram and send it any message."""
    from .publish.telegram import TelegramClient, TelegramError

    settings = _settings()
    if not settings.telegram_bot_token:
        typer.secho("Set TELEGRAM_BOT_TOKEN first.", fg=typer.colors.RED)
        raise typer.Exit(1)
    try:
        with TelegramClient(bot_token=settings.telegram_bot_token) as client:
            updates = client.call("getUpdates", {"timeout": 0}) or []
    except TelegramError as exc:
        typer.secho(f"Telegram error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    chats: dict[str, str] = {}
    for update in updates:
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        if chat.get("id") is not None:
            name = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
            chats[str(chat["id"])] = f"{chat.get('type', '')} {name}".strip()
    if not chats:
        typer.echo("No messages yet. Open your bot in Telegram, press Start, send 'hi', "
                   "then run this again.")
        raise typer.Exit(1)
    for chat_id, label in chats.items():
        typer.echo(f"TELEGRAM_PUBLIC_CHANNEL_ID={chat_id}    ({label})")


@app.command("test-telegram")
def test_telegram() -> None:
    """Send one test message to TELEGRAM_PUBLIC_CHANNEL_ID."""
    from .publish.telegram import TelegramClient, TelegramError

    settings = _settings()
    if not settings.telegram_configured:
        typer.secho("Set TELEGRAM_BOT_TOKEN and TELEGRAM_PUBLIC_CHANNEL_ID first.",
                    fg=typer.colors.RED)
        raise typer.Exit(1)
    try:
        with TelegramClient(bot_token=settings.telegram_bot_token) as client:
            client.send_message(
                chat_id=settings.telegram_public_channel_id,
                html="\U0001f44b <b>Predoc bot</b> is connected. New predoc / RA openings "
                     "will arrive here. Send /positions to see the current list.",
            )
    except TelegramError as exc:
        typer.secho(f"failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc
    typer.echo("sent")


@app.command("test-x")
def test_x() -> None:
    """Send one test tweet to your configured X/Twitter account."""
    from .publish.x import XClient, XError

    settings = _settings()
    if not settings.x_broadcast_configured:
        typer.secho(
            "X credentials not configured. Please set X_CONSUMER_KEY, X_CONSUMER_SECRET, "
            "X_ACCESS_TOKEN, and X_ACCESS_TOKEN_SECRET in your environment or .env.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    client = XClient.from_settings(settings)
    test_text = (
        "🎓 Predoc Pipeline connected.\n\n"
        "Automated monitoring for predoctoral and research assistant positions in economics.\n\n"
        "#EconTwitter #Predoc"
    )
    try:
        tweet_id = client.post_tweet(test_text)
        typer.secho(f"Successfully posted test tweet! ID: {tweet_id}", fg=typer.colors.GREEN)
        typer.echo(f"View at: https://x.com/i/status/{tweet_id}")
    except XError as exc:
        typer.secho(f"X API error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc


@app.command("search-x")
def search_x(
    query: str = typer.Argument(
        'from:econ_RA OR "predoc" OR "pre-doc"',
        help="Search query or account filter.",
    ),
    limit: int = typer.Option(10, help="Maximum number of results to display."),
) -> None:
    """Live search X/Twitter for predoc postings using X API v2 or Xquik."""
    import os

    from .ingest.collectors import collect_x_api, collect_xquik

    settings = _settings()
    settings.twitter_search_queries = [query]
    settings.max_items_per_source = limit

    if settings.x_bearer_token or os.environ.get("X_BEARER_TOKEN"):
        typer.echo(f"Querying Official X API v2 with query: {query}")
        items, stats = collect_x_api(settings)
    elif settings.xquik_api_key or os.environ.get("XQUIK_API_KEY"):
        typer.echo(f"Querying Xquik Platform API with query: {query}")
        items, stats = collect_xquik(settings)
    else:
        typer.secho(
            "No X search credentials configured. Set X_BEARER_TOKEN (for official X API v2) "
            "or XQUIK_API_KEY (for Xquik) in your environment or .env file.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    for stat in stats:
        if stat.errors:
            typer.secho(f"Errors: {', '.join(stat.messages)}", fg=typer.colors.RED)
    if not items:
        typer.echo("No matching tweets found.")
        return

    typer.secho(f"Found {len(items)} tweets:\n", fg=typer.colors.GREEN)
    for i, it in enumerate(items, 1):
        typer.echo(f"[{i}] {it.source}")
        typer.echo(f"    URL: {it.source_url}")
        typer.echo(f"    Text: {it.title}")
        if it.hints.get("urls"):
            typer.echo(f"    Extracted links: {', '.join(it.hints['urls'])}")
        typer.echo("-" * 60)


@sources_app.command("list")
def sources_list(config: str = typer.Option("config/sources.toml")) -> None:
    """Show every source and whether it is switched on."""
    from .boards.config import load_board_sources

    for board in load_board_sources(config):
        state_ = "on " if board.enabled else "off"
        typer.echo(f"{state_}  board   {board.name:<30} {board.type:<10} {board.group}")
    for source in load_sources(config):
        state_ = "on " if source.enabled else "off"
        typer.echo(f"{state_}  {source.kind:<7} {source.name:<30}")


@sources_app.command("verify")
def sources_verify(
    config: str = typer.Option("config/sources.toml"),
    timeout: float = typer.Option(20.0),
) -> None:
    """Probe board, feed and portal discovery through production collectors.

    Disabled entries are reported separately. This checks board discovery,
    not vacancy eligibility or every posting's detail/application destination.
    """
    settings = Settings()
    sources = load_sources(config)
    from .boards.collector import verify_boards
    from .boards.config import load_board_sources
    from .ingest.collectors import collect_feeds, collect_portals

    boards = load_board_sources(config)
    if not sources and not boards:
        typer.secho(f"no sources found in {config}", fg=typer.colors.YELLOW)
        raise typer.Exit(1)

    prefs = load_preferences(settings.preferences_config)
    prefs.http.timeout = timeout
    prefs.http.source_timeout = timeout
    board_stats = verify_boards(config, prefs)
    ok = 0
    failed = 0
    for board in boards:
        if not board.enabled:
            typer.echo(f"skip     {board.name} (disabled)")
            continue
        stat = board_stats[board.name]
        if stat.get("skipped"):
            typer.echo(f"SKIPPED  {board.name}")
            failed += 1
        elif not stat.get("ok") or stat.get("errors"):
            stage = stat.get('failure_stage') or 'discovery'
            label = 'PARTIAL' if stat.get('items') else 'FAIL'
            typer.echo(f"{label:<8} {board.name} (adapter {stage} failed; "
                       f"{stat.get('items', 0)} postings discovered)")
            failed += 1
        elif not stat.get("items"):
            expected = stat.get("may_be_empty", False)
            detail = 'seasonal empty allowed' if expected else 'unexpected empty discovery'
            typer.echo(f"{'EMPTY' if expected else 'CHECK':<8} {board.name} "
                       f"({detail})")
            ok += int(expected)
            failed += int(not expected)
        else:
            typer.echo(f"OK       {board.name} {stat['items']} discovered postings")
            ok += 1
    with PoliteClient(
        user_agent=settings.http_user_agent,
        timeout=timeout,
        respect_robots=settings.respect_robots_txt,
    ) as client:
        for source in sources:
            if not source.enabled:
                typer.echo(f"skip     {source.name} (disabled)")
                continue
            mark = "verified" if source.verified else "UNVERIFIED"
            collector = collect_feeds if source.kind == 'feed' else collect_portals
            _, outcomes = collector([source], client, max_items=settings.max_items_per_source)
            outcome = outcomes[0]
            if outcome.errors:
                failed += 1
                label = 'PARTIAL' if outcome.items else 'FAIL'
                typer.echo(f"{label:<8} {source.name} {outcome.errors} collector errors [{mark}]")
            elif outcome.items:
                ok += 1
                typer.secho(
                    f"OK       {source.name:<28} {outcome.items} discovered postings [{mark}]",
                    fg=typer.colors.GREEN,
                )
            else:
                failed += 1
                typer.secho(
                    f"CHECK    {source.name:<28} no postings discovered [{mark}]",
                    fg=typer.colors.RED,
                )
            time.sleep(0.2)
    enabled = sum(s.enabled for s in sources) + sum(b.enabled for b in boards)
    typer.echo(f"\n{ok}/{enabled} enabled sources passed; {failed} require attention")
    if not enabled or failed:
        raise typer.Exit(1)


@sources_app.command("discover")
def sources_discover(
    url: str = typer.Argument(..., help="A site or section page to inspect."),
) -> None:
    """Find feeds a page advertises, as a starting point for sources.toml."""
    settings = Settings()
    with PoliteClient(user_agent=settings.http_user_agent) as client:
        result = client.get(url, use_cache=False)
    if not result.ok:
        typer.secho(f"could not fetch {url}: {result.error or result.status}", fg=typer.colors.RED)
        raise typer.Exit(1)
    feeds = discover_in_html(result.text, url)
    if not feeds:
        typer.echo("no feeds found via <link rel=alternate> or anchor text")
        raise typer.Exit(1)
    for feed in feeds:
        label = f" ({feed.title})" if feed.title else ""
        typer.echo(f"[{feed.method:<12}] {feed.url}{label}")


def main() -> None:  # pragma: no cover - thin entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
