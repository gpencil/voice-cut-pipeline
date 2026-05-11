"""
Step 5：ASR 内容过滤。

输入：temp4/{shipper_id}/rank{N}_{短文件名}.wav
输出：temp5/{shipper_id}/rank{N}_{原文件名}.wav  +  同名 .txt

只处理 rank ≤ ASR_TOP_N 的文件（排名由 Step 4 计算好），
其余文件直接跳过（skipped），不调用 ASR。

过滤条件（任一命中则丢弃）：
  - 有效汉字数 < ASR_MIN_CHARS
  - 最高频字符占比 > ASR_MAX_REPEAT_RATIO（如"嗯嗯嗯嗯嗯"）

ASR 调用失败 → 记入 errors，保留文件（避免网络抖动误删好素材）。
"""

from __future__ import annotations

import re
import shutil
import time
import unicodedata
from collections import Counter
from pathlib import Path

import requests

from .common import (
    ASR_BASE_URL,
    ASR_MAX_REPEAT_RATIO,
    ASR_MIN_CHARS,
    ASR_TIMEOUT_S,
    ASR_TOP_N,
    StepResult,
    load_manifest,
    origin_from_manifest,
    save_manifest,
)

_RANK_RE = re.compile(r"^rank(\d+)_")


def _parse_rank(filename: str) -> int:
    """从文件名解析 rank 编号，解析失败返回 1（不跳过）。"""
    m = _RANK_RE.match(filename)
    return int(m.group(1)) if m else 1


def _is_chinese(ch: str) -> bool:
    return unicodedata.category(ch) == "Lo" and "\u4e00" <= ch <= "\u9fff"


def _chinese_chars(text: str) -> str:
    return "".join(ch for ch in text if _is_chinese(ch))


def _call_asr(wav_path: str) -> str:
    with open(wav_path, "rb") as f:
        wav_bytes = f.read()
    resp = requests.post(
        ASR_BASE_URL,
        files={"audio": ("audio.wav", wav_bytes, "audio/wav")},
        timeout=ASR_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json().get("transcript", "")


def _should_filter(transcript: str) -> tuple[bool, str]:
    chars = _chinese_chars(transcript)
    if len(chars) < ASR_MIN_CHARS:
        return True, f"有效汉字不足({len(chars)}<{ASR_MIN_CHARS}): {transcript!r}"
    if chars:
        top_count = Counter(chars).most_common(1)[0][1]
        ratio = top_count / len(chars)
        if ratio > ASR_MAX_REPEAT_RATIO:
            return True, f"重复字符占比过高({ratio:.0%}>{ASR_MAX_REPEAT_RATIO:.0%}): {transcript!r}"
    return False, ""


def run(src: str, dst: str) -> StepResult:
    t0 = time.time()
    result = StepResult(step=5)

    src_p = Path(src)
    dst_p = Path(dst)

    all_files = sorted(src_p.rglob("*.wav"))
    result.input_count = len(all_files)

    for wav in all_files:
        rel = wav.relative_to(src_p)
        rank = _parse_rank(wav.name)

        # 超出 Top-N 限额，跳过（不调用 ASR）
        if rank > ASR_TOP_N:
            result.skipped += 1
            continue

        out_wav = dst_p / rel
        out_txt = out_wav.with_suffix(".txt")
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        src_manifest = load_manifest(wav.parent)
        dst_manifest = load_manifest(out_wav.parent)

        try:
            transcript = _call_asr(str(wav))
        except Exception as e:
            result.fail(str(rel), f"ASR 调用失败: {e}")
            shutil.copy2(wav, out_wav)
            dst_manifest[out_wav.name] = {
                "source": wav.name,
                "origin": origin_from_manifest(src_manifest, wav.name),
            }
            save_manifest(out_wav.parent, dst_manifest)
            result.output_count += 1
            continue

        discard, reason = _should_filter(transcript)
        if discard:
            result.errors.append({"file": str(rel), "reason": f"[rank{rank}] {reason}"})
            result.skipped += 1
            continue

        shutil.copy2(wav, out_wav)
        out_txt.write_text(transcript, encoding="utf-8")
        dst_manifest[out_wav.name] = {
            "source": wav.name,
            "origin": origin_from_manifest(src_manifest, wav.name),
            "transcript": transcript,
        }
        save_manifest(out_wav.parent, dst_manifest)
        result.output_count += 1

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
