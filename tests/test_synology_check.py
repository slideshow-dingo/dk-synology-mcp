import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = REPO_ROOT / "openclaw" / "synology_check.sh"
sys.path.insert(0, str(REPO_ROOT / "src"))

from synology_api.exceptions import SynoConnectionError
from synology_mcp.utils.formatters import handle_synology_error


def _write_mcporter_stub(tmp_path: Path, responses_by_name: dict[str, list[str]]) -> Path:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for name, responses in responses_by_name.items():
        (state_dir / f"{name}.responses.json").write_text(json.dumps(responses))

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
                "synology.synology_utilization": "utilization",
            }

            if tool not in tool_map:
                sys.stderr.write(f"unexpected tool: {tool}\\n")
                sys.exit(1)

            name = tool_map[tool]
            responses_path = state_dir / f"{name}.responses.json"
            if not responses_path.exists():
                sys.stderr.write(f"missing stub responses for: {name}\\n")
                sys.exit(1)

            count_path = state_dir / f"{name}.count"
            count = int(count_path.read_text()) if count_path.exists() else 0
            count_path.write_text(str(count + 1))

            responses = json.loads(responses_path.read_text())
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


def _mcp_error_envelope(text: str) -> str:
    return json.dumps({"content": [{"type": "text", "text": text}], "isError": True})


class SynologyCheckTests(unittest.TestCase):
    def run_check(
        self,
        check_name: str,
        *,
        dsm_outputs: list[str] | None = None,
        storage_outputs: list[str] | None = None,
        utilization_outputs: list[str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        tmp_path = Path(tmpdir.name)
        responses_by_name: dict[str, list[str]] = {}
        if dsm_outputs is not None:
            responses_by_name["dsm"] = dsm_outputs
        if storage_outputs is not None:
            responses_by_name["storage"] = storage_outputs
        if utilization_outputs is not None:
            responses_by_name["utilization"] = utilization_outputs

        mcporter_path = _write_mcporter_stub(tmp_path, responses_by_name)
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
            ["bash", str(CHECK_SCRIPT), check_name],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        return result, tmp_path

    def test_health_dashboard_ok_uses_direct_dsm_and_storage_tools(self) -> None:
        result, tmp_path = self.run_check(
            "health_dashboard",
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
        result, tmp_path = self.run_check(
            "health_dashboard",
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
        result, tmp_path = self.run_check(
            "health_dashboard",
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

    def test_utilization_warns_after_known_telemetry_error_retries(self) -> None:
        result, tmp_path = self.run_check(
            "utilization",
            utilization_outputs=[
                json.dumps({"status": "error", "message": "Could not retrieve utilization data"}),
            ],
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "level": "warn",
                "check": "utilization",
                "message": f"telemetry unavailable after 3 attempt(s); debug log: {tmp_path / 'debug' / 'utilization.log'}",
            },
        )
        self.assertEqual(_read_count(tmp_path, "utilization"), 3)

        debug_log = tmp_path / "debug" / "utilization.log"
        self.assertTrue(debug_log.exists())
        log_text = debug_log.read_text()
        self.assertIn("event=tool_error", log_text)
        self.assertIn("event=final_known_error", log_text)

    def test_utilization_accepts_current_tool_schema(self) -> None:
        result, tmp_path = self.run_check(
            "utilization",
            utilization_outputs=[
                json.dumps(
                    {
                        "cpu": {
                            "user_load": 8,
                            "system_load": 4,
                            "other_load": 8,
                            "total_load": 12,
                        },
                        "memory": {
                            "total": "9.6 GB",
                            "used": "8.0 GB",
                            "available": "1.6 GB",
                            "percent_used": 83.4,
                        },
                        "swap": {"percent_used": 12.7},
                    }
                ),
            ],
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "level": "ok",
                "check": "utilization",
                "message": "cpu=12% mem=83.4%",
            },
        )
        self.assertEqual(_read_count(tmp_path, "utilization"), 1)

    def test_utilization_accepts_flattened_schema(self) -> None:
        result, tmp_path = self.run_check(
            "utilization",
            utilization_outputs=[
                json.dumps({"cpu_load_percent": 12.4, "memory_percent": 67.8}),
            ],
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "level": "ok",
                "check": "utilization",
                "message": "cpu=12.4% mem=67.8%",
            },
        )
        self.assertEqual(_read_count(tmp_path, "utilization"), 1)

    def test_utilization_surfaces_mcporter_error_envelope(self) -> None:
        result, tmp_path = self.run_check(
            "utilization",
            utilization_outputs=[
                _mcp_error_envelope("Error executing tool synology_utilization: backend unavailable"),
            ],
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            json.loads(result.stderr),
            {
                "level": "crit",
                "check": "utilization",
                "message": f"Error executing tool synology_utilization: backend unavailable after 3 attempt(s); debug log: {tmp_path / 'debug' / 'utilization.log'}",
            },
        )
        self.assertEqual(_read_count(tmp_path, "utilization"), 3)

        debug_log = tmp_path / "debug" / "utilization.log"
        self.assertTrue(debug_log.exists())
        log_text = debug_log.read_text()
        self.assertIn("event=mcp_error_envelope", log_text)
        self.assertIn("event=tool_error", log_text)

    def test_utilization_warns_on_missing_or_malformed_fields(self) -> None:
        result, tmp_path = self.run_check(
            "utilization",
            utilization_outputs=[
                json.dumps({"cpu": {"total_load": 120}, "memory": {"percent_used": "n/a"}}),
            ],
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "level": "warn",
                "check": "utilization",
                "message": f"missing or malformed cpu/memory fields after 3 attempt(s); debug log: {tmp_path / 'debug' / 'utilization.log'}",
            },
        )
        self.assertEqual(_read_count(tmp_path, "utilization"), 3)

        debug_log = tmp_path / "debug" / "utilization.log"
        self.assertTrue(debug_log.exists())
        self.assertIn("event=malformed_fields", debug_log.read_text())

    def test_utilization_retries_transport_error_and_surfaces_message(self) -> None:
        result, tmp_path = self.run_check(
            "utilization",
            utilization_outputs=[
                json.dumps({"status": "error", "message": "System utilization failed: Cannot reach NAS"}),
            ],
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            json.loads(result.stderr),
            {
                "level": "crit",
                "check": "utilization",
                "message": f"System utilization failed: Cannot reach NAS after 3 attempt(s); debug log: {tmp_path / 'debug' / 'utilization.log'}",
            },
        )
        self.assertEqual(_read_count(tmp_path, "utilization"), 3)

    def test_utilization_replaces_blank_error_suffix_with_unknown_error(self) -> None:
        result, tmp_path = self.run_check(
            "utilization",
            utilization_outputs=[
                json.dumps({"status": "error", "message": "System utilization failed: "}),
            ],
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            json.loads(result.stderr),
            {
                "level": "crit",
                "check": "utilization",
                "message": f"System utilization failed: unknown error after 3 attempt(s); debug log: {tmp_path / 'debug' / 'utilization.log'}",
            },
        )
        self.assertEqual(_read_count(tmp_path, "utilization"), 3)


class FormatterTests(unittest.TestCase):
    def test_handle_synology_error_uses_custom_exception_message(self) -> None:
        payload = json.loads(handle_synology_error(SynoConnectionError("Cannot reach NAS"), "System utilization"))

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["message"], "System utilization failed: Cannot reach NAS")
        self.assertEqual(
            payload["suggestion"],
            "Check that the NAS is online and the host/port configuration is correct.",
        )


if __name__ == "__main__":
    unittest.main()
