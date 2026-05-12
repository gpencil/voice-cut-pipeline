"""
voice-cut-pipeline FastAPI 入口。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipeline import (
    step1_classify,
    step2_extract_channel,
    step3_split,
    step4_quality,
    step5_asr,
    step6_clone,
    step7_delete_voice,
)
from pipeline.common import StepResult
from pipeline.safety import SafetyError, cascade_clear, safe_clear_temp, validate_dst

app = FastAPI(title="voice-cut-pipeline")
app.mount("/static", StaticFiles(directory="static"), name="static")


class RunReq(BaseModel):
    src: str
    dst: str
    work_dir: Optional[str] = None   # 用于级联清理下游 tempN（可选）
    api_key: Optional[str] = None    # Step 6 音色克隆 API 密钥


class DeleteVoiceReq(BaseModel):
    voice_id: str
    api_key: str


@app.get("/")
def index():
    return FileResponse("static/index.html")


def _run_step(step_no: int, runner, req: RunReq):
    t0 = time.time()
    try:
        validate_dst(req.dst, req.src)
    except SafetyError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 源目录不存在/不是目录 → 直接返回，不做任何清理（避免误删）
    src_path = Path(req.src)
    if not src_path.exists() or not src_path.is_dir():
        return JSONResponse(StepResult(step=step_no).to_dict())

    try:
        # 重跑：清空当前 step 输出目录
        safe_clear_temp(req.dst)

        # 级联清空下游 temp（可选）
        if req.work_dir:
            cascade_clear(req.work_dir, from_step=step_no + 1)

        result = runner.run(req.src, req.dst)
    except SafetyError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        result = StepResult(step=step_no)
        result.fail(f"step{step_no}", f"执行失败: {type(e).__name__}: {e}")
        result.elapsed_ms = int((time.time() - t0) * 1000)
    return JSONResponse(result.to_dict())


@app.post("/run/step1")
def run_step1(req: RunReq):
    return _run_step(1, step1_classify, req)


@app.post("/run/step2")
def run_step2(req: RunReq):
    return _run_step(2, step2_extract_channel, req)


@app.post("/run/step3")
def run_step3(req: RunReq):
    return _run_step(3, step3_split, req)


@app.post("/run/step4")
def run_step4(req: RunReq):
    return _run_step(4, step4_quality, req)


@app.post("/run/step5")
def run_step5(req: RunReq):
    return _run_step(5, step5_asr, req)


@app.post("/run/step6")
def run_step6(req: RunReq):
    try:
        validate_dst(req.dst, req.src)
    except SafetyError as e:
        raise HTTPException(status_code=422, detail=str(e))

    src_path = Path(req.src)
    if not src_path.exists() or not src_path.is_dir():
        return JSONResponse(StepResult(step=6).to_dict())

    if req.api_key:
        _delete_existing_step6_voices(Path(req.dst), req.api_key)

    safe_clear_temp(req.dst)

    if req.work_dir:
        try:
            cascade_clear(req.work_dir, from_step=7)
        except SafetyError as e:
            raise HTTPException(status_code=422, detail=str(e))

    result = step6_clone.run(req.src, req.dst, api_key=req.api_key or "")
    return JSONResponse(result.to_dict())


@app.post("/run/step7")
def run_step7(req: DeleteVoiceReq):
    result = step7_delete_voice.run(req.voice_id, api_key=req.api_key)
    return JSONResponse(result.to_dict())


def _delete_existing_step6_voices(temp6_dir: Path, api_key: str):
    """重跑 Step 6 前，删除上一次 report.json 中保留的 Round2 voice_id。"""
    if not temp6_dir.exists():
        return
    for report_path in temp6_dir.rglob("report.json"):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        voice_id = str(report.get("voice_id") or "").strip()
        if voice_id:
            step7_delete_voice.run(voice_id, api_key=api_key)
