"""跨项目标签目录的汇总逻辑测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _env  # noqa: F401  # 必须在 config/storage 之前导入

import storage


class LabelCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="labelfast-label-catalog-")
        root = Path(self._tmp.name)
        self.dirs = {"p1": root / "p1", "p2": root / "p2"}
        for directory in self.dirs.values():
            (directory / "files").mkdir(parents=True)

        self._write_annotations(self.dirs["p1"], "f1", ["A", "A", "B"])
        self._write_annotations(self.dirs["p2"], "f2", ["B", "C", "C"])

        self.projects = [
            {"id": "p1", "labels": ["A", "B"]},
            {"id": "p2", "labels": ["B", "C"]},
        ]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_annotations(self, directory: Path, name: str, labels: list[str]) -> None:
        file_dir = directory / "files" / name
        file_dir.mkdir(parents=True)
        spans = [
            {"id": index + 1, "start": index * 2, "end": index * 2 + 1, "label": label}
            for index, label in enumerate(labels)
        ]
        (file_dir / "annotations.json").write_text(
            json.dumps({"text": "占位", "spans": spans, "relations": [], "paragraphs": []}),
            encoding="utf-8",
        )

    def _run_catalog(self, exclude: str | None = None) -> list[dict]:
        with (
            mock.patch.object(storage, "list_projects", return_value=self.projects),
            mock.patch.object(
                storage,
                "get_project",
                side_effect=lambda pid: next(item for item in self.projects if item["id"] == pid),
            ),
            mock.patch.object(
                storage, "_project_dir", side_effect=lambda pid: self.dirs[pid]
            ),
        ):
            return storage.label_catalog(exclude)

    def test_aggregates_labels_and_usage_across_projects(self) -> None:
        rows = {row["label"]: row for row in self._run_catalog()}
        self.assertEqual(rows["A"]["project_count"], 1)
        self.assertEqual(rows["A"]["usage_count"], 2)
        self.assertEqual(rows["B"]["project_count"], 2)
        self.assertEqual(rows["B"]["usage_count"], 2)
        self.assertEqual(rows["C"]["project_count"], 1)
        self.assertEqual(rows["C"]["usage_count"], 2)

    def test_exclude_current_project(self) -> None:
        rows = {row["label"]: row for row in self._run_catalog("p1")}
        self.assertNotIn("A", rows)
        self.assertEqual(rows["B"]["project_count"], 1)
        self.assertEqual(rows["B"]["usage_count"], 1)
        self.assertEqual(rows["C"]["usage_count"], 2)

    def test_sorted_by_usage_desc(self) -> None:
        labels = [row["label"] for row in self._run_catalog()]
        self.assertEqual(labels[0], "B")  # 3 次引用，最多


if __name__ == "__main__":
    unittest.main()

