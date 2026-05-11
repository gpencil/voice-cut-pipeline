"""
Step 4：时长过滤。
- 时长 ≥ SEGMENT_MIN_DURATION（2.0s）的片段拷贝到 dst
- < 2s 视为"嗯/哦/好的"，丢弃
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import soundfile as sf

from .common import SEGMENT_MIN_DURATION, StepResult


def get_duration(path: str) -> float:
    info = sf.info(path)
    return info.frames / info.samplerate


def run(src: str, dst: str) -> StepResult:
    t0 = time.time()
    result = StepResult(step=4)

    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.exists() or not src_path.is_dir():
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    dst_path.mkdir(parents=True, exist_ok=True)

    files = sorted([f for f in src_path.rglob("*.wav") if f.is_file()])
    result.input_count = len(files)

    for f in files:
        try:
            dur = get_duration(str(f))
        except Exception as e:
            result.fail(f.name, f"读取时长失败: {e}")
            continue

        if dur < SEGMENT_MIN_DURATION:
            result.skipped += 1
            continue

        shipper_dir = f.parent.name
        target_dir = dst_path / shipper_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(str(f), str(target_dir / f.name))
            result.output_count += 1
        except OSError as e:
            result.fail(f.name, f"拷贝失败: {e}")

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
