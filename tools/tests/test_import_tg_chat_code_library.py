import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import import_tg_chat_code_library as importer


class ExtractDescriptionTests(unittest.TestCase):
    def test_prefers_block_comment_over_single_line_section_comment(self) -> None:
        expression = """// 配置邮件发送模式
var emailMode = 'Netease';
/*
Gmail  →  Google邮箱
ProtonMail
QQ  →  QQ邮箱
Netease →  网易邮箱
*/
var fromEmail = "@163.com";
"""
        self.assertEqual(
            importer.extract_description(expression, "邮件发送"),
            "Gmail  →  Google邮箱\nProtonMail\nQQ  →  QQ邮箱\nNetease →  网易邮箱",
        )

    def test_supports_javadoc_style_block_comment(self) -> None:
        expression = """/**
 * 支持文件发送
 * 支持文本发送
 */
var payload = {};
"""
        self.assertEqual(
            importer.extract_description(expression, "邮件发送"),
            "支持文件发送\n支持文本发送",
        )

    def test_falls_back_to_first_valid_single_line_comment(self) -> None:
        expression = """// 来源: https://example.com
// 获取当前位置信息
var result = 1;
"""
        self.assertEqual(
            importer.extract_description(expression, "获取当前位置"),
            "获取当前位置信息",
        )

    def test_skips_low_signal_comments_and_falls_back(self) -> None:
        expression = """var outputPath = "生成的文件路径";
var qrText = "hello";
importClass(java.io.File);
importClass(java.lang.Integer);
importClass(java.lang.Thread);
importClass(java.lang.ClassLoader);
importClass(Packages.android.graphics.Bitmap);
importClass(Packages.android.graphics.Color);
importClass(java.io.FileOutputStream);
importClass(java.util.Map);
importClass(java.util.HashMap);
importClass(Packages.tornaco.apps.shortx.core.OooO0O0);

// ================= 配置路径 =================
var jarPath = "/tmp/test.dex";
// ================= 创建 loader =================
var loader = {};
"""
        self.assertEqual(
            importer.extract_description(expression, "二维码生成"),
            "二维码生成",
        )

    def test_ignores_metadata_only_block_comment(self) -> None:
        expression = """/*
来源: https://example.com
提取自: something
*/
// 真正的说明
var result = 1;
"""
        self.assertEqual(
            importer.extract_description(expression, "示例"),
            "真正的说明",
        )


if __name__ == "__main__":
    unittest.main()
