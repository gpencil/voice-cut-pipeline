"""
Step 4：音质筛选 + 评分排名。
输入：temp3/  输出：temp4/

两阶段：
  1. 硬过滤（9 条规则，任一不达标则丢弃）
  2. 对通过的文件评分，按货主分组排名，以 rank{N}_ 前缀保存

输出文件名格式：rank{N}_{短文件名}.wav
  - rank1 = 该货主评分最高的片段，优先用于音色克隆
  - rank2、rank3 … 依次递减，供人工对比参考

硬过滤规则（阈值在 common.py 调节）：
  1. SNR ≥ QUALITY_SNR_MIN_DB
  2. 有效语音帧占比 ≥ QUALITY_SPEECH_RATIO_MIN
  3. Tukey 超限帧数 ≤ NOISE_SPIKE_MAX_FRAMES
  4. max / p95 ≤ NOISE_TAIL_MAX_P95_RATIO
  5. 静音段活跃度 ≤ SILENCE_ACTIVITY_MAX
  6. 噪声语音帧占比 ≤ NOISY_VOICED_RATIO_MAX
  7. 高频擦噪帧数 ≤ HISS_SPIKE_MAX_FRAMES
  8. 低频能量比 ≤ LOW_FREQ_ENERGY_MAX
  9. 短语音段占比 ≤ SPEECH_SHORT_BURST_MAX
  语音段时长中位数不再作为硬过滤，只参与流畅度评分。

评分权重：
  流畅度 50% + 音量一致性 20% + SNR 15% + 噪声语音帧 10% + 低频能量 3% + 语音占比 2%
"""

from __future__ import annotations

import shutil
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from .common import (
    HISS_HIGH_FREQ_RATIO_MIN,
    HISS_HIGH_BAND_TUKEY_K,
    HISS_SFM_MIN,
    HISS_SPIKE_MAX_FRAMES,
    LOW_FREQ_ENERGY_MAX,
    NOISE_SPIKE_MAX_FRAMES,
    NOISE_SPIKE_TUKEY_K,
    NOISE_TAIL_MAX_P95_RATIO,
    NOISY_VOICED_RATIO_MAX,
    QUALITY_SNR_MIN_DB,
    QUALITY_SPEECH_RATIO_MIN,
    QUALITY_TOP_N,
    SILENCE_ACTIVITY_MAX,
    SILENCE_THRESHOLD,
    SPEECH_SHORT_BURST_MAX,
    StepResult,
    load_manifest,
    origin_from_manifest,
    read_wav_pcm16,
    save_manifest,
    write_wav_pcm16,
)

_FRAME_MS = 50  # 帧长（毫秒）
_LEADING_TRIM_PADDING_S = 0.05
_LEADING_FILLER_MAX_S = 0.75
_LEADING_FILLER_GAP_MIN_S = 0.04
_TRAILING_TRIM_MIN_S = 0.05
_TRAILING_TRIM_PADDING_S = 0.0
_TRAILING_ISOLATED_BURST_MAX_S = 0.20
_TRAILING_ISOLATED_GAP_MIN_S = 0.08


# ────────────────────────────────────────────────────────────
# 底层信号工具
# ────────────────────────────────────────────────────────────

def _as_mono(data: np.ndarray) -> np.ndarray:
    """Step 4 指标统一按单声道计算，避免双声道 reshape 失败。"""
    if data.ndim == 1:
        return data.astype(np.int16, copy=False)
    if data.ndim == 2:
        return np.mean(data.astype(np.float32), axis=1).astype(np.int16)
    return data.reshape(-1).astype(np.int16)


def _frame_rms(data: np.ndarray, samplerate: int) -> np.ndarray:
    data = _as_mono(data)
    frame_size = int(samplerate * _FRAME_MS / 1000)
    n = len(data) // frame_size
    if n < 5:
        return np.array([])
    frames = data[:n * frame_size].reshape(n, frame_size).astype(np.float32)
    return np.sqrt(np.mean(frames ** 2, axis=1))


def _estimate_snr(rms: np.ndarray) -> float:
    if len(rms) == 0:
        return 99.0
    n_noise = max(1, len(rms) // 5)
    noise_rms = np.mean(np.sort(rms)[:n_noise])
    if noise_rms < 1.0:
        return 99.0
    return float(20 * np.log10(np.mean(rms) / noise_rms))


def _speech_ratio(data: np.ndarray) -> float:
    data = _as_mono(data)
    return float(np.mean(np.abs(data) > SILENCE_THRESHOLD))


def _spike_frames(rms: np.ndarray) -> int:
    if len(rms) == 0:
        return 0
    p25, p75 = np.percentile(rms, [25, 75])
    upper = p75 + NOISE_SPIKE_TUKEY_K * (p75 - p25)
    return int(np.sum(rms > upper))


def _tail_ratio(rms: np.ndarray) -> float:
    if len(rms) == 0:
        return 1.0
    p95 = np.percentile(rms, 95)
    if p95 < 1.0:
        return 1.0
    return float(rms.max() / p95)


def _noisy_voiced_ratio(data: np.ndarray, samplerate: int) -> float:
    data = _as_mono(data)
    rms = _frame_rms(data, samplerate)
    if len(rms) == 0:
        return 0.0
    frame_size = int(samplerate * _FRAME_MS / 1000)
    n = len(data) // frame_size
    frames = data[:n * frame_size].reshape(n, frame_size).astype(np.float64)
    noise_floor = np.mean(np.sort(rms)[:max(1, len(rms) // 5)])
    voiced_mask = rms > noise_floor * 2
    if voiced_mask.sum() == 0:
        return 0.0
    sfms = []
    for frame in frames[voiced_mask]:
        mag = np.abs(np.fft.rfft(frame))[1:]
        mag = np.maximum(mag, 1e-10)
        sfms.append(float(np.exp(np.mean(np.log(mag))) / np.mean(mag)))
    return float(np.mean(np.array(sfms) > 0.5))


def _hiss_frame_flags(data: np.ndarray, samplerate: int) -> tuple[np.ndarray, np.ndarray, int]:
    """返回每个 50ms 帧是否为高频擦噪候选。"""
    data = _as_mono(data)
    rms = _frame_rms(data, samplerate)
    if len(rms) == 0:
        return np.array([], dtype=bool), rms, 0

    frame_size = int(samplerate * _FRAME_MS / 1000)
    n = len(data) // frame_size
    frames = data[:n * frame_size].reshape(n, frame_size).astype(np.float64)
    freqs = np.fft.rfftfreq(frame_size, 1 / samplerate)
    high_mask = freqs >= 3000
    if not high_mask.any():
        return np.zeros(n, dtype=bool), rms, frame_size

    noise_floor = np.mean(np.sort(rms)[:max(1, len(rms) // 5)])
    # 高频“呲”常出现在停顿里，能量未必达到语音帧阈值；这里用更低的 active 阈值。
    voiced_mask = rms > max(20.0, noise_floor * 0.5)
    high_ratios: list[float] = []
    sfms: list[float] = []
    high_band_rms: list[float] = []
    voiced_indices = np.where(voiced_mask)[0]

    for frame in frames[voiced_mask]:
        mag = np.abs(np.fft.rfft(frame))[1:]
        mag = np.maximum(mag, 1e-10)
        power = mag ** 2
        high_power = float(power[high_mask[1:]].sum())
        total_power = float(power.sum()) + 1e-10
        high_ratios.append(high_power / total_power)
        sfms.append(float(np.exp(np.mean(np.log(mag))) / np.mean(mag)))
        high_band_rms.append(float(np.sqrt(high_power / max(1, int(high_mask.sum())))))

    if not high_band_rms:
        return np.zeros(n, dtype=bool), rms, frame_size

    high_arr = np.array(high_band_rms)
    p25, p75 = np.percentile(high_arr, [25, 75])
    high_upper = p75 + HISS_HIGH_BAND_TUKEY_K * (p75 - p25)
    median_high = float(np.median(high_arr)) + 1e-9

    flags = np.zeros(n, dtype=bool)
    for frame_idx, high_ratio, sfm, high_rms in zip(voiced_indices, high_ratios, sfms, high_band_rms):
        is_broadband_hiss = high_ratio > HISS_HIGH_FREQ_RATIO_MIN and sfm > HISS_SFM_MIN
        is_local_spike = high_rms > high_upper and high_rms / median_high > 2.5
        # 有些“呲”声是连续擦噪，不一定形成很尖的局部突刺；候选帧本身也直接计入。
        if is_broadband_hiss or is_local_spike:
            flags[frame_idx] = True
    return flags, rms, frame_size


def _hiss_spike_frames(data: np.ndarray, samplerate: int) -> int:
    """检测短促高频宽带噪声帧，主要捕捉“呲/嘶”类异常声。"""
    flags, _, _ = _hiss_frame_flags(data, samplerate)
    return int(flags.sum())


def _voiced_runs(voiced: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    in_run = False
    start = 0
    for i, value in enumerate(voiced):
        if value and not in_run:
            start = i
            in_run = True
        elif not value and in_run:
            runs.append((start, i))
            in_run = False
    if in_run:
        runs.append((start, len(voiced)))
    return runs


def _trim_leading_start(data: np.ndarray, samplerate: int) -> tuple[np.ndarray, float]:
    """只裁开头空白或很短的开头语气词（嗯/哦/好），不处理中间和结尾。"""
    data = _as_mono(data)
    rms = _frame_rms(data, samplerate)
    if len(rms) == 0:
        return data, 0.0

    frame_size = int(samplerate * _FRAME_MS / 1000)
    noise_floor = np.mean(np.sort(rms)[:max(1, len(rms) // 5)])
    threshold = max(SILENCE_THRESHOLD * 0.5, noise_floor * 2)
    voiced = rms > threshold
    runs = _voiced_runs(voiced)
    if not runs:
        return data, 0.0

    trim_frame = runs[0][0]

    # 开头很短且后面有明显停顿，视为“嗯/哦/好”一类起始语气词。
    if len(runs) >= 2:
        first_start, first_end = runs[0]
        second_start, second_end = runs[1]
        first_s = (first_end - first_start) * _FRAME_MS / 1000
        gap_s = (second_start - first_end) * _FRAME_MS / 1000
        second_s = (second_end - second_start) * _FRAME_MS / 1000
        short_filler = first_s <= 0.45
        longer_filler_before_main = first_s <= _LEADING_FILLER_MAX_S and second_s >= 0.70
        if first_start <= 1 and (short_filler or longer_filler_before_main) and gap_s >= _LEADING_FILLER_GAP_MIN_S:
            trim_frame = second_start

    pad = int(_LEADING_TRIM_PADDING_S * samplerate)
    trim_sample = max(0, trim_frame * frame_size - pad)
    if trim_sample <= 0:
        return data, 0.0
    return data[trim_sample:].astype(np.int16), trim_sample / samplerate


def _trim_trailing_residue(data: np.ndarray, samplerate: int) -> tuple[np.ndarray, float]:
    """只裁末尾残留：连续低能量尾巴，或停顿后的孤立短尾段。"""
    data = _as_mono(data)
    rms = _frame_rms(data, samplerate)
    if len(rms) == 0:
        return data, 0.0

    frame_size = int(samplerate * _FRAME_MS / 1000)
    noise_floor = np.mean(np.sort(rms)[:max(1, len(rms) // 5)])
    threshold = max(SILENCE_THRESHOLD * 0.5, noise_floor * 2)
    active = rms > threshold
    active_indices = np.where(active)[0]
    if len(active_indices) == 0:
        return data, 0.0

    runs = _voiced_runs(active)
    if len(runs) >= 2:
        prev_start, prev_end = runs[-2]
        last_start, last_end = runs[-1]
        last_s = (last_end - last_start) * _FRAME_MS / 1000
        gap_s = (last_start - prev_end) * _FRAME_MS / 1000
        prev_s = (prev_end - prev_start) * _FRAME_MS / 1000
        after_last_s = (len(rms) - last_end) * _FRAME_MS / 1000
        if (
            last_s <= _TRAILING_ISOLATED_BURST_MAX_S
            and gap_s >= _TRAILING_ISOLATED_GAP_MIN_S
            and prev_s >= 0.50
            and after_last_s <= _TRAILING_TRIM_MIN_S
        ):
            end_sample = min(len(data), last_start * frame_size)
            if end_sample < len(data):
                return data[:end_sample].astype(np.int16), (len(data) - end_sample) / samplerate

    last_active = int(active_indices[-1])
    tail_frames = len(rms) - (last_active + 1)
    tail_s = tail_frames * _FRAME_MS / 1000
    if tail_s < _TRAILING_TRIM_MIN_S:
        return data, 0.0

    pad = int(_TRAILING_TRIM_PADDING_S * samplerate)
    end_sample = min(len(data), (last_active + 1) * frame_size + pad)
    if end_sample >= len(data):
        return data, 0.0
    return data[:end_sample].astype(np.int16), (len(data) - end_sample) / samplerate


def _speech_burst_stats(data: np.ndarray, samplerate: int) -> tuple[float, float]:
    rms = _frame_rms(data, samplerate)
    if len(rms) == 0:
        return 0.0, 99.0
    noise_floor = np.mean(np.sort(rms)[:max(1, len(rms) // 5)])
    voiced = rms > noise_floor * 2

    bursts: list[float] = []
    in_burst = False
    start = 0
    for i, v in enumerate(voiced):
        if v and not in_burst:
            start = i; in_burst = True
        elif not v and in_burst:
            bursts.append((i - start) * _FRAME_MS / 1000)
            in_burst = False
    if in_burst:
        bursts.append((len(rms) - start) * _FRAME_MS / 1000)

    if not bursts:
        return 0.0, 99.0
    arr = np.array(bursts)
    return float(np.mean(arr < 0.15)), float(np.median(arr))


def _low_freq_energy_ratio(data: np.ndarray, samplerate: int, cutoff: int = 300) -> float:
    data = _as_mono(data)
    mag = np.abs(np.fft.rfft(data.astype(np.float64)))
    freqs = np.fft.rfftfreq(len(data), 1 / samplerate)
    lo = float((mag[freqs < cutoff] ** 2).sum())
    total = float((mag ** 2).sum()) + 1e-10
    return lo / total


def _silence_activity(rms: np.ndarray) -> float:
    if len(rms) == 0:
        return 0.0
    n_noise = max(1, len(rms) // 5)
    noise_floor = np.mean(np.sort(rms)[:n_noise])
    silence_mask = rms < noise_floor * 2
    if silence_mask.sum() == 0:
        return 0.0
    overall = np.mean(rms)
    if overall < 1.0:
        return 0.0
    return float(np.mean(rms[silence_mask]) / overall)


# ────────────────────────────────────────────────────────────
# 综合评分（仅用于排名，不做硬过滤）
# ────────────────────────────────────────────────────────────

def _vol_consistency_score(rms: np.ndarray) -> float:
    """语音帧 RMS 变异系数（CV）反转为 0~1 得分，CV 越低越好。"""
    voiced = rms[rms >= SILENCE_THRESHOLD * 0.5] if len(rms) > 0 else np.array([])
    if len(voiced) < 2:
        return 1.0
    cv = float(np.std(voiced) / (np.mean(voiced) + 1e-9))
    return max(0.0, 1.0 - (cv - 0.35) / (0.80 - 0.35))


def _fluency_score(short_ratio: float, burst_median: float) -> float:
    """由已计算好的 burst 统计量直接得分。"""
    short_score  = 1.0 - min(short_ratio / 0.30, 1.0)
    median_score = max(0.0, min((burst_median - 0.15) / (0.50 - 0.15), 1.0))
    return 0.5 * short_score + 0.5 * median_score


def _quality_score(
    data: np.ndarray,
    samplerate: int,
    rms: np.ndarray,
    nvr: float,
    lfr: float,
    short_ratio: float,
    burst_median: float,
) -> float:
    """
    综合评分 0~1，越高越好。
    权重：流畅度 50% + 音量一致性 20% + SNR 15% + 噪声语音帧 10% + 低频能量 3% + 语音占比 2%
    """
    detail = _quality_score_detail(data, samplerate, rms, nvr, lfr, short_ratio, burst_median)
    return float(detail["score"])


def _quality_score_detail(
    data: np.ndarray,
    samplerate: int,
    rms: np.ndarray,
    nvr: float,
    lfr: float,
    short_ratio: float,
    burst_median: float,
) -> dict:
    """返回综合评分和各分项，便于人工核验排序原因。"""
    fluency   = _fluency_score(short_ratio, burst_median)
    vol       = _vol_consistency_score(rms)
    snr_score = min(_estimate_snr(rms) / 30.0, 1.0)   # 30 dB 以上收益递减
    nvr_score = 1.0 - min(nvr / 0.5, 1.0)
    lfr_score = 1.0 - min(lfr / 0.5, 1.0)
    sr_score  = min(_speech_ratio(data) / 0.8, 1.0)

    score = (0.50 * fluency + 0.20 * vol + 0.15 * snr_score
             + 0.10 * nvr_score + 0.03 * lfr_score + 0.02 * sr_score)
    return {
        "score": round(float(score), 6),
        "fluency": round(float(fluency), 6),
        "volume_consistency": round(float(vol), 6),
        "snr": round(float(snr_score), 6),
        "noisy_voiced": round(float(nvr_score), 6),
        "low_freq": round(float(lfr_score), 6),
        "speech_ratio": round(float(sr_score), 6),
        "short_burst_ratio": round(float(short_ratio), 6),
        "burst_median_s": round(float(burst_median), 6),
    }


# ────────────────────────────────────────────────────────────
# 主流程
# ────────────────────────────────────────────────────────────

def run(src: str, dst: str) -> StepResult:
    t0 = time.time()
    result = StepResult(step=4)

    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.exists() or not src_path.is_dir():
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    dst_path.mkdir(parents=True, exist_ok=True)

    files = sorted(f for f in src_path.rglob("*.wav") if f.is_file())
    result.input_count = len(files)

    # ── 阶段一：硬过滤，收集通过文件及已算好的指标 ──
    # 每条目：(shipper_id, src_file, score_detail, output_audio, sr, leading_trimmed_s, trailing_trimmed_s)
    passing: list[tuple[str, Path, dict, np.ndarray | None, int, float, float]] = []

    for f in files:
        try:
            sr, data = read_wav_pcm16(str(f))
        except Exception as e:
            result.fail(f.name, f"读取失败: {e}")
            continue

        data, leading_trimmed_s = _trim_leading_start(data, sr)
        data, trailing_trimmed_s = _trim_trailing_residue(data, sr)

        rms = _frame_rms(data, sr)

        snr = _estimate_snr(rms)
        if snr < QUALITY_SNR_MIN_DB:
            result.skipped += 1
            result.errors.append({"file": f.name, "reason": f"SNR 过低: {snr:.1f} dB"})
            continue

        ratio = _speech_ratio(data)
        if ratio < QUALITY_SPEECH_RATIO_MIN:
            result.skipped += 1
            result.errors.append({"file": f.name, "reason": f"语音占比过低: {ratio:.2%}"})
            continue

        spikes = _spike_frames(rms)
        if spikes > NOISE_SPIKE_MAX_FRAMES:
            result.skipped += 1
            result.errors.append({"file": f.name, "reason": f"爆破噪声: {spikes} 帧超出 Tukey 上限"})
            continue

        tail = _tail_ratio(rms)
        if tail > NOISE_TAIL_MAX_P95_RATIO:
            result.skipped += 1
            result.errors.append({"file": f.name, "reason": f"尾部能量异常: max/p95={tail:.2f}"})
            continue

        sa = _silence_activity(rms)
        if sa > SILENCE_ACTIVITY_MAX:
            result.skipped += 1
            result.errors.append({"file": f.name, "reason": f"背景声过强: 静音活跃度={sa:.3f}"})
            continue

        nvr = _noisy_voiced_ratio(data, sr)
        if nvr > NOISY_VOICED_RATIO_MAX:
            result.skipped += 1
            result.errors.append({"file": f.name, "reason": f"混声/杂音: 噪声语音帧={nvr:.1%}"})
            continue

        hiss_frames = _hiss_spike_frames(data, sr)
        if hiss_frames > HISS_SPIKE_MAX_FRAMES:
            result.skipped += 1
            result.errors.append({"file": f.name, "reason": f"高频呲声: {hiss_frames} 帧"})
            continue

        lfr = _low_freq_energy_ratio(data, sr)
        if lfr > LOW_FREQ_ENERGY_MAX:
            result.skipped += 1
            result.errors.append({"file": f.name, "reason": f"低频噪声: 低频能量={lfr:.3f}"})
            continue

        short_ratio, burst_median = _speech_burst_stats(data, sr)
        if short_ratio > SPEECH_SHORT_BURST_MAX:
            result.skipped += 1
            result.errors.append({"file": f.name, "reason": f"说话卡壳: 短段占比={short_ratio:.1%}"})
            continue
        score_detail = _quality_score_detail(data, sr, rms, nvr, lfr, short_ratio, burst_median)
        if leading_trimmed_s > 0:
            score_detail["leading_trimmed_s"] = round(float(leading_trimmed_s), 3)
        if trailing_trimmed_s > 0:
            score_detail["trailing_trimmed_s"] = round(float(trailing_trimmed_s), 3)
        shipper_id = f.parent.name
        trimmed = leading_trimmed_s > 0 or trailing_trimmed_s > 0
        passing.append((shipper_id, f, score_detail, data if trimmed else None, sr, leading_trimmed_s, trailing_trimmed_s))

    # ── 阶段二：按货主排名，以 rank{N}_ 前缀拷贝到 dst ──
    by_shipper: dict[str, list[tuple[float, Path, dict, np.ndarray | None, int, float, float]]] = defaultdict(list)
    for shipper_id, f, score_detail, output_audio, sr, leading_trimmed_s, trailing_trimmed_s in passing:
        by_shipper[shipper_id].append((float(score_detail["score"]), f, score_detail, output_audio, sr, leading_trimmed_s, trailing_trimmed_s))

    for shipper_id, entries in by_shipper.items():
        entries.sort(key=lambda x: x[0], reverse=True)
        if QUALITY_TOP_N > 0:
            entries = entries[:QUALITY_TOP_N]
        target_dir = dst_path / shipper_id
        target_dir.mkdir(parents=True, exist_ok=True)
        src_manifest = load_manifest(entries[0][1].parent) if entries else {}
        dst_manifest = load_manifest(target_dir)
        for rank, (score, f, score_detail, output_audio, sr, leading_trimmed_s, trailing_trimmed_s) in enumerate(entries, 1):
            dst_file = target_dir / f"rank{rank}_{f.name}"
            try:
                if output_audio is not None:
                    write_wav_pcm16(str(dst_file), sr, output_audio)
                else:
                    shutil.copy2(str(f), str(dst_file))
                dst_manifest[dst_file.name] = {
                    "source": f.name,
                    "origin": origin_from_manifest(src_manifest, f.name),
                    "score": round(float(score), 6),
                    "score_detail": score_detail,
                    "leading_trimmed_s": round(float(leading_trimmed_s), 3),
                    "trailing_trimmed_s": round(float(trailing_trimmed_s), 3),
                }
                result.output_count += 1
            except OSError as e:
                result.fail(f.name, f"拷贝失败: {e}")
        save_manifest(target_dir, dst_manifest)

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
