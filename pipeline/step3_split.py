"""
Step 3：按气口切分成多段，同时过滤短片段。
- 长停顿（>0.3s）作为切分点
- 每段首尾保留 0.05s padding
- 时长 < SEGMENT_MIN_DURATION 的段直接丢弃（无需写到磁盘再过滤）
- 输出：temp3/{shipper_id}/{货主id}_{源序号}_{切段序号}.wav
- 同时写 manifest.json 延续原始文件名追踪
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .common import (
    BREATH_MIN_DURATION,
    SEGMENT_MIN_DURATION,
    SEGMENT_PADDING,
    SILENCE_THRESHOLD,
    StepResult,
    load_manifest,
    origin_from_manifest,
    read_wav_pcm16,
    save_manifest,
    write_wav_pcm16,
)


def find_speech_segments(audio: np.ndarray, samplerate: int) -> list[tuple[int, int]]:
    """
    找出所有"非长停顿"区间。返回 [(start, end), ...] 半开区间。
    长停顿定义：连续 >= BREATH_MIN_DURATION 秒的低振幅区间。
    """
    min_silence = int(BREATH_MIN_DURATION * samplerate)
    is_silent = (np.abs(audio) < SILENCE_THRESHOLD).astype(np.int8)

    diff = np.diff(is_silent, prepend=0, append=0)
    silence_starts = np.where(diff == 1)[0]
    silence_ends = np.where(diff == -1)[0]

    long_silences = [
        (s, e) for s, e in zip(silence_starts, silence_ends)
        if (e - s) >= min_silence
    ]

    if not long_silences:
        return [(0, len(audio))]

    segments = []
    prev_end = 0
    for s_start, s_end in long_silences:
        if prev_end < s_start:
            segments.append((prev_end, s_start))
        prev_end = s_end
    if prev_end < len(audio):
        segments.append((prev_end, len(audio)))

    return segments


def run(src: str, dst: str) -> StepResult:
    t0 = time.time()
    result = StepResult(step=3)

    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.exists() or not src_path.is_dir():
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    dst_path.mkdir(parents=True, exist_ok=True)

    files = sorted([f for f in src_path.rglob("*.wav") if f.is_file()])
    result.input_count = len(files)
    src_manifests: dict[Path, dict] = {}
    dst_manifests: dict[str, dict] = {}

    for f in files:
        try:
            sr, data = read_wav_pcm16(str(f))
        except Exception as e:
            result.fail(f.name, f"读取 WAV 失败: {e}")
            continue

        if data.ndim != 1:
            # Step 3 输入应该是单声道，多声道默认取第一声道
            data = data[:, 0]

        segments = find_speech_segments(data, sr)
        if not segments:
            continue

        padding = int(SEGMENT_PADDING * sr)
        shipper_dir = f.parent.name
        target_dir = dst_path / shipper_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        src_manifest = src_manifests.setdefault(f.parent, load_manifest(f.parent))
        dst_manifest = dst_manifests.setdefault(shipper_dir, load_manifest(target_dir))
        origin = origin_from_manifest(src_manifest, f.name)

        stem = f.stem
        min_samples = int(SEGMENT_MIN_DURATION * sr)
        out_idx = 1
        kept = 0
        for s, e in segments:
            ps = max(0, s - padding)
            pe = min(len(data), e + padding)
            if (pe - ps) < min_samples:   # 用加了 padding 的实际输出长度判断
                result.skipped += 1
                continue
            kept += 1
            seg_audio = data[ps:pe].astype(np.int16)
            out_path = target_dir / f"{stem}_{out_idx:03d}.wav"
            try:
                write_wav_pcm16(str(out_path), sr, seg_audio)
                dst_manifest[out_path.name] = {"source": f.name, "origin": origin}
                result.output_count += 1
                out_idx += 1
            except Exception as ex:
                result.fail(f"{f.name}#{out_idx}", f"写入失败: {ex}")

        if kept == 0:
            total_s = round(len(data) / sr, 1)
            longest_s = round(max(e - s for s, e in segments) / sr, 1) if segments else 0
            result.fail(f.name, f"所有切段均短于 {SEGMENT_MIN_DURATION}s 被丢弃（音频总长 {total_s}s，最长段 {longest_s}s）")

    for shipper_id, manifest in dst_manifests.items():
        save_manifest(dst_path / shipper_id, manifest)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
