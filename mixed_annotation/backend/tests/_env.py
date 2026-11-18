"""测试环境隔离。

必须在导入 ``config`` / ``storage`` 之前导入本模块：
把运行期数据目录指向临时目录，避免污染 ``backend/data``。
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

TEMP_DATA_DIR = tempfile.mkdtemp(prefix="labelfast-tests-")
os.environ["BACKEND_DATA_DIR"] = TEMP_DATA_DIR

atexit.register(lambda: shutil.rmtree(TEMP_DATA_DIR, ignore_errors=True))
