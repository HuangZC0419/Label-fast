"""MinerU 可用性与引擎选择测试。

通过临时文件与 ``patch.object`` 模拟 MinerU Python / runner 的存在性，
并 mock ``api_available`` / ``mineru_ready``，不真正启动子进程或访问网络。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import mineru_engine


class MineruAvailableTests(unittest.TestCase):
    def test_available_when_python_and_runner_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            python = Path(temp_dir) / "python.exe"
            runner = Path(temp_dir) / "mineru_runner.py"
            python.write_text("", encoding="utf-8")
            runner.write_text("", encoding="utf-8")
            with mock.patch.object(config, "MINERU_PYTHON", python), mock.patch.object(
                config, "MINERU_RUNNER", runner
            ):
                available, reason = mineru_engine.mineru_available()

        self.assertTrue(available)
        self.assertIn("可用", reason)

    def test_unavailable_when_python_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = Path(temp_dir) / "mineru_runner.py"
            runner.write_text("", encoding="utf-8")
            missing = Path(temp_dir) / "not-found.exe"
            with mock.patch.object(config, "MINERU_PYTHON", missing), mock.patch.object(
                config, "MINERU_RUNNER", runner
            ):
                available, reason = mineru_engine.mineru_available()

        self.assertFalse(available)
        self.assertIn("Python", reason)

    def test_unavailable_when_runner_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            python = Path(temp_dir) / "python.exe"
            python.write_text("", encoding="utf-8")
            missing = Path(temp_dir) / "not-found.py"
            with mock.patch.object(config, "MINERU_PYTHON", python), mock.patch.object(
                config, "MINERU_RUNNER", missing
            ):
                available, reason = mineru_engine.mineru_available()

        self.assertFalse(available)
        self.assertIn("runner", reason)


class MineruReadyTests(unittest.TestCase):
    def test_subprocess_available_short_circuits_api(self) -> None:
        with mock.patch.object(
            mineru_engine, "mineru_available", return_value=(True, "子进程可用")
        ), mock.patch.object(mineru_engine, "api_available") as api:
            ready, reason = mineru_engine.mineru_ready()

        self.assertTrue(ready)
        self.assertIn("子进程", reason)
        api.assert_not_called()

    def test_api_available_when_subprocess_missing(self) -> None:
        with mock.patch.object(
            mineru_engine, "mineru_available", return_value=(False, "无 Python")
        ), mock.patch.object(
            mineru_engine, "api_available", return_value=(True, "API 可用")
        ):
            ready, reason = mineru_engine.mineru_ready()

        self.assertTrue(ready)
        self.assertIn("API", reason)

    def test_unavailable_when_subprocess_and_api_fail(self) -> None:
        with mock.patch.object(
            mineru_engine, "mineru_available", return_value=(False, "无 Python")
        ), mock.patch.object(
            mineru_engine, "api_available", return_value=(False, "连接拒绝")
        ):
            ready, reason = mineru_engine.mineru_ready()

        self.assertFalse(ready)
        self.assertIn("无 Python", reason)
        self.assertIn("连接拒绝", reason)


class SelectEngineTests(unittest.TestCase):
    def _select(self, *, ocr_engine: str, available: bool, override: str | None = None) -> str:
        with mock.patch.object(config, "OCR_ENGINE", ocr_engine), mock.patch.object(
            mineru_engine, "mineru_ready", return_value=(available, "mock")
        ):
            return mineru_engine.select_engine(override)

    def test_config_paddle_always_uses_paddle(self) -> None:
        self.assertEqual(self._select(ocr_engine="paddle", available=True), "paddle")

    def test_config_mineru_uses_mineru_when_available(self) -> None:
        self.assertEqual(self._select(ocr_engine="mineru", available=True), "mineru")

    def test_explicit_mineru_does_not_silently_downgrade(self) -> None:
        # 显式 mineru + 不可用：仍返回 mineru，让转换抛出明确错误。
        self.assertEqual(self._select(ocr_engine="auto", available=False, override="mineru"), "mineru")

    def test_auto_prefers_mineru_when_available(self) -> None:
        self.assertEqual(self._select(ocr_engine="auto", available=True), "mineru")

    def test_auto_never_falls_back_to_paddle(self) -> None:
        # Paddle 回退已禁用（中文路径限制）；auto 仍返回 mineru，由转换层报错。
        self.assertEqual(self._select(ocr_engine="auto", available=False), "mineru")

    def test_override_paddle_wins_over_config(self) -> None:
        self.assertEqual(
            self._select(ocr_engine="mineru", available=True, override="paddle"),
            "paddle",
        )

    def test_override_auto_respects_availability(self) -> None:
        self.assertEqual(
            self._select(ocr_engine="mineru", available=False, override="auto"),
            "mineru",
        )
        self.assertEqual(
            self._select(ocr_engine="paddle", available=True, override="auto"),
            "mineru",
        )

    def test_empty_override_uses_config(self) -> None:
        # /convert 默认传空字符串，应回落到 OCR_ENGINE 配置而不是固定 auto。
        self.assertEqual(self._select(ocr_engine="paddle", available=True, override=""), "paddle")
        self.assertEqual(self._select(ocr_engine="auto", available=True, override=""), "mineru")

    def test_invalid_override_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._select(ocr_engine="auto", available=True, override="gpu")

    def test_invalid_config_falls_back_to_auto(self) -> None:
        self.assertEqual(self._select(ocr_engine="cuda", available=True), "mineru")
        self.assertEqual(self._select(ocr_engine="cuda", available=False), "mineru")

    def test_case_and_whitespace_are_normalized(self) -> None:
        self.assertEqual(self._select(ocr_engine=" PADDLE ", available=True), "paddle")
        self.assertEqual(self._select(ocr_engine="auto", available=True, override=" MinerU "), "mineru")


if __name__ == "__main__":
    unittest.main()
