"""Windows 长路径回归测试。

MinerU 图片名是 64 位哈希；如果 staging/backup 目录继续使用完整 UUID，
解压目标会超过 Windows 默认 260 字符限制（LongPathsEnabled=0）。
"""

from __future__ import annotations

import unittest

import _env  # noqa: F401  # 必须在 config/storage 之前导入

from services import conversion_service

TOKEN = "03527c8b-ea53-4011-b24b-98c3eb14487c"

# 复刻用户实际报错的文件路径前缀。
BASE = (
    r"H:\Git\1CF_win11\Label-fast-main_混合标注\backend\data\projects"
    r"\60be455a-089f-4904-91b5-95fdf705b131\files"
    r"\e0be96c3-56cd-4eaa-a96d-74bcd7ed5eb3"
)
IMAGE = "0b156277eaa2ad25e6309e957987127047c3e7334991367b19c0390d53639152.jpg"


class ConversionPathLengthTests(unittest.TestCase):
    def test_short_token_is_bounded(self) -> None:
        short = conversion_service._short_token(TOKEN)
        self.assertEqual(len(short), 16)
        self.assertNotIn("-", short)

    def test_staging_path_under_windows_limit(self) -> None:
        short = conversion_service._short_token(TOKEN)
        staging_image = f"{BASE}\\.stg-{short}\\images\\{IMAGE}"
        # 留出余量，避免贴着 260 的边界再次失败。
        self.assertLess(len(staging_image), 260)

    def test_backup_path_under_windows_limit(self) -> None:
        short = conversion_service._short_token(TOKEN)
        backup_image = f"{BASE}\\.bak-{short}\\images\\{IMAGE}"
        self.assertLess(len(backup_image), 260)


if __name__ == "__main__":
    unittest.main()
