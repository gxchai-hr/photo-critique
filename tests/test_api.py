"""端到端冒烟测试：用 TestClient 跑真实 HTTP 链路，模型调用用桩替代。

需要 fastapi / httpx / python-multipart / Pillow；缺失时自动跳过。
"""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("ACCESS_PASSWORD", "test-access")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin")
os.environ.setdefault("DATA_DIR", os.path.join(tempfile.gettempdir(), "pc-smoke-data"))

try:
    from fastapi.testclient import TestClient

    from app import config, main
    from app.parsing import validate_result
    from tests.test_core import sample_result

    AVAILABLE = True
except ImportError:
    AVAILABLE = False


async def fake_review(cfg, system_prompt, jpeg, title):
    result, _ = validate_result(sample_result())
    return result, [], {"total_tokens": 123}


async def fake_reject(cfg, system_prompt, jpeg, title):
    result, _ = validate_result({"is_photograph": False, "reject_reason": "这是一张聊天截图"})
    return result, [], {"total_tokens": 20}


def jpeg_bytes():
    from PIL import Image

    img = Image.new("RGB", (640, 480), (90, 120, 150))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@unittest.skipUnless(AVAILABLE, "缺少 fastapi / httpx / multipart / Pillow")
class TestApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config.DATA_DIR = Path(self.tmp.name)
        config.CONFIG_PATH = config.DATA_DIR / "config.json"
        # 模型调用已被桩替换，但 is_ready 仍要求已填 Key
        config.CONFIG_PATH.write_text('{"api_key": "test-key"}', encoding="utf-8")
        with main._LOCK:
            main._SESSIONS.clear()
            main._LOGIN_FAILURES.clear()
            main._REVIEW_HITS.clear()
            for key in main._STATS:
                main._STATS[key] = 0
        self.original_review = main.call_review
        self.client = TestClient(main.app)

    def tearDown(self):
        main.call_review = self.original_review
        self.client.close()
        self.tmp.cleanup()

    def _login(self, password="test-access"):
        return self.client.post("/api/login", json={"password": password})

    def test_health_and_pages(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        self.assertIn("你拍我评", self.client.get("/").text)
        self.assertIn("后台配置", self.client.get("/admin").text)

    def test_login_and_roles(self):
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"password": "wrong"}).status_code, 401)
        resp = self._login()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["role"], "user")
        self.assertEqual(self.client.get("/api/me").json()["role"], "user")
        self.assertEqual(self.client.get("/api/config").status_code, 403)

    def test_admin_config_never_leaks_key(self):
        self.assertEqual(self._login("test-admin").json()["role"], "admin")
        cfg = self.client.get("/api/config").json()
        self.assertNotIn("api_key", cfg)
        self.assertIn("default_system_prompt", cfg)
        saved = self.client.post("/api/config", json={
            "provider": "custom", "base_url": "https://example.com/v1",
            "model": "vision-test", "api_key": "sk-abcdefgh1234",
            "system_prompt": cfg["default_system_prompt"],
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["api_key_masked"], "sk-****1234")
        self.assertNotIn("sk-abcdefgh1234", saved.text)
        self.assertEqual(config.get_config()["api_key"], "sk-abcdefgh1234")

    def test_review_requires_model_config(self):
        config.save_config({"base_url": "", "model": ""})
        self._login()
        resp = self.client.post("/api/review", files={"image": ("p.jpg", jpeg_bytes(), "image/jpeg")})
        self.assertEqual(resp.status_code, 400)

    def test_review_success_path(self):
        config.save_config({"base_url": "https://example.com/v1", "model": "vision-test"})
        main.call_review = fake_review
        self._login()
        resp = self.client.post(
            "/api/review",
            files={"image": ("p.jpg", jpeg_bytes(), "image/jpeg")},
            data={"title": "黄昏"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["result"]["score"], 82)
        self.assertEqual(len(body["result"]["highlights"]), 3)
        self.assertEqual(body["image"]["original_width"], 640)
        self.assertTrue(body["image"]["bytes"] > 0)

    def test_review_rejection_path(self):
        config.save_config({"base_url": "https://example.com/v1", "model": "vision-test"})
        main.call_review = fake_reject
        self._login()
        body = self.client.post(
            "/api/review", files={"image": ("p.jpg", jpeg_bytes(), "image/jpeg")}
        ).json()
        self.assertFalse(body["result"]["is_photograph"])
        self.assertNotIn("score", body["result"])

    def test_bad_image_is_rejected_locally(self):
        config.save_config({"base_url": "https://example.com/v1", "model": "vision-test"})
        self._login()
        resp = self.client.post("/api/review", files={"image": ("p.jpg", b"not an image", "image/jpeg")})
        self.assertEqual(resp.status_code, 400)

    def test_rate_limit(self):
        config.save_config({"base_url": "https://example.com/v1", "model": "vision-test"})
        main.call_review = fake_review
        self._login()
        for _ in range(3):
            ok = self.client.post("/api/review", files={"image": ("p.jpg", jpeg_bytes(), "image/jpeg")})
            self.assertEqual(ok.status_code, 200)
        limited = self.client.post("/api/review", files={"image": ("p.jpg", jpeg_bytes(), "image/jpeg")})
        self.assertEqual(limited.status_code, 429)

    def test_origin_and_logout(self):
        resp = self.client.post("/api/login", json={"password": "test-access"},
                                headers={"Origin": "https://evil.example.com"})
        self.assertEqual(resp.status_code, 403)
        self._login()
        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/me").status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
