"""
Step 7：按 voice_id 删除音色记录。
"""

from __future__ import annotations

import os
import time

import requests

from .common import StepResult
from .manbang_db import delete_voice_record

_API_BASE = os.environ.get("VUILABS_API_BASE", "https://api.vuilabs.cn")
_TIMEOUT = 30


def run(voice_id: str, api_key: str = "") -> StepResult:
    t0 = time.time()
    result = StepResult(step=7, input_count=1)

    voice_id = voice_id.strip()
    if not voice_id:
        result.fail("voice_id", "未传入 voice_id")
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    if not api_key:
        result.fail("config", "未传入 VUILABS_API_KEY")
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    try:
        resp = requests.delete(
            f"{_API_BASE}/v1/voice/{voice_id}",
            headers={"X-API-Key": api_key},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        result.output_count = 1
    except Exception as e:
        result.fail(voice_id, f"删除音色失败: {e}")
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    try:
        delete_voice_record(voice_id)
    except Exception as e:
        result.fail(voice_id, f"删除本地去重记录失败: {e}")

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
