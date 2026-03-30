import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import import_tg_chat_command_library as importer


class ImportTelegramCommandLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        sandbox_root = TOOLS_DIR / "tests" / "_tmp_cmd_import"
        sandbox_root.mkdir(parents=True, exist_ok=True)
        self.root = sandbox_root / f"case_{uuid.uuid4().hex}"
        self.root.mkdir()
        self.export_root = self.root / "export"
        self.repo_root = self.root / "repo"
        self.export_root.mkdir()
        self.repo_root.mkdir()
        (self.repo_root / "da").mkdir()
        (self.repo_root / "rule").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write_share_file(
        self,
        relative_path: str,
        body: dict,
        header: dict,
        *,
        base_root: Path | None = None,
    ) -> Path:
        root = base_root or self.export_root
        file_path = root / Path(relative_path.replace("/", "\\"))
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(body, ensure_ascii=False, indent=2)
            + "\n"
            + importer.SHARE_SEPARATOR
            + "\n"
            + json.dumps(header, ensure_ascii=False),
            encoding="utf-8",
        )
        return file_path

    def write_result(self, messages: list[dict]) -> None:
        payload = {
            "id": 3073722829,
            "messages": messages,
        }
        (self.export_root / "result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def attachment_message(self, message_id: int, relative_path: str, file_name: str | None = None) -> dict:
        return {
            "id": message_id,
            "file": relative_path,
            "file_name": file_name or Path(relative_path).name,
        }

    def test_collect_candidates_classifies_da_and_rule_and_skips_others(self) -> None:
        self.write_share_file(
            "chats/topic/files/Direct.txt",
            {"id": "da-1", "title": "直达", "actions": []},
            {"type": "da"},
        )
        self.write_share_file(
            "chats/topic/files/Rule.txt",
            {"id": "rule-1", "title": "自动规则", "facts": [], "conditions": [], "actions": []},
            {"type": "rule"},
        )
        self.write_share_file(
            "chats/topic/files/Code.txt",
            {"id": "code-1", "name": "代码库", "type": "CodeType_JAVASCRIPT"},
            {"type": "CodeLibraryItem"},
        )
        self.write_share_file(
            "chats/topic/files/Unknown.txt",
            {"id": "unknown-1", "title": "未知", "actions": []},
            {"type": "mystery"},
        )
        self.write_result(
            [
                self.attachment_message(1, "chats/topic/files/Direct.txt"),
                self.attachment_message(2, "chats/topic/files/Rule.txt"),
                self.attachment_message(3, "chats/topic/files/Code.txt"),
                self.attachment_message(4, "chats/topic/files/Unknown.txt"),
            ]
        )

        data = importer.load_export(self.export_root)
        candidates, stats = importer.collect_attachment_candidates(self.export_root, data["messages"])

        self.assertEqual(2, len(candidates))
        self.assertEqual(["da", "rule"], [candidate.share_type for candidate in candidates])
        self.assertEqual(4, stats["attachments_seen"])
        self.assertEqual(1, stats["skipped_code_libraries"])
        self.assertEqual(1, stats["skipped_unknown_type"])

    def test_plan_projects_reuses_existing_archive_dir_and_keeps_latest_root(self) -> None:
        existing_body = {
            "id": "SHARED-DA-monitor",
            "title": "设置项监视器 4.4",
            "description": "4.4版本\n旧版本",
            "actions": [],
            "versionCode": "8",
            "lastUpdateTime": "100",
        }
        latest_body = {
            "id": "SHARED-DA-monitor",
            "title": "设置项监视器 4.6",
            "description": "4.6版本\n新版本",
            "actions": [],
            "versionCode": "9",
            "lastUpdateTime": "200",
        }
        self.write_share_file("da/ShortX-设置项监视器_4.6.txt", latest_body, {"type": "da"}, base_root=self.repo_root)
        self.write_share_file(
            "da/设置项监视器/ShortX-设置项监视器_4.4.txt",
            existing_body,
            {"type": "da"},
            base_root=self.repo_root,
        )
        self.write_share_file(
            "chats/topic/files/ShortX-设置项监视器_4.6.txt",
            latest_body,
            {"type": "da"},
        )
        self.write_result([self.attachment_message(1, "chats/topic/files/ShortX-设置项监视器_4.6.txt")])

        data = importer.load_export(self.export_root)
        candidates, _ = importer.collect_attachment_candidates(self.export_root, data["messages"])
        projects, summary = importer.plan_projects(self.repo_root, candidates)

        self.assertEqual(1, summary["planned_projects"])
        self.assertEqual("设置项监视器", projects[0].archive_dir_name)
        self.assertEqual(self.repo_root / "da" / "ShortX-设置项监视器_4.6.txt", projects[0].latest_root_path)
        self.assertEqual(
            {
                self.repo_root / "da" / "设置项监视器" / "ShortX-设置项监视器_4.4.txt",
                self.repo_root / "da" / "设置项监视器" / "ShortX-设置项监视器_4.6.txt",
            },
            {path for path, _ in projects[0].archive_items},
        )

    def test_plan_projects_splits_same_name_versions_by_description_version(self) -> None:
        body_v1 = {
            "id": "SHARED-DA-find",
            "title": "屏幕文本查找直达",
            "description": "1.0版本\n旧版本",
            "actions": [],
            "versionCode": "1",
            "lastUpdateTime": "100",
        }
        body_v2 = {
            "id": "SHARED-DA-find",
            "title": "屏幕文本查找直达",
            "description": "1.3.5版本\n新版本",
            "actions": [],
            "versionCode": "5",
            "lastUpdateTime": "200",
        }
        self.write_share_file("chats/topic/files/FindA.txt", body_v1, {"type": "da"})
        self.write_share_file("chats/topic/files/FindB.txt", body_v2, {"type": "da"})
        self.write_result(
            [
                self.attachment_message(10, "chats/topic/files/FindA.txt", file_name="ShortX-屏幕文本查找直达.txt"),
                self.attachment_message(11, "chats/topic/files/FindB.txt", file_name="ShortX-屏幕文本查找直达.txt"),
            ]
        )

        data = importer.load_export(self.export_root)
        candidates, _ = importer.collect_attachment_candidates(self.export_root, data["messages"])
        projects, _ = importer.plan_projects(self.repo_root, candidates)
        archive_paths = {path.name for path, _ in projects[0].archive_items}

        self.assertEqual(self.repo_root / "da" / "ShortX-屏幕文本查找直达.txt", projects[0].latest_root_path)
        self.assertIn("ShortX-屏幕文本查找直达_1.0.txt", archive_paths)
        self.assertIn("ShortX-屏幕文本查找直达_1.3.5.txt", archive_paths)

    def test_plan_projects_preserves_multilingual_variants_inside_archive(self) -> None:
        old_body = {
            "id": "SHARED-DA-shortcuts",
            "title": "Shortcuts(快捷方式",
            "description": "4.0版本\n旧版本",
            "actions": [],
            "versionCode": "4",
            "lastUpdateTime": "100",
        }
        en_body = {
            "id": "SHARED-DA-shortcuts",
            "title": "Shortcuts Tool",
            "description": "Version 4.2\nEnglish",
            "actions": [],
            "versionCode": "5",
            "lastUpdateTime": "200",
        }
        zh_body = {
            "id": "SHARED-DA-shortcuts",
            "title": "Shortcuts(快捷方式",
            "description": "4.2版本\n中文",
            "actions": [],
            "versionCode": "5",
            "lastUpdateTime": "300",
        }
        self.write_share_file("da/ShortX-Shortcuts_快捷方式.txt", old_body, {"type": "da"}, base_root=self.repo_root)
        self.write_share_file("chats/topic/files/En.txt", en_body, {"type": "da"})
        self.write_share_file("chats/topic/files/Zh.txt", zh_body, {"type": "da"})
        self.write_result(
            [
                self.attachment_message(20, "chats/topic/files/En.txt", file_name="ShortX-Shortcuts Tool.txt"),
                self.attachment_message(21, "chats/topic/files/Zh.txt", file_name="ShortX-Shortcuts(快捷方式.txt"),
            ]
        )

        data = importer.load_export(self.export_root)
        candidates, _ = importer.collect_attachment_candidates(self.export_root, data["messages"])
        projects, _ = importer.plan_projects(self.repo_root, candidates)

        self.assertEqual(self.repo_root / "da" / "ShortX-Shortcuts(快捷方式.txt", projects[0].latest_root_path)
        archive_paths = {path.name for path, _ in projects[0].archive_items}
        self.assertIn("ShortX-Shortcuts_快捷方式.txt", archive_paths)
        self.assertIn("ShortX-Shortcuts Tool.txt", archive_paths)
        self.assertIn("ShortX-Shortcuts(快捷方式.txt", archive_paths)

    def test_plan_projects_prefers_chinese_root_and_archive_dir_for_same_id(self) -> None:
        en_body = {
            "id": "SHARED-DA-policy",
            "title": "PolicyManager",
            "description": "Version 1.5\nEnglish",
            "actions": [],
            "versionCode": "1",
            "lastUpdateTime": "200",
        }
        zh_body = {
            "id": "SHARED-DA-policy",
            "title": "Android组策略管理器",
            "description": "1.5版本\n中文",
            "actions": [],
            "versionCode": "1",
            "lastUpdateTime": "100",
        }
        self.write_share_file("da/PolicyManager/ShortX-PolicyManager.txt", en_body, {"type": "da"}, base_root=self.repo_root)
        self.write_share_file("da/ShortX-PolicyManager.txt", en_body, {"type": "da"}, base_root=self.repo_root)
        self.write_share_file("chats/topic/files/Zh.txt", zh_body, {"type": "da"})
        self.write_result([self.attachment_message(40, "chats/topic/files/Zh.txt", file_name="ShortX-Android组策略管理器.txt")])

        data = importer.load_export(self.export_root)
        candidates, _ = importer.collect_attachment_candidates(self.export_root, data["messages"])
        projects, _ = importer.plan_projects(self.repo_root, candidates)

        self.assertEqual("Android组策略管理器", projects[0].archive_dir_name)
        self.assertEqual(self.repo_root / "da" / "ShortX-Android组策略管理器.txt", projects[0].latest_root_path)
        archive_paths = {path.name for path, _ in projects[0].archive_items}
        self.assertIn("ShortX-PolicyManager.txt", archive_paths)
        self.assertIn("ShortX-Android组策略管理器.txt", archive_paths)

    def test_execute_plans_removes_obsolete_root_files_and_writes_archive(self) -> None:
        older_body = {
            "id": "SHARED-DA-area",
            "title": "选择屏幕区域",
            "description": "1.0版本\n旧版本",
            "actions": [],
            "versionCode": "2",
            "lastUpdateTime": "100",
        }
        newer_body = {
            "id": "SHARED-DA-area",
            "title": "选择屏幕区域",
            "description": "2.8版本\n新版本",
            "actions": [],
            "versionCode": "6",
            "lastUpdateTime": "300",
        }
        old_root = self.write_share_file("da/ShortX-选择屏幕区域_m1746.txt", older_body, {"type": "da"}, base_root=self.repo_root)
        self.write_share_file("chats/topic/files/A.txt", older_body, {"type": "da"})
        self.write_share_file("chats/topic/files/B.txt", newer_body, {"type": "da"})
        self.write_result(
            [
                self.attachment_message(30, "chats/topic/files/A.txt", file_name="ShortX-选择屏幕区域.txt"),
                self.attachment_message(31, "chats/topic/files/B.txt", file_name="ShortX-选择屏幕区域.txt"),
            ]
        )

        data = importer.load_export(self.export_root)
        candidates, stats = importer.collect_attachment_candidates(self.export_root, data["messages"])
        projects, plan_stats = importer.plan_projects(self.repo_root, candidates)
        write_stats = importer.execute_plans(projects)
        summary = importer.summarize_plan(projects, stats, plan_stats)

        self.assertEqual(1, summary["planned_projects"])
        self.assertFalse(old_root.exists())
        self.assertTrue((self.repo_root / "da" / "ShortX-选择屏幕区域.txt").exists())
        self.assertTrue((self.repo_root / "da" / "选择屏幕区域" / "ShortX-选择屏幕区域_1.0.txt").exists())
        self.assertTrue((self.repo_root / "da" / "选择屏幕区域" / "ShortX-选择屏幕区域_2.8.txt").exists())
        self.assertGreaterEqual(write_stats["written_files"], 3)
        self.assertEqual(1, write_stats["deleted_paths"])


if __name__ == "__main__":
    unittest.main()
