"""
Step 6：两轮音色克隆 + 评估。

输入：temp5/{shipper_id}/rank1_*.wav + 同名 .txt
输出：temp6/{shipper_id}/r1_gen{1,2}.wav   ← Round 1 生成（评分选优）
      temp6/{shipper_id}/r2_gen{1,2}.wav   ← Round 2 生成（人工评估）
      temp6/{shipper_id}/report.json       ← 评分详情 + 最终 voice_id
      temp6/oss_manifest.json              ← 本次上传的所有 OSS key（用于后续清理）

两轮克隆流程（每个货主）：
  Round 1：
    ① 上传 rank1_.wav → OSS → object_key
    ② POST /v1/voice/save（voice_id=manbang_{ts}_r1, ref_text=.txt内容）
    ③ 生成句子 A、B 各一段 → r1_gen1.wav / r1_gen2.wav
    ④ 评分 → 取流畅度较高的那段（best_audio）
    ⑤ 上传 best_audio → OSS → object_key_2
    ⑥ DELETE manbang_{ts}_r1（释放额度）
  Round 2：
    ⑦ POST /v1/voice/save（voice_id=manbang_{ts}, ref_audio=key_2, ref_text=对应生成句）
    ⑧ 生成句子 A、B 各一段 → r2_gen1.wav / r2_gen2.wav
    ⑨ 写 report.json

环境变量：
  VUILABS_API_KEY      必填，调 api.vuilabs.cn 的密钥
  AliyunAccessKeyID    OSS AK（与 api-gateway 相同）
  AliyunAccessKeySecret
  OSS_ENDPOINT         可选，默认 oss-cn-hangzhou.aliyuncs.com
  OSS_BUCKET           可选，默认 lunalab-res
"""

from __future__ import annotations

import io
import json
import os
import time
import uuid
from pathlib import Path

import numpy as np
import oss2
import requests
import soundfile as sf

from .common import StepResult
from .step4_quality import (
    _estimate_snr,
    _fluency_score,
    _frame_rms,
    _speech_burst_stats,
    _vol_consistency_score,
)
from .manbang_db import upsert_voice_id

# ── 配置 ────────────────────────────────────────────────────
_API_BASE  = os.environ.get("VUILABS_API_BASE", "https://api.vuilabs.cn")
_OSS_EP    = os.environ.get("OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com")
_OSS_BKT   = os.environ.get("OSS_BUCKET", "lunalab-res")
_OSS_DIR   = "ttsVoiceV1"
_OSS_AK    = os.environ.get("AliyunAccessKeyID", "")
_OSS_SK    = os.environ.get("AliyunAccessKeySecret", "")

CLONE_SENTENCES = [
    "我们明天上午十点在仓库见，你到了给我打电话。",
    "今天天气不错，我们可以明天早上出发。",
]

_API_TIMEOUT = 60   # TTS 生成超时（秒）
_SAVE_TIMEOUT = 30  # voice/save 超时（秒）


# ── OSS ─────────────────────────────────────────────────────

def _oss_bucket() -> oss2.Bucket:
    auth = oss2.Auth(_OSS_AK, _OSS_SK)
    return oss2.Bucket(auth, _OSS_EP, _OSS_BKT)


def _upload_wav(wav_path: str) -> str:
    """上传 WAV 到 OSS，返回 object_key。"""
    unique = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}.wav"
    key = f"{_OSS_DIR}/{unique}"
    bkt = _oss_bucket()
    with open(wav_path, "rb") as f:
        bkt.put_object(key, f)
    return key


def _upload_bytes(data: bytes, suffix: str = ".wav") -> str:
    """上传内存中的音频 bytes 到 OSS，返回 object_key。"""
    unique = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}{suffix}"
    key = f"{_OSS_DIR}/{unique}"
    _oss_bucket().put_object(key, data)
    return key


def _oss_url(key: str) -> str:
    return f"https://{_OSS_BKT}.{_OSS_EP}/{key}"


# ── Voice API ────────────────────────────────────────────────

def _save_voice(voice_id: str, ref_audio_key: str, ref_text: str, api_key: str):
    resp = requests.post(
        f"{_API_BASE}/v1/voice/save",
        headers={"X-API-Key": api_key},
        json={"voice_id": voice_id, "ref_audio": _oss_url(ref_audio_key), "ref_text": ref_text},
        timeout=_SAVE_TIMEOUT,
    )
    resp.raise_for_status()


def _delete_voice(voice_id: str, api_key: str):
    try:
        requests.delete(
            f"{_API_BASE}/v1/voice/{voice_id}",
            headers={"X-API-Key": api_key},
            timeout=_SAVE_TIMEOUT,
        )
    except Exception:
        pass  # 删除失败不中断流程


_TTS_FAST_RATE_THRESHOLD = 6.0  # 参考音频超过 6 字/秒时不再加速
_TTS_VERY_FAST_RATE_THRESHOLD = 7.0  # 超过 7 字/秒时轻微降速
_TTS_DEFAULT_SPEED = 1.1
_TTS_FAST_REF_SPEED = 1.0
_TTS_VERY_FAST_REF_SPEED = 0.9
_ROUND2_TTS_SPEED = 1.0


def _generate_audio(voice_id: str, text: str, api_key: str, speed: float) -> bytes:
    """调 TTS 同步接口，返回原始音频 bytes（WAV）。"""
    resp = requests.post(
        f"{_API_BASE}/v1/text-to-speech",
        headers={"X-API-Key": api_key},
        json={"voice_id": voice_id, "generate_text": text, "speed": speed},
        timeout=_API_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.content


# ── 音频后处理 ───────────────────────────────────────────────

_TRIM_FRAME_MS  = 20    # 帧长（毫秒）
_TRIM_RATIO     = 0.01  # 低于最大帧 RMS × ratio 视为静音
_TRIM_PADDING_S = 0.05  # 裁剪后保留的首尾 padding（秒）


def _trim_silence(data: np.ndarray, sr: int) -> np.ndarray:
    """按帧能量去掉首尾静音段（相对阈值，与振幅量级无关）。"""
    frame_size = max(1, int(_TRIM_FRAME_MS / 1000 * sr))
    n_frames = len(data) // frame_size
    if n_frames == 0:
        return data
    frames = data[: n_frames * frame_size].reshape(n_frames, frame_size).astype(np.float32)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    threshold = rms.max() * _TRIM_RATIO
    voiced = np.where(rms > threshold)[0]
    if len(voiced) == 0:
        return data
    pad_frames = max(1, int(_TRIM_PADDING_S * sr / frame_size))
    start = max(0, voiced[0] - pad_frames) * frame_size
    end   = min(n_frames, voiced[-1] + pad_frames + 1) * frame_size
    return data[start:end]


def _bytes_trim_silence(audio_bytes: bytes) -> bytes:
    """对音频 bytes 裁剪首尾静音，返回新的 WAV bytes。"""
    try:
        data, sr = sf.read(io.BytesIO(audio_bytes), dtype="int16", always_2d=False)
    except Exception:
        return audio_bytes
    if data.ndim > 1:
        data = data[:, 0]
    trimmed = _trim_silence(data, sr)
    buf = io.BytesIO()
    sf.write(buf, trimmed, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# ── 评分 ─────────────────────────────────────────────────────

# 正常普通话 TTS 语速范围（字/秒，只计汉字）
_RATE_LOW  = 2.5   # 低于此值为拖沓
_RATE_HIGH = 6.0   # 高于此值为急促
_RATE_OPT  = (3.2, 5.0)  # 最优区间，满分


def _count_chinese(text: str) -> int:
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")


def _speech_rate_score(duration_s: float, text: str) -> float:
    """语速评分（0~1）。拖沓或急促均扣分，正常区间得满分。"""
    n = _count_chinese(text)
    if n == 0 or duration_s <= 0:
        return 0.5
    rate = n / duration_s  # 字/秒
    lo, hi = _RATE_OPT
    if lo <= rate <= hi:
        return 1.0
    if rate < lo:
        # 低于 _RATE_LOW 得 0，线性插值
        return max(0.0, (rate - _RATE_LOW) / (lo - _RATE_LOW))
    # 高于 _RATE_HIGH 得 0，线性插值
    return max(0.0, 1.0 - (rate - hi) / (_RATE_HIGH - hi))


def _select_tts_speed(text: str, duration_s: float) -> tuple[float, float]:
    """根据参考音频字速选择 TTS speed：超过 7 字/秒降速，超过 6 字/秒不加速。"""
    n = _count_chinese(text)
    if n == 0 or duration_s <= 0:
        return 0.0, _TTS_DEFAULT_SPEED
    rate = n / duration_s
    if rate > _TTS_VERY_FAST_RATE_THRESHOLD:
        speed = _TTS_VERY_FAST_REF_SPEED
    elif rate > _TTS_FAST_RATE_THRESHOLD:
        speed = _TTS_FAST_REF_SPEED
    else:
        speed = _TTS_DEFAULT_SPEED
    return float(rate), float(speed)


def _score_audio_bytes(audio_bytes: bytes, sentence: str = "") -> float:
    """对 TTS 生成的音频 bytes 计算综合评分（含语速）。"""
    try:
        data, sr = sf.read(io.BytesIO(audio_bytes), dtype="int16", always_2d=False)
    except Exception:
        return 0.0
    if data.ndim > 1:
        data = data[:, 0]
    duration_s = len(data) / sr
    rms = _frame_rms(data, sr)
    short_ratio, burst_median = _speech_burst_stats(data, sr)
    fluency  = _fluency_score(short_ratio, burst_median)
    vol      = _vol_consistency_score(rms)
    rate     = _speech_rate_score(duration_s, sentence)
    # TTS 生成音频 SNR 通常很高，语速权重提至首位
    return 0.40 * rate + 0.35 * fluency + 0.25 * vol


# ── OSS Manifest ─────────────────────────────────────────────

def _append_manifest(manifest_path: Path, entries: list[dict]):
    existing: list[dict] = []
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    manifest_path.write_text(
        json.dumps(existing + entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 主流程 ───────────────────────────────────────────────────

def run(src: str, dst: str, api_key: str = "") -> StepResult:
    t0 = time.time()
    result = StepResult(step=6)

    if not api_key:
        result.fail("config", "未传入 VUILABS_API_KEY")
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result
    if not _OSS_AK or not _OSS_SK:
        result.fail("config", "未设置 OSS 环境变量 AliyunAccessKeyID / AliyunAccessKeySecret")
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    src_p = Path(src)
    dst_p = Path(dst)
    dst_p.mkdir(parents=True, exist_ok=True)
    manifest_path = dst_p / "oss_manifest.json"

    # 枚举 temp5 中每个货主通过 ASR 的 WAV；不强依赖 rank1_ 前缀。
    input_files = sorted(src_p.rglob("*.wav"))
    result.input_count = len(input_files)

    for wav_path in input_files:
        shipper_id = wav_path.parent.name
        txt_path   = wav_path.with_suffix(".txt")
        out_dir    = dst_p / shipper_id
        out_dir.mkdir(parents=True, exist_ok=True)

        # 读取 ref_text（Step 5 ASR 转录结果）
        if not txt_path.exists():
            result.fail(str(wav_path.relative_to(src_p)), "找不到对应 .txt 文件")
            continue
        ref_text = txt_path.read_text(encoding="utf-8").strip()
        if not ref_text:
            result.fail(str(wav_path.relative_to(src_p)), ".txt 内容为空")
            continue
        try:
            ref_info = sf.info(str(wav_path))
            ref_duration_s = float(ref_info.frames / ref_info.samplerate) if ref_info.samplerate else 0.0
        except Exception:
            ref_duration_s = 0.0
        ref_rate, r1_tts_speed = _select_tts_speed(ref_text, ref_duration_s)
        r2_tts_speed = _ROUND2_TTS_SPEED

        ts = int(time.time() * 1000)
        voice_r1 = f"manbang_{ts}_r1"
        voice_r2 = f"manbang_{ts}"
        oss_entries: list[dict] = []

        try:
            # ── Round 1 ──────────────────────────────────────
            # ① 上传原始 rank1 音频
            key_ref1 = _upload_wav(str(wav_path))
            oss_entries.append({"key": key_ref1, "shipper_id": shipper_id, "role": "round1_ref"})

            # ② 保存 Round 1 音色
            _save_voice(voice_r1, key_ref1, ref_text, api_key)

            # ③ 生成两段测试音频
            r1_audios: list[tuple[bytes, str]] = []  # (audio_bytes, sentence)
            for idx, sentence in enumerate(CLONE_SENTENCES, 1):
                audio_bytes = _bytes_trim_silence(_generate_audio(voice_r1, sentence, api_key, r1_tts_speed))
                out_path    = out_dir / f"r1_gen{idx}.wav"
                out_path.write_bytes(audio_bytes)
                r1_audios.append((audio_bytes, sentence))

            # ④ 评分，选较好的那段
            scores = [_score_audio_bytes(ab, sent) for ab, sent in r1_audios]
            best_idx      = int(np.argmax(scores))
            best_bytes, best_sentence = r1_audios[best_idx]

            # ⑤ 上传最优生成音频作为 Round 2 参考
            key_ref2 = _upload_bytes(best_bytes)
            oss_entries.append({"key": key_ref2, "shipper_id": shipper_id, "role": "round2_ref"})

        except Exception as e:
            result.fail(shipper_id, f"Round 1 失败: {e}")
            continue
        finally:
            # ⑥ 无论成功与否，删掉 Round 1 音色（释放额度）
            _delete_voice(voice_r1, api_key)
            _append_manifest(manifest_path, oss_entries)
            oss_entries = []

        try:
            # ── Round 2 ──────────────────────────────────────
            # ⑦ 保存 Round 2 音色（以最优生成音频为参考）
            _save_voice(voice_r2, key_ref2, best_sentence, api_key)

            # ⑧ 生成两段评估音频
            r2_scores: list[float] = []
            for idx, sentence in enumerate(CLONE_SENTENCES, 1):
                audio_bytes = _bytes_trim_silence(_generate_audio(voice_r2, sentence, api_key, r2_tts_speed))
                out_path    = out_dir / f"r2_gen{idx}.wav"
                out_path.write_bytes(audio_bytes)
                r2_scores.append(_score_audio_bytes(audio_bytes, sentence))

            # ⑨ 写 report.json
            def _audio_duration(b: bytes) -> float:
                try:
                    d, s = sf.read(io.BytesIO(b), dtype="int16", always_2d=False)
                    return len(d) / s
                except Exception:
                    return 0.0

            r1_durations = [_audio_duration(ab) for ab, _ in r1_audios]
            report = {
                "shipper_id":       shipper_id,
                "source_wav":       wav_path.name,
                "voice_id":         voice_r2,
                "ref_duration_s":   ref_duration_s,
                "ref_rate_chars_per_s": ref_rate,
                "r1_tts_speed":     r1_tts_speed,
                "r2_tts_speed":     r2_tts_speed,
                "r1_scores":        scores,
                "r1_durations_s":   r1_durations,
                "r1_best_idx":      best_idx + 1,   # 1-based
                "r1_best_sentence": best_sentence,
                "r2_scores":        r2_scores,
                "r2_avg_score":     float(np.mean(r2_scores)),
            }
            (out_dir / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            upsert_voice_id(shipper_id, voice_r2)
            result.output_count += 1

        except Exception as e:
            result.fail(shipper_id, f"Round 2 失败: {e}")

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
