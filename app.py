"""
voice-cut-pipeline FastAPI 入口。
"""

from __future__ import annotations

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
    step4_filter,
)
from pipeline.common import StepResult
from pipeline.safety import SafetyError, cascade_clear, safe_clear_temp, validate_dst

app = FastAPI(title="voice-cut-pipeline")
app.mount("/static", StaticFiles(directory="static"), name="static")


class RunReq(BaseModel):
    src: str
    dst: str
    work_dir: Optional[str] = None  # 用于级联清理下游 tempN（可选）


@app.get("/")
def index():
    return FileResponse("static/index.html")


def _run_step(step_no: int, runner, req: RunReq):
    try:
        validate_dst(req.dst, req.src)
    except SafetyError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 源目录不存在/不是目录 → 直接返回，不做任何清理（避免误删）
    src_path = Path(req.src)
    if not src_path.exists() or not src_path.is_dir():
        return JSONResponse(StepResult(step=step_no).to_dict())

    # 重跑：清空当前 step 输出目录
    safe_clear_temp(req.dst)

    # 级联清空下游 temp（可选）
    if req.work_dir:
        try:
            cascade_clear(req.work_dir, from_step=step_no + 1)
        except SafetyError as e:
            raise HTTPException(status_code=422, detail=str(e))

    result = runner.run(req.src, req.dst)
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
    return _run_step(4, step4_filter, req)
