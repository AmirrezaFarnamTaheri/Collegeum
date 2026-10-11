"""Scheduled cohort routing across boards, RSS feeds, and portals."""

from types import SimpleNamespace

from predoc_pipeline.boards.collector import BoardRun
from predoc_pipeline.ingest import collectors
from predoc_pipeline.ingest.sources import Source


def test_scheduled_cohort_filters_boards_feeds_and_portals(monkeypatch):
    import predoc_pipeline.boards.collector as board_module
    import predoc_pipeline.boards.config as board_config

    selected = []

    def boards(_registry, _prefs, *, only, **_kwargs):
        selected.append(("boards", set(only)))
        return BoardRun()

    def feeds(sources, _client, *, max_items):
        selected.append(("feeds", [source.name for source in sources]))
        return [], []

    def portals(sources, _client, *, max_items):
        selected.append(("portals", [source.name for source in sources]))
        return [], []

    monkeypatch.setattr(board_module, "collect_boards", boards)
    monkeypatch.setattr(board_config, "load_board_sources", lambda _: [
        SimpleNamespace(name="board-a", enabled=True),
        SimpleNamespace(name="board-b", enabled=True),
    ])
    monkeypatch.setattr(collectors, "collect_feeds", feeds)
    monkeypatch.setattr(collectors, "collect_portals", portals)

    registry = [
        Source(name="feed-a", kind="feed", url="https://example.org/rss-a"),
        Source(name="feed-b", kind="feed", url="https://example.org/rss-b"),
        Source(name="portal-a", kind="portal", url="https://example.org/jobs"),
    ]
    settings = SimpleNamespace(
        enable_boards=True, enable_feeds=True, enable_portals=True,
        enable_jobspy=False, enable_twitter=False,
        max_items_per_source=30,
        sources_config="unused", preferences_config="unused",
    )
    collectors.gather(
        settings, registry, object(), prefs=object(),
        scheduled_registry={"board-b", "feed-a"},
    )
    assert selected == [
        ("boards", {"board-b"}), ("feeds", ["feed-a"]), ("portals", []),
    ]
    selected.clear()
    collectors.gather(
        settings, registry, object(), prefs=object(),
        scheduled_registry={"board-a", "feed-b", "portal-a"},
    )
    assert selected == [
        ("boards", {"board-a"}), ("feeds", ["feed-b"]), ("portals", ["portal-a"]),
    ]


def test_empty_cohort_does_not_schedule_all_boards(monkeypatch):
    import predoc_pipeline.boards.collector as board_module
    import predoc_pipeline.boards.config as board_config

    monkeypatch.setattr(board_config, "load_board_sources", lambda _: [
        SimpleNamespace(name="board-a", enabled=True),
    ])
    unexpected = []

    def boards(*_args, **_kwargs):
        unexpected.append("called")
        return BoardRun()

    monkeypatch.setattr(board_module, "collect_boards", boards)
    settings = SimpleNamespace(
        enable_boards=True, enable_feeds=False, enable_portals=False,
        enable_jobspy=False, enable_twitter=False,
        max_items_per_source=10, sources_config="unused",
    )
    collectors.gather(settings, [], object(), scheduled_registry=set())
    assert unexpected == []
