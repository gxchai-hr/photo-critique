"""本机试用启动脚本：不部署、不改动生产代码。

读取 .env.preview，把模型调用替换成本地演示响应，然后在 127.0.0.1:8080 起服务。
演示模式下：
  标题留空或任意文字 -> 完整的六段式点评
  标题里含「AI」或「生成」 -> 疑似 AI 生成、已降档的点评
  标题里含「截图」或「拒绝」 -> 非摄影作品拒绝页
"""
from __future__ import annotations

import asyncio
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
os.environ.setdefault("DATA_DIR", str(ROOT / ".preview-data"))
Path(os.environ["DATA_DIR"]).mkdir(parents=True, exist_ok=True)

from app import main  # noqa: E402
from app.parsing import validate_result  # noqa: E402

DEMO_WARNING = "演示模式：以下是示例点评，未调用真实大模型。填入自己的 API Key 并关闭本脚本启动，即可获得真实结果。"

BASE = {
    "is_photograph": True,
    "reject_reason": "",
    "subject": "黄昏街头，一个逆光中的背影",
    "first_impression": "逆光把黄昏压得很静，人物肩线与远处车灯构成一条隐约的对角线，有一点布列松式的几何趣味，情绪是克制的孤独。",
    "score": 82,
    "score_breakdown": {"构图": 80, "用光": 86, "色彩": 82, "主题表达": 80,
                        "技术完成度": 82, "标题匹配度": 82},
    "score_reason": "瞬间与用光出色，但背景杂物削弱了主体完整性。",
    "title_analysis": None,
    "highlights": [
        {"point": "侧逆光勾出人物轮廓", "evidence": "肩线被暖光勾出一道亮边，同时外套织物纹理仍可辨认，没有死白。"},
        {"point": "前景压暗形成引导", "evidence": "左下角约三分之一的暗部把视线自然推向画面中央的人物。"},
        {"point": "瞬间捕捉到位", "evidence": "人物抬脚的瞬间与远处车灯亮起同步，静止画面里留住了时间感。"},
    ],
    "problems": [
        {"issue": "背景破坏主体完整性", "evidence": "右上方的电线杆从人物头顶横穿过去，把视线从脸上拉走。"},
        {"issue": "画面右侧失衡", "evidence": "右三分之一是一整片空墙面，没有内容却占了很大权重。"},
        {"issue": "高光局部溢出", "evidence": "天空左上角失去层次，与人物身上的柔和过渡不匹配。"},
    ],
    "suggestions": [
        "降低机位半步，以草地和树冠为背景，避开横穿头顶的电线杆。",
        "向右再走两步或改用稍长焦距，把右侧空墙面压出画外。",
        "后期对天空左上角做局部压暗与高光回收，保留云层层次。",
    ],
    "ai_suspect": False,
    "ai_downgraded": False,
    "ai_evidence": "",
}

AI_RESULT = {
    **BASE,
    "score": 68,
    "score_breakdown": {"构图": 72, "用光": 66, "色彩": 70, "主题表达": 68,
                        "技术完成度": 62, "标题匹配度": 68},
    "score_reason": "疑似生成式填充，已按规则降档；真实性和艺术感染力因此受损。",
    "first_impression": "第一眼像一张黄昏街拍，但人物与环境的衔接过于干净，缺少真实镜头里的偶然性。",
    "ai_suspect": True,
    "ai_downgraded": True,
    "ai_evidence": "左侧人物手指与栏杆交界处边缘过渡生硬；窗内光源方向与地面投影不一致；地砖纹理出现规律性重复。",
    "suggestions": [
        "若为生成图，先统一光源方向再重做投影，避免窗光与地面影子互相矛盾。",
        "检查手指、栏杆、发丝等高频边缘，用实拍素材替换过渡生硬的局部。",
        "打破地砖纹理的规律性重复，保留真实场景里的随机瑕疵。",
    ],
}


async def demo_review(cfg, system_prompt, jpeg, title):
    await asyncio.sleep(2.2)
    text = (title or "").strip()
    lower = text.lower()
    if "截图" in text or "拒绝" in text:
        obj = {"is_photograph": False,
               "reject_reason": "【演示数据】画面主体为聊天界面的文字与按钮，属于屏幕截图，不是相机拍摄的影像。"}
    elif "ai" in lower or "生成" in text:
        obj = dict(AI_RESULT)
        if text:
            obj["title_analysis"] = ["标题与画面气质统一，但没有提供新的观看视角",
                                     "在疑似生成图的前提下，标题的文艺感反而放大了真实性缺口"]
    else:
        obj = dict(BASE)
        if text:
            obj["title_analysis"] = ["简洁克制，与画面的孤独感统一，没有看图说话",
                                     "留白足够，但去掉标题照片依然完整，标题未加深理解"]
    result, warnings = validate_result(obj)
    warnings.append(DEMO_WARNING)
    return result, warnings, {"total_tokens": 0}


main.call_review = demo_review

if __name__ == "__main__":
    import uvicorn

    print("本机试用：http://127.0.0.1:8080  访问口令 demo1234  后台口令 admin1234", flush=True)
    uvicorn.run(main.app, host="127.0.0.1", port=8080, log_level="warning")
