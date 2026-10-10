"""Routing boundaries and missing-credential command behavior."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from predoc_pipeline.boards.config import Preferences, RoutingConfig
from predoc_pipeline.cli import app
from predoc_pipeline.routing import Channel, Router
from predoc_pipeline.settings import Settings


@pytest.mark.parametrize("name", ["Fed", "RAND", "UN", "BIS", "CRA", "ILO"])
def test_exact_employer_names_respect_word_boundaries(name):
    router = Router(Preferences(routing=RoutingConfig(web_employer_names=[name])))
    assert router.sector(f"Example {name.lower()} Research") == "institutional"
    assert router.sector(f"Example x{name}y University") == "academic"
    assert router.sector(f"Example {name}-associated University") == "academic"


def test_federico_university_routes_to_non_us_academic_channel():
    router = Router(Preferences(routing=RoutingConfig(web_employer_names=["Fed"])))
    assert router.channel(
        title="Predoctoral Fellow",
        institution="University of Naples Federico II",
        country="Italy",
    ) == Channel.TELEGRAM


def test_broadcast_pending_reports_missing_credentials_without_import_error():
    settings = Settings(_env_file=None, telegram_bot_token="", telegram_public_channel_id="")
    with patch("predoc_pipeline.cli._settings", return_value=settings):
        result = CliRunner().invoke(app, ["broadcast-pending"])
    assert result.exit_code == 1
    assert "Telegram credentials not configured" in result.output
    assert not isinstance(result.exception, ImportError)
