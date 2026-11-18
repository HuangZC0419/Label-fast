"""夜间队列加固测试。

覆盖：
- 待处理列表耗尽后才重新扫描，新入队文件可被 wake() 立即处理；
- 队列转换使用更短的单文件超时，普通转换保持原超时；
- 终态（completed）不会被陈旧令牌改回 failed/uploaded；
- 转换协程抛出未预期异常时文件不会永久停留在 converting；
- 文件列表同一秒内按 queue_seq 稳定倒序；
- 项目详情隐藏内部 uploading 记录；
- 启动时用历史最大 queue_seq 初始化进程内计数器。
"""

from __future__ import annotations

import asyncio
import os
import time
import unittest
from unittest import mock

import _env  # noqa: F401  # 必须在 config/storage 之前导入

import config
import storage
from routes import projects as projects_routes
from services import conversion_service, ocr_client, queue_service


def _new_file(project_id: str, name: str, seq: int | None = None) -> dict:
    """创建测试文件元数据；可按需求覆盖 queue_seq。"""

    meta, _ = storage.create_file(
        project_id,
        name,
        ".pdf",
        source_type="pdf",
        enable_table=True,
        enable_formula=False,
        dpi=200,
    )
    if seq is not None:
        meta = storage.update_file(meta["id"], {"queue_seq": seq})
    return meta


async def _worker_ready() -> bool:
    return True


class QueuePendingWakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("队列待处理列表测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_new_file_after_batch_is_processed_on_wake(self) -> None:
        first = _new_file(self.project["id"], "first.pdf", seq=100)
        second = _new_file(self.project["id"], "second.pdf", seq=200)
        calls: list[str] = []

        async def fake_run(file_id: str) -> bool:
            calls.append(file_id)
            storage.update_file(file_id, {"status": "completed"})
            return True

        async def scenario() -> str:
            third: dict = {}
            with mock.patch.dict(
                os.environ, {"MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05"}
            ), mock.patch.object(
                ocr_client, "worker_available", new=_worker_ready
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    deadline = time.monotonic() + 10
                    while not {first["id"], second["id"]}.issubset(set(calls)):
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                    # 一批处理完后新增文件：queue_seq 更大，应排在后面。
                    third = _new_file(self.project["id"], "third.pdf")
                    queue_service.wake()
                    deadline = time.monotonic() + 10
                    while third["id"] not in calls:
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                finally:
                    await queue_service.stop()
            return third["id"]

        third_id = asyncio.run(scenario())

        our_order = [
            file_id
            for file_id in calls
            if file_id in {first["id"], second["id"], third_id}
        ]
        self.assertEqual(our_order, [first["id"], second["id"], third_id])
        self.assertEqual(storage.get_file(third_id)["status"], "completed")

    def test_scan_interval_is_not_shorter_than_before(self) -> None:
        # 只约束行为下限：空闲兜底扫描不得比原来的 2 秒更频繁，
        # 不绑定具体实现常量，避免无意义地锁死 10 秒这个数值。
        self.assertGreaterEqual(queue_service._SCAN_INTERVAL_SECONDS, 2.0)


class QueuePendingOrderTests(unittest.TestCase):
    """pending 缓存必须保持队首原位，故障/重试不得打乱 queue_seq 顺序。"""

    def setUp(self) -> None:
        self.project = storage.create_project("队列顺序回归测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_worker_outage_does_not_rotate_queue_order(self) -> None:
        first = _new_file(self.project["id"], "a.pdf", seq=100)
        second = _new_file(self.project["id"], "b.pdf", seq=200)
        third = _new_file(self.project["id"], "c.pdf", seq=300)
        our_ids = {first["id"], second["id"], third["id"]}
        calls: list[str] = []
        health = {"count": 0}

        async def fake_available() -> bool:
            # 前两次探测不可用，恢复后必须仍从 a 开始，而不是 b/c/a。
            health["count"] += 1
            return health["count"] > 2

        async def fake_run(file_id: str) -> bool:
            calls.append(file_id)
            storage.update_file(file_id, {"status": "completed"})
            return True

        async def scenario() -> None:
            with mock.patch.dict(
                os.environ, {"MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05"}
            ), mock.patch.object(
                ocr_client, "worker_available", new=fake_available
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    deadline = time.monotonic() + 10
                    while not our_ids.issubset(set(calls)):
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                finally:
                    await queue_service.stop()

        asyncio.run(scenario())

        order = [file_id for file_id in calls if file_id in our_ids]
        self.assertEqual(order, [first["id"], second["id"], third["id"]])
        self.assertGreaterEqual(health["count"], 3)

    def test_requeued_file_is_retried_before_batch_continues(self) -> None:
        first = _new_file(self.project["id"], "a.pdf", seq=100)
        second = _new_file(self.project["id"], "b.pdf", seq=200)
        third = _new_file(self.project["id"], "c.pdf", seq=300)
        our_ids = {first["id"], second["id"], third["id"]}
        calls: list[str] = []
        attempts = {"first": 0}

        async def fake_run(file_id: str) -> bool:
            calls.append(file_id)
            if file_id == first["id"] and attempts["first"] == 0:
                attempts["first"] += 1
                storage.update_file(
                    first["id"],
                    {
                        "status": "failed",
                        "stage": "转换失败",
                        "message": "转换失败",
                        "error": "无法连接 OCR Worker：connection refused",
                        "conversion_token": "token-first",
                    },
                )
                return True
            storage.update_file(file_id, {"status": "completed"})
            return True

        async def scenario() -> None:
            with mock.patch.dict(
                os.environ,
                {
                    "MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05",
                    "MIX_QUEUE_MAX_RETRIES": "3",
                },
            ), mock.patch.object(
                ocr_client, "worker_available", new=_worker_ready
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    deadline = time.monotonic() + 10
                    while third["id"] not in calls:
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                finally:
                    await queue_service.stop()

        asyncio.run(scenario())

        order = [file_id for file_id in calls if file_id in our_ids]
        # a 首次失败后退回队首，必须在下一次重试 a 之后才轮到 b、c。
        self.assertEqual(
            order,
            [first["id"], first["id"], second["id"], third["id"]],
        )
        self.assertEqual(storage.get_file(first["id"])["status"], "completed")
        self.assertEqual(storage.get_file(first["id"])["queue_retry_count"], 1)


class QueueTaskTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("队列超时测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_queued_conversion_uses_queue_timeout(self) -> None:
        meta = _new_file(self.project["id"], "queued.pdf")
        captured: dict = {}

        async def fake_run(
            file_id: str,
            token: str,
            worker_options: dict,
            worker_filename: str,
            worker_content_type: str,
            *,
            requeue_on_cancel: bool = False,
            timeout_seconds: float | None = None,
        ) -> None:
            captured["timeout_seconds"] = timeout_seconds
            storage.update_file(file_id, {"status": "completed"})

        async def scenario() -> bool:
            with mock.patch.object(
                conversion_service, "_run_conversion", new=fake_run
            ):
                return await conversion_service.run_queued_conversion(meta["id"])

        self.assertTrue(asyncio.run(scenario()))
        self.assertEqual(
            captured.get("timeout_seconds"), config.OCR_QUEUE_TASK_TIMEOUT
        )

    def test_immediate_conversion_keeps_default_timeout(self) -> None:
        meta = _new_file(self.project["id"], "immediate.pdf")
        run_mock = mock.AsyncMock()

        async def scenario() -> None:
            with mock.patch.object(
                conversion_service, "_run_conversion", new=run_mock
            ):
                await conversion_service.start_conversion(
                    meta["id"],
                    enable_table=True,
                    enable_formula=False,
                    dpi=200,
                    reset_results=False,
                    filename="source.pdf",
                    content_type="application/pdf",
                )
                tasks = list(conversion_service._tasks)
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run(scenario())

        run_mock.assert_awaited_once()
        # 普通转换不传 timeout_seconds，沿用 OCR_TASK_TIMEOUT（6 小时）。
        self.assertIsNone(
            run_mock.call_args.kwargs.get("timeout_seconds")
        )


class TerminalStateGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("终态保护测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def _completed_file(self, token: str) -> dict:
        meta = _new_file(self.project["id"], "done.pdf")
        storage.update_file(
            meta["id"],
            {"status": "completed", "progress": 100, "conversion_token": token},
        )
        return meta

    def test_fail_with_stale_token_keeps_completed(self) -> None:
        meta = self._completed_file("old-token")

        asyncio.run(
            conversion_service._fail_if_current(
                meta["id"], "old-token", "陈旧协程失败"
            )
        )

        stored = storage.get_file(meta["id"])
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["progress"], 100)
        self.assertEqual(stored["error"], "")
        self.assertEqual(stored["conversion_token"], "old-token")

    def test_requeue_with_stale_token_keeps_completed(self) -> None:
        meta = self._completed_file("old-token")

        conversion_service._requeue_if_current(meta["id"], "old-token")

        stored = storage.get_file(meta["id"])
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["progress"], 100)
        self.assertEqual(stored["conversion_token"], "old-token")

    def test_fail_clears_token_on_converting(self) -> None:
        meta = _new_file(self.project["id"], "running.pdf")
        storage.update_file(
            meta["id"],
            {"status": "converting", "conversion_token": "active-token"},
        )

        asyncio.run(
            conversion_service._fail_if_current(
                meta["id"], "active-token", "转换失败"
            )
        )

        stored = storage.get_file(meta["id"])
        self.assertEqual(stored["status"], "failed")
        self.assertEqual(stored["conversion_token"], "")
        self.assertEqual(stored["error"], "转换失败")


class QueueInternalErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("队列内部异常测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_unexpected_exception_marks_converting_failed(self) -> None:
        first = _new_file(self.project["id"], "boom.pdf", seq=100)
        second = _new_file(self.project["id"], "next.pdf", seq=200)
        calls: list[str] = []

        async def fake_run(file_id: str) -> bool:
            calls.append(file_id)
            if file_id == first["id"]:
                # 模拟 run_queued_conversion 已置为 converting 后抛异常。
                storage.update_file(
                    file_id,
                    {
                        "status": "converting",
                        "conversion_token": "token-boom",
                    },
                )
                raise RuntimeError("模拟未知异常")
            storage.update_file(file_id, {"status": "completed"})
            return True

        async def scenario() -> None:
            with mock.patch.dict(
                os.environ, {"MIX_QUEUE_WORKER_RETRY_SECONDS": "0.05"}
            ), mock.patch.object(
                ocr_client, "worker_available", new=_worker_ready
            ), mock.patch.object(
                conversion_service, "run_queued_conversion", new=fake_run
            ):
                await queue_service.start()
                try:
                    deadline = time.monotonic() + 10
                    while second["id"] not in calls:
                        if time.monotonic() > deadline:
                            break
                        await asyncio.sleep(0.02)
                finally:
                    await queue_service.stop()

        asyncio.run(scenario())

        stored = storage.get_file(first["id"])
        self.assertEqual(stored["status"], "failed")
        self.assertEqual(stored["stage"], "转换失败")
        self.assertEqual(stored["error"], "转换发生内部错误，请重试")
        self.assertEqual(stored["conversion_token"], "")
        self.assertEqual(storage.get_file(second["id"])["status"], "completed")


class FileListSortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("文件列表排序测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_same_created_at_orders_by_queue_seq_desc(self) -> None:
        fixed_time = "2026-01-01T00:00:00Z"
        with mock.patch.object(storage, "utc_now", return_value=fixed_time):
            low = _new_file(self.project["id"], "low.pdf", seq=100)
            high = _new_file(self.project["id"], "high.pdf", seq=200)
            middle = _new_file(self.project["id"], "middle.pdf", seq=150)

        first_pass = [meta["id"] for meta in storage.list_files(self.project["id"])]
        second_pass = [meta["id"] for meta in storage.list_files(self.project["id"])]

        expected = [high["id"], middle["id"], low["id"]]
        self.assertEqual(first_pass, expected)
        # 顺序必须是稳定的，刷新列表不会跳动。
        self.assertEqual(second_pass, expected)


class ProjectDetailVisibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("详情可见性测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_uploading_files_are_hidden_from_detail(self) -> None:
        uploading, _ = storage.create_file(
            self.project["id"],
            "uploading.pdf",
            ".pdf",
            source_type="pdf",
            enable_table=True,
            enable_formula=False,
            dpi=200,
            initial_status="uploading",
        )
        uploaded = _new_file(self.project["id"], "ready.pdf")

        detail = projects_routes.get_project_detail(self.project["id"])
        ids = {item["id"] for item in detail["files"]}
        statuses = {item["status"] for item in detail["files"]}

        self.assertIn(uploaded["id"], ids)
        self.assertNotIn(uploading["id"], ids)
        self.assertNotIn("uploading", statuses)


class QueueSeqInitializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = storage.create_project("队列序号初始化测试", [], [])

    def tearDown(self) -> None:
        storage.delete_project(self.project["id"])

    def test_initialize_storage_advances_last_queue_seq(self) -> None:
        seed = max(storage._last_queue_seq, time.time_ns()) + 10**9
        legacy = _new_file(self.project["id"], "legacy.pdf", seq=seed)

        storage.initialize_storage()
        newer = _new_file(self.project["id"], "new.pdf")

        self.assertGreater(newer["queue_seq"], seed)
        self.assertGreater(newer["queue_seq"], legacy["queue_seq"])


if __name__ == "__main__":
    unittest.main()
