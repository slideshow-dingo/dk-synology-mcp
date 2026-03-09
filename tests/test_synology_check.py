import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = REPO_ROOT / "openclaw" / "synology_check.sh"


def _write_mcporter_stub(tmp_path: Path, dsm_outputs: list[str], storage_outputs: list[str]) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "dsm.responses.json").write_text(json.dumps(dsm_outputs))
    (state_dir / "storage.responses.json").write_text(json.dumps(storage_outputs))

    stub_path = tmp_path / "mcporter"
    stub_path.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            state_dir = Path(os.environ["STUB_STATE_DIR"])
            tool = sys.argv[2]
            tool_map = {
                "synology.synology_dsm_info": "dsm",
                "synology.synology_storage_info": "storage",
            }

            if tool not in tool_map:
                sys.stderr.write(f"unexpected tool: {tool}\\n")
                sys.exit(1)

            name = tool_map[tool]
            count_path = state_dir / f"{name}.count"
            count = int(count_path.read_text()) if count_path.exists() else 0
            count_path.write_text(str(count + 1))

            responses = json.loads((state_dir / f"{name}.responses.json").read_text())
            index = count if count < len(responses) else len(responses) - 1
            sys.stdout.write(responses[index])
            """
        )
    )
    stub_path.chmod(0o755)
    return stub_path


def _read_count(tmp_path: Path, name: str) -> int:
    count_path = tmp_path / "state" / f"{name}.count"
    return int(count_path.read_text()) if count_path.exists() else 0


class SynologyCheckTests(unittest.TestCase):
    def run_health_dashboard_check(self, dsm_outputs: list[str], storage_outputs: list[str]) -> tuple[subprocess.CompletedProcess[str], Path]:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        tmp_path = Path(tmpdir.name)
        mcporter_path = _write_mcporter_stub(tmp_path, dsm_outputs, storage_outputs)
        env = os.environ.copy()
        env.update(
            {
                "MCPORTER_BIN": str(mcporter_path),
                "STUB_STATE_DIR": str(tmp_path / "state"),
                "RETRY_SLEEP_SEC": "0",
                "TIMEOUT_SEC": "5",
                "DEBUG_LOG_DIR": str(tmp_path / "debug"),
                "HOME": str(tmp_path),
            }
        )
        result = subprocess.run(
            ["bash", str(CHECK_SCRIPT), "health_dashboard"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        return result, tmp_path

    def test_health_dashboard_ok_uses_direct_dsm_and_storage_tools(self) -> None:
        result, tmp_path = self.run_health_dashboard_check(
            dsm_outputs=[
                json.dumps(
                    {
                        "model": "DS920+",
                        "temperature": 41,
                    }
                )
            ],
            storage_outputs=[
                json.dumps(
                    {
                        "volumes": [
                            {
                                "id": "volume_1",
                                "status": "normal",
                                "percent_used": 62.5,
                            }
                        ]
                    }
                )
            ],
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "level": "ok",
                "check": "health_dashboard",
                "message": "volume=62.5% temp=41C",
            },
        )
        self.assertEqual(_read_count(tmp_path, "dsm"), 1)
        self.assertEqual(_read_count(tmp_path, "storage"), 1)

    def test_health_dashboard_retries_when_required_fields_are_temporarily_missing(self) -> None:
        result, tmp_path = self.run_health_dashboard_check(
            dsm_outputs=[
                json.dumps({"model": "DS920+", "temperature": None}),
                json.dumps({"model": "DS920+", "temperature": 42}),
            ],
            storage_outputs=[
                json.dumps(
                    {
                        "volumes": [
                            {
                                "id": "volume_1",
                                "status": "normal",
                                "percent_used": 58.1,
                            }
                        ]
                    }
                )
            ],
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "level": "ok",
                "check": "health_dashboard",
                "message": "volume=58.1% temp=42C",
            },
        )
        self.assertEqual(_read_count(tmp_path, "dsm"), 2)
        self.assertEqual(_read_count(tmp_path, "storage"), 2)

        debug_log = tmp_path / "debug" / "health_dashboard.log"
        self.assertTrue(debug_log.exists())
        log_text = debug_log.read_text()
        self.assertIn("event=missing_fields", log_text)
        self.assertIn("event=recovered", log_text)

    def test_health_dashboard_fails_with_debug_log_after_exhausting_retries(self) -> None:
        result, tmp_path = self.run_health_dashboard_check(
            dsm_outputs=[
                json.dumps({"model": "DS920+", "temperature": 43}),
            ],
            storage_outputs=[
                json.dumps({"volumes": []}),
            ],
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            json.loads(result.stderr),
            {
                "level": "crit",
                "check": "health_dashboard",
                "message": f"missing dashboard fields after 3 attempt(s); debug log: {tmp_path / 'debug' / 'health_dashboard.log'}",
            },
        )
        self.assertEqual(_read_count(tmp_path, "dsm"), 3)
        self.assertEqual(_read_count(tmp_path, "storage"), 3)


if __name__ == "__main__":
    unittest.main()
