import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from synology_mcp.tools.task_scheduler import (
    TaskSchedulerEnableInput,
    TaskSchedulerNasInput,
    TaskSchedulerTaskInput,
    register_task_scheduler_tools,
)


class RecordingMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, *, name, annotations):
        def decorator(func):
            self.tools[name] = func
            return func

        return decorator


class FakeConnectionManager:
    def __init__(self, client) -> None:
        self.client = client

    def get_client(self, service, nas_name=None):
        assert service == "task_scheduler"
        return self.client


class FakeTaskScheduler:
    def __init__(self) -> None:
        self.calls = []
        self.gen_list = {"SYNO.Core.TaskScheduler": {"path": "entry.cgi"}}
        self.tasks = [
            {
                "id": 1,
                "name": "Auto S.M.A.R.T. Test",
                "type": "custom",
                "enable": True,
                "owner": "root",
                "real_owner": "root",
                "next_trigger_time": "2026-03-20 00:01",
            },
            {
                "id": 7,
                "name": "Empty Recycle Bins",
                "type": "recycle",
                "enable": True,
                "owner": "root",
                "real_owner": "root",
                "next_trigger_time": "2026-03-20 01:00",
            },
        ]

    def request_data(self, api, path, params):
        self.calls.append((api, path, dict(params)))
        method = params["method"]

        if method == "list":
            offset = params["offset"]
            limit = params["limit"]
            page = self.tasks[offset : offset + limit]
            return {"data": {"tasks": page, "total": len(self.tasks)}, "success": True}

        if method == "get":
            return {
                "data": {
                    "id": params["id"],
                    "real_owner": params["real_owner"],
                    "name": "Auto S.M.A.R.T. Test",
                },
                "success": True,
            }

        if method == "run":
            return {"success": True}

        if method == "set_enable":
            return {"success": True}

        if method == "get_history_status_list":
            return {"data": [], "success": True}

        raise AssertionError(f"unexpected method: {method}")


class TaskSchedulerToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = FakeTaskScheduler()
        self.mcp = RecordingMCP()
        register_task_scheduler_tools(self.mcp, FakeConnectionManager(self.client))

    async def test_list_tasks_uses_supported_list_version(self) -> None:
        result = await self.mcp.tools["synology_scheduled_tasks_list"](TaskSchedulerNasInput())
        payload = json.loads(result)

        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["tasks"][0]["real_owner"], "root")

        list_call = next(params for _, _, params in self.client.calls if params["method"] == "list")
        self.assertEqual(list_call["version"], 2)

    async def test_task_info_resolves_real_owner_and_uses_supported_get_version(self) -> None:
        result = await self.mcp.tools["synology_scheduled_task_info"](TaskSchedulerTaskInput(task_id=7))
        payload = json.loads(result)

        self.assertEqual(payload["id"], 7)
        self.assertEqual(payload["real_owner"], "root")

        get_call = next(params for _, _, params in self.client.calls if params["method"] == "get")
        self.assertEqual(get_call["version"], 3)
        self.assertEqual(get_call["real_owner"], "root")

    async def test_task_run_resolves_real_owner_before_calling_dsm(self) -> None:
        result = await self.mcp.tools["synology_scheduled_task_run"](TaskSchedulerTaskInput(task_id=7))
        payload = json.loads(result)

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["real_owner"], "root")

        run_call = next(params for _, _, params in self.client.calls if params["method"] == "run")
        self.assertEqual(run_call["version"], 2)
        self.assertEqual(json.loads(run_call["tasks"]), [{"id": 7, "real_owner": "root"}])

    async def test_task_enable_resolves_real_owner_before_calling_dsm(self) -> None:
        result = await self.mcp.tools["synology_scheduled_task_enable"](
            TaskSchedulerEnableInput(task_id=7, enabled=False)
        )
        payload = json.loads(result)

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["real_owner"], "root")

        enable_call = next(params for _, _, params in self.client.calls if params["method"] == "set_enable")
        self.assertEqual(enable_call["version"], 2)
        self.assertEqual(
            json.loads(enable_call["status"]),
            [{"id": 7, "real_owner": "root", "enable": False}],
        )


if __name__ == "__main__":
    unittest.main()
