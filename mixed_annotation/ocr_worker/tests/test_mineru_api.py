"""常驻 mineru-api 传输的纯单元测试。

覆盖：multipart 表单字段、ZIP 安全解压、任务失败状态抛错。全部使用
mock / 临时文件，不访问网络。
"""

from __future__ import annotations

import stat
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import mineru_engine


class BuildApiFormDataTests(unittest.TestCase):
    def test_expected_fields(self) -> None:
        data = mineru_engine.build_api_form_data(
            enable_table=True, enable_formula=False
        )

        self.assertEqual(data["lang_list"], config.MINERU_LANGUAGE)
        self.assertEqual(data["backend"], config.MINERU_BACKEND)
        self.assertEqual(data["parse_method"], config.MINERU_PARSE_METHOD)
        self.assertEqual(data["table_enable"], "true")
        self.assertEqual(data["formula_enable"], "false")
        for key in (
            "return_md",
            "return_middle_json",
            "return_content_list",
            "return_images",
            "response_format_zip",
        ):
            self.assertEqual(data[key], "true", key)
        self.assertEqual(data["return_original_file"], "false")
        self.assertEqual(data["start_page_id"], "0")
        self.assertEqual(data["end_page_id"], "99999")

    def test_toggle_flags(self) -> None:
        data = mineru_engine.build_api_form_data(
            enable_table=False, enable_formula=True
        )

        self.assertEqual(data["table_enable"], "false")
        self.assertEqual(data["formula_enable"], "true")


def _write_zip(path: Path, entries: list[tuple[str, bytes, int | None]]) -> None:
    """entries: (name, content, external_attr)。"""

    with zipfile.ZipFile(path, "w") as archive:
        for name, content, external_attr in entries:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if external_attr is not None:
                info.external_attr = external_attr
            archive.writestr(info, content)


class SafeExtractTests(unittest.TestCase):
    def test_extracts_nested_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "result.zip"
            target = root / "out"
            _write_zip(
                archive_path,
                [
                    ("doc/result.md", "# 标题".encode("utf-8"), None),
                    ("doc/images/a.jpg", b"image-bytes", None),
                ],
            )

            count = mineru_engine._safe_extract_zip(archive_path, target)

            self.assertEqual(count, 2)
            self.assertEqual(
                (target / "doc" / "result.md").read_text(encoding="utf-8"),
                "# 标题",
            )
            self.assertEqual(
                (target / "doc" / "images" / "a.jpg").read_bytes(),
                b"image-bytes",
            )

    def test_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "result.zip"
            _write_zip(archive_path, [("../evil.txt", b"x", None)])

            with self.assertRaises(RuntimeError) as ctx:
                mineru_engine._safe_extract_zip(archive_path, root / "out")

            self.assertIn("非法路径", str(ctx.exception))
            self.assertFalse((root / "evil.txt").exists())

    def test_rejects_posix_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "result.zip"
            _write_zip(archive_path, [("/abs/evil.txt", b"x", None)])

            with self.assertRaises(RuntimeError) as ctx:
                mineru_engine._safe_extract_zip(archive_path, root / "out")

            self.assertIn("非法路径", str(ctx.exception))

    def test_rejects_windows_drive_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "result.zip"
            _write_zip(archive_path, [("C:/evil.txt", b"x", None)])

            with self.assertRaises(RuntimeError) as ctx:
                mineru_engine._safe_extract_zip(archive_path, root / "out")

            self.assertIn("非法路径", str(ctx.exception))

    def test_rejects_symlink_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "result.zip"
            _write_zip(
                archive_path,
                [("link", b"C:/Windows/system32", (stat.S_IFLNK | 0o777) << 16)],
            )

            with self.assertRaises(RuntimeError) as ctx:
                mineru_engine._safe_extract_zip(archive_path, root / "out")

            self.assertIn("符号链接", str(ctx.exception))


class _FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> object:
        return self._payload


class _FakeClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls = 0

    def get(self, _url: str) -> _FakeResponse:
        self.calls += 1
        return _FakeResponse(self.payload)


class PollApiTaskTests(unittest.TestCase):
    def _poll(self, payload: dict, timeout: int = 5) -> _FakeClient:
        client = _FakeClient(payload)
        with mock.patch.object(config, "MINERU_API_POLL_SECONDS", 0.05):
            mineru_engine._poll_api_task(
                client,
                "task-1",
                timeout=timeout,
                report=lambda *_: None,
                started=time.monotonic(),
            )
        return client

    def test_completed_status_returns(self) -> None:
        client = self._poll({"task_id": "task-1", "status": "completed"})
        self.assertEqual(client.calls, 1)

    def test_failed_status_raises_with_error(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._poll(
                {"task_id": "task-1", "status": "failed", "error": "模型崩了"}
            )
        self.assertIn("模型崩了", str(ctx.exception))

    def test_failed_status_without_error_still_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self._poll({"task_id": "task-1", "status": "failed"})
        self.assertIn("未知错误", str(ctx.exception))

    def test_pending_then_timeout_raises(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            # started 提前 10 秒，timeout=1 → 立即超时。
            with mock.patch.object(config, "MINERU_API_POLL_SECONDS", 0.01):
                mineru_engine._poll_api_task(
                    _FakeClient({"status": "processing"}),
                    "task-1",
                    timeout=1,
                    report=lambda *_: None,
                    started=time.monotonic() - 10,
                )
        self.assertIn("超时", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
