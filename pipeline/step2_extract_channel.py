"""
Step 2：提取货主声道。
- 输入：temp1/{shipper_id}/*.wav（双声道）
- 输出：temp2/{shipper_id}/{shipper_id}_001.wav（单声道）
- 同时写 manifest.json 记录短文件名对应的原始文件名
- 通过 soundfile 自动转 PCM 16-bit
- 单声道输入 → 报错入 errors
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .common import (
    StepResult,
    load_manifest,
    parse_filename,
    read_wav_pcm16,
    save_manifest,
    write_wav_pcm16,
)


def run(src: str, dst: str) -> StepResult:
    t0 = time.time()
    result = StepResult(step=2)

    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.exists() or not src_path.is_dir():
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    dst_path.mkdir(parents=True, exist_ok=True)

    files = sorted([f for f in src_path.rglob("*.wav") if f.is_file()])
    result.input_count = len(files)
    counters: dict[str, int] = {}
    manifests: dict[str, dict] = {}

    for f in files:
        meta = parse_filename(f.name)
        if not meta:
            result.skipped += 1
            continue

        try:
            sr, data = read_wav_pcm16(str(f))
        except Exception as e:
            result.fail(f.name, f"读取 WAV 失败: {e}")
            continue

        if data.ndim != 2 or data.shape[1] < 2:
            result.fail(f.name, "单声道输入不支持，需要双声道")
            continue

        ch = 0 if meta.channel == "0" else 1
        mono = data[:, ch].astype(np.int16)

        target_dir = dst_path / meta.shipper_id
        target_dir.mkdir(parents=True, exist_ok=True)
        counters[meta.shipper_id] = counters.get(meta.shipper_id, 0) + 1
        short_name = f"{meta.shipper_id}_{counters[meta.shipper_id]:03d}.wav"
        target_path = target_dir / short_name

        try:
            write_wav_pcm16(str(target_path), sr, mono)
            manifest = manifests.setdefault(meta.shipper_id, load_manifest(target_dir))
            manifest[short_name] = {"source": f.name, "origin": f.name}
            result.output_count += 1
        except Exception as e:
            result.fail(f.name, f"写入失败: {e}")

    for shipper_id, manifest in manifests.items():
        save_manifest(dst_path / shipper_id, manifest)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
