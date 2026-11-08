"""本机预览自检：登录并跑通三种演示结果，不消耗真实模型额度。"""
from __future__ import annotations

import io
import time

import httpx
from PIL import Image

BASE = "http://127.0.0.1:8080"
HEADERS = {"X-Forwarded-For": "10.99.99.99"}

img = Image.new("RGB", (800, 600), (110, 130, 150))
buf = io.BytesIO()
img.save(buf, format="JPEG")
JPEG = buf.getvalue()

for attempt in range(8):
    try:
        httpx.get(BASE + "/api/health", timeout=2)
        break
    except Exception:
        if attempt == 7:
            raise
        time.sleep(0.7)

with httpx.Client(base_url=BASE, timeout=40, headers=HEADERS) as client:
    print("health:", client.get("/api/health").json())
    login = client.post("/api/login", json={"password": "demo1234"})
    print("login:", login.status_code, login.json())
    for label, title in [("完整点评", "归途"), ("AI 降档", "AI 生成测试"), ("非摄影拒绝", "截图测试")]:
        resp = client.post(
            "/api/review",
            files={"image": ("demo.jpg", JPEG, "image/jpeg")},
            data={"title": title},
        )
        body = resp.json()
        r = body.get("result", {})
        print(f"{label}: HTTP {resp.status_code} | 摄影={r.get('is_photograph')} | "
              f"评分={r.get('score')} | AI={r.get('ai_suspect')} | "
              f"亮点={len(r.get('highlights', []))} | 问题={len(r.get('problems', []))} | "
              f"提示={len(body.get('warnings', []))}")
    admin = client.post("/api/login", json={"password": "admin1234"})
    print("admin login:", admin.status_code, admin.json())
