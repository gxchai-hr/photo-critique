"""本机正式模式启动脚本：不替换模型调用，走真实 API。

与 NAS 部署加载的是同一个 app.main:app，只是跑在本机、不进 Docker。
口令沿用 .env.preview，配置存 .local-data/config.json（与演示数据隔离）。
启动后请到 /admin 填 Base URL / API Key / 模型名，点「测试连接」后再点评。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env.preview"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
os.environ.setdefault("ACCESS_PASSWORD", "demo1234")
os.environ.setdefault("ADMIN_PASSWORD", "admin1234")
os.environ.setdefault("DATA_DIR", str(ROOT / ".local-data"))
Path(os.environ["DATA_DIR"]).mkdir(parents=True, exist_ok=True)

from app import main  # noqa: E402

if __name__ == "__main__":
    import uvicorn

    print("本机正式模式：http://127.0.0.1:8080 | 访问 demo1234 | 后台 admin1234", flush=True)
    print("先到 /admin 填 Base URL / API Key / 模型名，测试连接通过后再上传照片", flush=True)
    uvicorn.run(main.app, host="127.0.0.1", port=8080, log_level="info")
