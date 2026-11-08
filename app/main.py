"""FastAPI 入口：静态页 + 评审接口 + 后台配置。"""
from __future__ import annotations

import hmac
import os
import re
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, imaging
from .llm import ModelError, call_review, test_connection
from .prompt import SYSTEM_PROMPT

STATIC = Path(__file__).parent / "static"
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
SESSION_TTL = 24 * 3600

if not ACCESS_PASSWORD or not ADMIN_PASSWORD:
    raise RuntimeError(
        "必须设置 ACCESS_PASSWORD 与 ADMIN_PASSWORD 环境变量（见 .env.example）。"
        "拒绝以空口令启动公网服务。"
    )

app = FastAPI(title="你拍我评", docs_url=None, redoc_url=None, openapi_url=None)

_LOCK = threading.Lock()
_SESSIONS: dict[str, dict] = {}
_LOGIN_FAILURES: dict[str, tuple[int, float]] = {}
_REVIEW_HITS: dict[str, deque] = {}
_STATS = {"calls": 0, "success": 0, "rejected": 0, "failed": 0, "total_ms": 0, "total_tokens": 0}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.url.path.startswith("/api/") and (request.headers.get("origin") or ""):
        origin = request.headers["origin"].split("://", 1)[-1].split("/", 1)[0]
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        if host and origin != host:
            return JSONResponse({"detail": "请求来源不被允许"}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown"))


def _role(request: Request) -> str | None:
    token = request.cookies.get("pc_session", "")
    if not token:
        return None
    with _LOCK:
        session = _SESSIONS.get(token)
        if not session or session["expire"] < time.time():
            _SESSIONS.pop(token, None)
            return None
        return session["role"]


def require_user(request: Request) -> str:
    role = _role(request)
    if not role:
        raise HTTPException(401, "请先输入访问口令")
    return role


def require_admin(request: Request) -> str:
    if _role(request) != "admin":
        raise HTTPException(403, "需要后台管理口令")
    return "admin"


def _rate_limit(ip: str) -> None:
    now = time.time()
    with _LOCK:
        hits = _REVIEW_HITS.setdefault(ip, deque())
        while hits and hits[0] < now - 86400:
            hits.popleft()
        recent = [t for t in hits if t > now - 60]
        if len(recent) >= 3:
            raise HTTPException(429, "点评太频繁，请稍等一分钟")
        if len(hits) >= 50:
            raise HTTPException(429, "今日调用次数已用完")
        hits.append(now)


def _bump(key: str, **extra) -> None:
    with _LOCK:
        _STATS[key] = _STATS.get(key, 0) + 1
        for name, value in extra.items():
            _STATS[name] = _STATS.get(name, 0) + value


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/login")
async def login(request: Request, payload: dict):
    ip = _client_ip(request)
    with _LOCK:
        count, until = _LOGIN_FAILURES.get(ip, (0, 0.0))
        if until > time.time():
            raise HTTPException(429, "口令错误次数过多，请 10 分钟后再试")
    password = str(payload.get("password", "")) if isinstance(payload, dict) else ""
    role = None
    if hmac.compare_digest(password, ADMIN_PASSWORD):
        role = "admin"
    elif hmac.compare_digest(password, ACCESS_PASSWORD):
        role = "user"
    if not role:
        with _LOCK:
            count += 1
            _LOGIN_FAILURES[ip] = (count, time.time() + 600 if count >= 5 else 0.0)
        raise HTTPException(401, "口令不正确")
    with _LOCK:
        _LOGIN_FAILURES.pop(ip, None)
        token = secrets.token_urlsafe(32)
        _SESSIONS[token] = {"role": role, "expire": time.time() + SESSION_TTL}
    response = JSONResponse({"ok": True, "role": role})
    response.set_cookie(
        "pc_session", token, max_age=SESSION_TTL,
        httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/",
    )
    return response


@app.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get("pc_session", "")
    with _LOCK:
        _SESSIONS.pop(token, None)
    response = JSONResponse({"ok": True})
    response.delete_cookie("pc_session", path="/")
    return response


@app.get("/api/me")
async def me(request: Request):
    role = _role(request)
    if not role:
        raise HTTPException(401, "未登录")
    return {"role": role}


@app.get("/api/config")
async def get_public_config(request: Request):
    require_admin(request)
    view = config.public_config()
    view["default_system_prompt"] = SYSTEM_PROMPT
    view["system_prompt"] = view["system_prompt"] or SYSTEM_PROMPT
    return view


@app.post("/api/config")
async def save_public_config(request: Request, payload: dict):
    require_admin(request)
    try:
        config.save_config(payload, SYSTEM_PROMPT)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    view = config.public_config()
    view["default_system_prompt"] = SYSTEM_PROMPT
    view["system_prompt"] = view["system_prompt"] or SYSTEM_PROMPT
    return view


@app.get("/api/stats")
async def stats(request: Request):
    require_admin(request)
    with _LOCK:
        snapshot = dict(_STATS)
    avg = round(snapshot["total_ms"] / max(1, snapshot["success"] + snapshot["rejected"]))
    return {**snapshot, "avg_ms": avg, "note": "仅统计本次容器运行期间，重启清零"}


@app.post("/api/test-connection")
async def test_conn(request: Request):
    require_admin(request)
    cfg = config.get_config()
    if not config.is_ready(cfg):
        raise HTTPException(400, "请先填写 Base URL、模型名称与 API Key")
    try:
        return await test_connection(cfg, imaging.tiny_test_image())
    except ModelError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@app.post("/api/review")
async def review(request: Request, image: UploadFile = File(...), title: str = Form("")):
    role = require_user(request)
    _rate_limit(_client_ip(request))
    cfg = config.get_config()
    if not config.is_ready(cfg):
        raise HTTPException(400, "尚未完成模型配置，请联系管理员到后台填写 API Key")

    raw = await image.read(imaging.MAX_UPLOAD + 1)
    try:
        jpeg, info = imaging.prepare(raw, image.content_type or "")
    except imaging.ImageError as exc:
        raise HTTPException(400, str(exc)) from exc

    system_prompt = cfg.get("system_prompt") or SYSTEM_PROMPT
    started = time.monotonic()
    _bump("calls")
    try:
        result, warnings, usage = await call_review(cfg, system_prompt, jpeg, title[:60])
    except ModelError as exc:
        _bump("failed")
        raise HTTPException(exc.status, str(exc)) from exc
    elapsed_ms = round((time.monotonic() - started) * 1000)
    _bump("rejected" if not result["is_photograph"] else "success", total_ms=elapsed_ms,
          total_tokens=int(usage.get("total_tokens") or 0))
    # 图片与结果都不写磁盘，函数返回后即被释放。
    return {"result": result, "warnings": warnings, "image": info, "elapsed_ms": elapsed_ms, "role": role}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/admin")
async def admin_page():
    return FileResponse(STATIC / "admin.html", headers={"Cache-Control": "no-cache"})


@app.get("/{verify_name}")
async def root_verification_file(verify_name: str):
    """站点归属校验文件（微信/搜索引擎），必须免认证、无跳转。

    以后再需要校验，只要往 app/static/ 放一个 <名字>.txt 即可，无需改代码。
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.txt", verify_name):
        raise HTTPException(404)
    path = STATIC / verify_name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="text/plain",
                        headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
