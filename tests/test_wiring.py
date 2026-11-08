"""前后端接线检查：不需要启动服务，防止 DOM id 和接口路径写错。"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestWiring(unittest.TestCase):
    def test_static_assets_exist(self):
        for name in ("index.html", "admin.html", "app.js", "admin.js", "style.css"):
            self.assertTrue((STATIC / name).is_file(), f"缺少前端文件 {name}")

    def test_dom_ids_used_by_app_js_exist(self):
        html = read(STATIC / "index.html")
        ids = set(re.findall(r'id="([^"]+)"', html))
        used = set(re.findall(r"\$\('([^']+)'\)", read(STATIC / "app.js")))
        # renderResult 动态插入的两个按钮在结果 HTML 里生成
        dynamic = {"copyBtn", "againBtn"}
        missing = used - ids - dynamic
        self.assertEqual(missing, set(), f"app.js 引用了不存在的元素：{missing}")

    def test_dom_ids_used_by_admin_js_exist(self):
        html = read(STATIC / "admin.html")
        ids = set(re.findall(r'id="([^"]+)"', html))
        used = set(re.findall(r"\$\('([^']+)'\)", read(STATIC / "admin.js")))
        missing = used - ids
        self.assertEqual(missing, set(), f"admin.js 引用了不存在的元素：{missing}")

    def test_api_paths_are_registered(self):
        backend = read(ROOT / "app" / "main.py")
        registered = set(re.findall(r'@app\.(?:get|post)\("([^"]+)"', backend))
        frontend = read(STATIC / "app.js") + read(STATIC / "admin.js")
        called = set(re.findall(r"api\('(/api/[^']+)'", frontend))
        missing = called - registered
        self.assertEqual(missing, set(), f"前端调用了不存在的接口：{missing}")

    def test_dockerfile_references_existing_files(self):
        dockerfile = read(ROOT / "Dockerfile")
        self.assertIn("COPY app /app/app", dockerfile)
        self.assertIn("requirements.txt", dockerfile)
        self.assertTrue((ROOT / "requirements.txt").is_file())

    def test_env_example_documents_both_passwords(self):
        env = read(ROOT / ".env.example")
        self.assertIn("ACCESS_PASSWORD", env)
        self.assertIn("ADMIN_PASSWORD", env)
        self.assertIn("COOKIE_SECURE", env)


if __name__ == "__main__":
    unittest.main(verbosity=2)
