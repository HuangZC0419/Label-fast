import importlib
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

image_app = importlib.import_module("图像标注器.label_system.app")


class ProjectConfigFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="image-labeler-tests-"))
        self.projects_root = self.temp_dir / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.projects_file = self.temp_dir / "projects.json"
        self.projects_file.write_text("[]", encoding="utf-8")

        self.original_project_root = image_app.PROJECT_ROOT
        self.original_projects_file = image_app.PROJECTS_FILE
        self.original_current_config = image_app.current_config
        self.original_current_project_name = image_app.current_project_name
        self.original_current_project_id = image_app.current_project_id
        self.original_active_project = image_app.active_project

        image_app.PROJECT_ROOT = str(self.temp_dir)
        image_app.PROJECTS_FILE = str(self.projects_file)
        image_app.current_config = image_app.Config(image_dir="", jsonl_path="")
        image_app.current_project_name = ""
        image_app.current_project_id = ""
        image_app.active_project = None

        self.client = TestClient(image_app.app)

    def tearDown(self) -> None:
        image_app.PROJECT_ROOT = self.original_project_root
        image_app.PROJECTS_FILE = self.original_projects_file
        image_app.current_config = self.original_current_config
        image_app.current_project_name = self.original_current_project_name
        image_app.current_project_id = self.original_current_project_id
        image_app.active_project = self.original_active_project
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def read_projects(self):
        return json.loads(self.projects_file.read_text(encoding="utf-8"))

    def read_image_template(self) -> str:
        template_path = BACKEND_ROOT / "图像标注器" / "label_system" / "templates" / "index.html"
        return template_path.read_text(encoding="utf-8")

    def test_projects_start_empty_and_ignore_filesystem_directories(self):
        stray_project_dir = self.temp_dir / "projects" / "旧目录项目" / "images"
        stray_project_dir.mkdir(parents=True, exist_ok=True)
        (stray_project_dir / "1.png").write_bytes(b"fake")

        response = self.client.get("/api/projects")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        self.assertEqual(self.read_projects(), [])

    def test_create_project_is_create_only(self):
        response = self.client.post(
            "/api/projects",
            json={
                "id": "",
                "name": "项目A",
                "image_dir": "",
                "jsonl_path": "",
                "labels": ["猫", "狗"],
            },
        )

        self.assertEqual(response.status_code, 200)
        project = response.json()
        self.assertEqual(project["project_dir"], "projects/项目A")
        self.assertEqual(project["image_dir"], "projects/项目A/images")
        self.assertEqual(project["jsonl_path"], "projects/项目A/标注结果_qa.jsonl")
        self.assertEqual(project["box_jsonl_path"], "projects/项目A/标注结果_boxes.jsonl")
        self.assertTrue((self.temp_dir / "projects" / "项目A" / "images").is_dir())

        saved_projects = self.read_projects()
        self.assertEqual(saved_projects[0]["labels"], ["猫", "狗"])

        duplicate_name_response = self.client.post(
            "/api/projects",
            json={
                "id": "",
                "name": "项目A",
                "image_dir": "",
                "jsonl_path": "",
                "labels": [],
            },
        )
        self.assertEqual(duplicate_name_response.status_code, 400)

        update_attempt = self.client.post(
            "/api/projects",
            json={
                "id": project["id"],
                "name": "项目A-改名",
                "project_dir": project["project_dir"],
                "image_dir": project["image_dir"],
                "jsonl_path": project["jsonl_path"],
                "box_jsonl_path": project["box_jsonl_path"],
                "labels": ["新标签"],
            },
        )
        self.assertEqual(update_attempt.status_code, 400)
        self.assertEqual(project["project_dir"], "projects/项目A")
        self.assertEqual(saved_projects[0]["project_dir"], "projects/项目A")

    def test_save_current_project_persists_labels_and_progress_without_rename(self):
        create_response = self.client.post(
            "/api/projects",
            json={
                "id": "",
                "name": "保存项目",
                "image_dir": "",
                "jsonl_path": "",
                "labels": ["原标签"],
            },
        )
        self.assertEqual(create_response.status_code, 200)
        project = create_response.json()
        self.client.post(f"/api/projects/switch/{project['id']}")

        save_current_response = self.client.post(
            "/api/projects/current",
            json={
                "last_image": "3.png",
                "labels": ["新标签"],
            },
        )
        self.assertEqual(save_current_response.status_code, 200)
        saved_project = save_current_response.json()
        self.assertEqual(saved_project["name"], "保存项目")
        self.assertEqual(saved_project["labels"], ["新标签"])
        self.assertEqual(saved_project["last_image"], "3.png")

        renamed_save_attempt = self.client.post(
            "/api/projects/current",
            json={
                "name": "偷偷改名",
                "labels": ["其它标签"],
            },
        )
        self.assertEqual(renamed_save_attempt.status_code, 400)

        saved_projects = self.read_projects()
        self.assertEqual(saved_projects[0]["name"], "保存项目")
        self.assertEqual(saved_projects[0]["labels"], ["新标签"])
        self.assertEqual(saved_projects[0]["last_image"], "3.png")

    def test_save_current_project_persists_current_annotations(self):
        create_response = self.client.post(
            "/api/projects",
            json={
                "id": "",
                "name": "完整保存项目",
                "image_dir": "",
                "jsonl_path": "",
                "labels": ["旧标签"],
            },
        )
        self.assertEqual(create_response.status_code, 200)
        project = create_response.json()
        self.client.post(f"/api/projects/switch/{project['id']}")

        save_current_response = self.client.post(
            "/api/projects/current",
            json={
                "last_image": "1.png",
                "labels": ["猫", "狗"],
                "qa_records": [
                    {
                        "image": "1.png",
                        "user_content": "描述图片",
                        "assistant_content": "这是项目自己的问答标注",
                    }
                ],
                "box_records": [
                    {
                        "image": "1.png",
                        "boxes": [
                            {"x1": 1, "y1": 2, "x2": 11, "y2": 12, "label": "猫"}
                        ],
                    }
                ],
            },
        )
        self.assertEqual(save_current_response.status_code, 200)

        qa_path = self.temp_dir / "projects" / "完整保存项目" / "标注结果_qa.jsonl"
        boxes_path = self.temp_dir / "projects" / "完整保存项目" / "标注结果_boxes.jsonl"
        self.assertTrue(qa_path.exists())
        self.assertTrue(boxes_path.exists())

        qa_lines = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        box_lines = [json.loads(line) for line in boxes_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(qa_lines, [{
            "conversations": [
                {"role": "user", "content": "描述图片\n<image>"},
                {"role": "assistant", "content": "这是项目自己的问答标注"},
            ],
            "image": "1.png",
        }])
        self.assertEqual(box_lines, [{
            "image": "1.png",
            "boxes": [{"x1": 1, "y1": 2, "x2": 11, "y2": 12, "label": "猫"}],
        }])

    def test_same_image_name_is_isolated_between_projects(self):
        create_a = self.client.post(
            "/api/projects",
            json={
                "id": "",
                "name": "项目A",
                "image_dir": "",
                "jsonl_path": "",
                "labels": [],
            },
        )
        self.assertEqual(create_a.status_code, 200)
        project_a = create_a.json()

        create_b = self.client.post(
            "/api/projects",
            json={
                "id": "",
                "name": "项目B",
                "image_dir": "",
                "jsonl_path": "",
                "labels": [],
            },
        )
        self.assertEqual(create_b.status_code, 200)
        project_b = create_b.json()

        self.client.post(f"/api/projects/switch/{project_a['id']}")
        save_a = self.client.post(
            "/api/projects/current",
            json={
                "last_image": "same.png",
                "labels": ["A标签"],
                "qa_records": [
                    {
                        "image": "same.png",
                        "user_content": "A项目图片",
                        "assistant_content": "A项目答案",
                    }
                ],
                "box_records": [
                    {
                        "image": "same.png",
                        "boxes": [
                            {"x1": 10, "y1": 20, "x2": 30, "y2": 40, "label": "A标签"}
                        ],
                    }
                ],
            },
        )
        self.assertEqual(save_a.status_code, 200)

        self.client.post(f"/api/projects/switch/{project_b['id']}")
        save_b = self.client.post(
            "/api/projects/current",
            json={
                "last_image": "same.png",
                "labels": ["B标签"],
                "qa_records": [
                    {
                        "image": "same.png",
                        "user_content": "B项目图片",
                        "assistant_content": "B项目答案",
                    }
                ],
                "box_records": [
                    {
                        "image": "same.png",
                        "boxes": [
                            {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "label": "B标签"}
                        ],
                    }
                ],
            },
        )
        self.assertEqual(save_b.status_code, 200)

        self.client.post(f"/api/projects/switch/{project_a['id']}")
        annotations_a = self.client.get("/api/annotations")
        self.assertEqual(annotations_a.status_code, 200)
        self.assertEqual(annotations_a.json()["box"], [{
            "image": "same.png",
            "boxes": [{"x1": 10, "y1": 20, "x2": 30, "y2": 40, "label": "A标签"}],
        }])
        self.assertEqual(annotations_a.json()["qa"], [{
            "conversations": [
                {"role": "user", "content": "A项目图片\n<image>"},
                {"role": "assistant", "content": "A项目答案"},
            ],
            "image": "same.png",
        }])
        self.assertEqual(self.client.get("/api/projects").json()[0]["labels"], ["A标签"])

        self.client.post(f"/api/projects/switch/{project_b['id']}")
        annotations_b = self.client.get("/api/annotations")
        self.assertEqual(annotations_b.status_code, 200)
        self.assertEqual(annotations_b.json()["box"], [{
            "image": "same.png",
            "boxes": [{"x1": 1, "y1": 2, "x2": 3, "y2": 4, "label": "B标签"}],
        }])
        self.assertEqual(annotations_b.json()["qa"], [{
            "conversations": [
                {"role": "user", "content": "B项目图片\n<image>"},
                {"role": "assistant", "content": "B项目答案"},
            ],
            "image": "same.png",
        }])
        projects_by_name = {project["name"]: project for project in self.client.get("/api/projects").json()}
        self.assertEqual(projects_by_name["项目A"]["labels"], ["A标签"])
        self.assertEqual(projects_by_name["项目B"]["labels"], ["B标签"])

    def test_switch_and_save_use_active_project_paths(self):
        create_response = self.client.post(
            "/api/projects",
            json={
                "id": "",
                "name": "保存项目",
                "image_dir": "",
                "jsonl_path": "",
                "labels": ["框"],
            },
        )
        self.assertEqual(create_response.status_code, 200)
        project = create_response.json()

        switch_response = self.client.post(f"/api/projects/switch/{project['id']}")
        self.assertEqual(switch_response.status_code, 200)

        save_response = self.client.post(
            "/api/save",
            json={
                "image": "demo.png",
                "user_content": "描述图片",
                "assistant_content": "这是一个测试",
            },
        )
        self.assertEqual(save_response.status_code, 200)

        save_boxes_response = self.client.post(
            "/api/save_boxes",
            json={
                "image": "demo.png",
                "boxes": [{"x1": 1, "y1": 2, "x2": 11, "y2": 12, "label": "框"}],
            },
        )
        self.assertEqual(save_boxes_response.status_code, 200)

        qa_path = self.temp_dir / "projects" / "保存项目" / "标注结果_qa.jsonl"
        boxes_path = self.temp_dir / "projects" / "保存项目" / "标注结果_boxes.jsonl"
        self.assertTrue(qa_path.exists())
        self.assertTrue(boxes_path.exists())

        qa_lines = [json.loads(line) for line in qa_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        box_lines = [json.loads(line) for line in boxes_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(qa_lines[-1]["image"], "demo.png")
        self.assertEqual(box_lines[-1]["boxes"][0]["label"], "框")

    def test_delete_project_removes_record_and_directory(self):
        create_response = self.client.post(
            "/api/projects",
            json={
                "id": "",
                "name": "待删除项目",
                "image_dir": "",
                "jsonl_path": "",
                "labels": ["框"],
            },
        )
        self.assertEqual(create_response.status_code, 200)
        project = create_response.json()
        project_dir = self.temp_dir / "projects" / "待删除项目"
        self.assertTrue(project_dir.exists())

        delete_response = self.client.delete(f"/api/projects/{project['id']}")
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(self.read_projects(), [])
        self.assertFalse(project_dir.exists())

    def test_export_uses_real_annotation_filenames_by_mode(self):
        create_response = self.client.post(
            "/api/projects",
            json={
                "id": "",
                "name": "导出项目",
                "image_dir": "",
                "jsonl_path": "",
                "labels": ["框"],
            },
        )
        self.assertEqual(create_response.status_code, 200)
        project = create_response.json()
        self.client.post(f"/api/projects/switch/{project['id']}")
        self.client.post(
            "/api/projects/current",
            json={
                "last_image": "same.png",
                "labels": ["框"],
                "qa_records": [
                    {
                        "image": "same.png",
                        "user_content": "导出问答",
                        "assistant_content": "问答答案",
                    }
                ],
                "box_records": [
                    {
                        "image": "same.png",
                        "boxes": [
                            {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "label": "框"}
                        ],
                    }
                ],
            },
        )

        qa_export = self.client.get("/api/export-zip?mode=qa")
        self.assertEqual(qa_export.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(qa_export.content)) as zf:
            qa_names = set(zf.namelist())
        self.assertIn("导出项目/标注结果_qa.jsonl", qa_names)
        self.assertNotIn("导出项目/标注结果_boxes.jsonl", qa_names)

        box_export = self.client.get("/api/export-zip?mode=box")
        self.assertEqual(box_export.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(box_export.content)) as zf:
            box_names = set(zf.namelist())
        self.assertIn("导出项目/标注结果_boxes.jsonl", box_names)
        self.assertNotIn("导出项目/标注结果_qa.jsonl", box_names)

    def test_image_template_supports_escape_to_cancel_box_drawing(self):
        template = self.read_image_template()
        self.assertIn("const cancelCurrentDrawing = (deactivateBoxMode = false) => {", template)
        self.assertIn("if (e.key === 'Escape') {", template)
        self.assertIn("cancelCurrentDrawing(true);", template)


if __name__ == "__main__":
    unittest.main()
