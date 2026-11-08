"""本机正式模式自检：只验证服务与鉴权链路，不发起真实模型调用。"""
from __future__ import annotations

import time

import httpx

BASE = "http://127.0.0.1:8080"
HEADERS = {"X-Forwarded-For": "10.98.98.98"}

for attempt in range(8):
    try:
        httpx.get(BASE + "/api/health", timeout=2)
        break
    except Exception:
        if attempt == 7:
            raise
        time.sleep(0.7)

with httpx.Client(base_url=BASE, timeout=30, headers=HEADERS) as client:
    print("health:", client.get("/api/health").json())
    print("未登录 /api/me:", client.get("/api/me").status_code)
    user = client.post("/api/login", json={"password": "demo1234"})
    print("用户登录:", user.status_code, user.json())
    admin = client.post("/api/login", json={"password": "admin1234"})
    print("后台登录:", admin.status_code, admin.json())
    cfg = client.get("/api/config")
    view = cfg.json()
    print("后台配置: HTTP", cfg.status_code, "| 明文 Key 字段=", "api_key" in view,
          "| 当前模型=", view.get("model"), "| Key 已设置=", view.get("api_key_set"))
    stats = client.get("/api/stats")
    print("调用统计: HTTP", stats.status_code, "| 次数=", stats.json().get("calls"))
    conn = client.post("/api/test-connection")
    print("外网模型端点探测: HTTP", conn.status_code, "|", conn.json().get("detail", ""))
    print("退出:", client.post("/api/logout").status_code,
          "| 退出后 /api/me:", client.get("/api/me").status_code)
