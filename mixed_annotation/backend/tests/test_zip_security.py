"""OCR 结果 ZIP 解压安全测试。

覆盖 Windows 特有的路径攻击面：盘符相对路径（``C:/x``）、NTFS 数据流
（``file.txt:ads``）、保留设备名（``CON`` / ``NUL.txt``）、目录穿越、
绝对路径以及符号链接。所有恶意条目都必须抛 ``ServiceError``，且不得在
目标目录之外产生文件。
"""

from __future__ import annotations

import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

import _env  # noqa: F401  # 必须在 config/storage 之前导入

from errors import ServiceError
from services.conversion_service import _extract_result_zip


class ZipExtractionSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="lfm-zip-test-"))
        self.zip_path = self.temp_dir / "result.zip"
        self.destination = self.temp_dir / "out"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_zip(self, entries: list[tuple[str, bytes]]) -> None:
        with zipfile.ZipFile(self.zip_path, "w") as archive:
            for name, content in entries:
                archive.writestr(name, content)

    def _assert_rejected(self, name: str) -> None:
        self._write_zip([("result.md", b"# ok\n"), (name, b"evil")])
        with self.assertRaises(ServiceError):
            _extract_result_zip(self.zip_path, self.destination)
        # 解压失败后目标目录之外不应出现任何文件。
        escaped = {
            self.temp_dir / "evil.txt",
            self.temp_dir / "evil.md",
        }
        for path in escaped:
            self.assertFalse(path.exists(), f"非法条目逃逸到 {path}")

    def test_normal_nested_files_are_extracted(self) -> None:
        self._write_zip(
            [
                ("result.md", "# 标题\n".encode("utf-8")),
                ("images/page-1.png", b"\x89PNG\r\n\x1a\n"),
                ("pages.json", b"[]"),
            ]
        )

        _extract_result_zip(self.zip_path, self.destination)

        self.assertEqual(
            (self.destination / "result.md").read_text(encoding="utf-8"),
            "# 标题\n",
        )
        self.assertEqual(
            (self.destination / "images" / "page-1.png").read_bytes(),
            b"\x89PNG\r\n\x1a\n",
        )
        self.assertEqual((self.destination / "pages.json").read_bytes(), b"[]")

    def test_drive_relative_path_is_rejected(self) -> None:
        self._assert_rejected("C:/evil.txt")

    def test_ntfs_alternate_data_stream_is_rejected(self) -> None:
        self._assert_rejected("file.txt:ads")

    def test_windows_reserved_device_names_are_rejected(self) -> None:
        for name in ("CON", "NUL.txt", "aux.pdf", "COM1.log", "LPT9"):
            with self.subTest(name=name):
                self._assert_rejected(name)

    def test_parent_traversal_is_rejected(self) -> None:
        self._assert_rejected("../evil.txt")
        self._assert_rejected("..\\evil.txt")

    def test_absolute_path_is_rejected(self) -> None:
        self._assert_rejected("/evil.txt")

    def test_trailing_dot_or_space_is_rejected(self) -> None:
        self._assert_rejected("evil.")
        self._assert_rejected("evil ")

    def test_symlink_entry_is_rejected(self) -> None:
        with zipfile.ZipFile(self.zip_path, "w") as archive:
            archive.writestr("result.md", "# ok\n")
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "result.md")

        with self.assertRaises(ServiceError):
            _extract_result_zip(self.zip_path, self.destination)


if __name__ == "__main__":
    unittest.main()
