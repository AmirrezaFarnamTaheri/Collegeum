"""Never turn a one-off source acceptance probe into live collection or write access."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
FLOW = ROOT / ".github/workflows/life-euraxess-detail-probe.yml"


class LifeEuraxessProbeContract(unittest.TestCase):
    def test_only_trusted_main_runs_readonly_bounded_policy_probe(self):
        workflow = FLOW.read_text(encoding="utf-8")
        for required in (
            "permissions:\n  contents: read",
            "github.ref == 'refs/heads/main'",
            "github.repository == 'AmirrezaFarnamTaheri/Collegeum'",
            "persist-credentials: false",
            "ref: main",
            "--detail-sample-limit 2",
            "--limit 3",
            "--names life_euraxess life_euraxess_cell_models life_euraxess_computational",
            "actions/upload-artifact@v7",
        ):
            self.assertIn(required, workflow)
        for forbidden in ("contents: write", "actions: write", "git push",
                          "workflow_run:", "schedule:", "secrets.", "TELEGRAM_BOT_TOKEN"):
            self.assertNotIn(forbidden, workflow)


if __name__ == "__main__":
    unittest.main()
