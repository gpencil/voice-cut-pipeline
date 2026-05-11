"""
通用工具：常量、文件名解析、WAV 读写、错误工具。
"""

from __future__ import annotations

import re
import secrets
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

# ---------- 常量 ----------

MAX_FILE_SIZE_MB = 20
SILENCE_THRESHOLD = 300            # 16-bit PCM 振幅阈值
BREATH_MIN_DURATION = 0.3          # 气口最短时长（秒）
SEGMENT_PADDING = 0.05             # Step 3 切分后每段首尾保留的过渡（秒）
PLOSIVE_PEAK_RATIO = 7.0
PLOSIVE_WINDOW_MS = 50
SEGMENT_MIN_DURATION = 2.0         # Step 3 保留片段最短时长（秒）

# ---------- Step 4 音质筛选 ----------
QUALITY_SNR_MIN_DB = 15.0          # 最低信噪比（dB），低于此值丢弃
QUALITY_SPEECH_RATIO_MIN = 0.5     # 有效语音帧占比下限，低于此值丢弃

# 瞬间噪声爆破检测（基于 Tukey fence）
NOISE_SPIKE_TUKEY_K = 3.0          # 上限 = p75 + K * IQR，超出即为异常帧
NOISE_SPIKE_MAX_FRAMES = 0         # 允许超限帧数上限（含），超过则丢弃
# 尾部能量比检测（捕捉非爆破型偶发噪声）
NOISE_TAIL_MAX_P95_RATIO = 1.8     # max / p95 超过此值则丢弃
# 背景人声检测：静音段活跃度
# 静音帧（底噪2倍以下）的平均RMS / 整体均值RMS，高于此值说明"静音"里有背景声
SILENCE_ACTIVITY_MAX = 0.15
# 噪声语音帧检测：语音帧中频谱平坦度（SFM）> 0.5 的比例
# SFM 接近 1 = 白噪声，接近 0 = 纯谐波语音；占比过高说明含噪声混声
NOISY_VOICED_RATIO_MAX = 0.10
# 高频擦噪检测：捕捉短促“呲/嘶”一类高频宽带噪声
HISS_HIGH_FREQ_RATIO_MIN = 0.22     # 3kHz 以上能量占比超过此值视为高频异常候选
HISS_SFM_MIN = 0.28                 # 候选帧还需频谱足够平坦，避免误伤正常谐波
HISS_HIGH_BAND_TUKEY_K = 2.5        # 高频能量局部突刺上限 = p75 + K * IQR
HISS_SPIKE_MAX_FRAMES = 0           # 允许的高频擦噪帧数上限（50ms/帧）
# 低频能量比（< 300 Hz 占总能量），高于此值说明有电梯/环境低频噪声
LOW_FREQ_ENERGY_MAX = 0.25
# 语音流畅性检测
SPEECH_SHORT_BURST_MAX = 0.30      # 短语音段（< 0.15s）占比上限，超过说明卡壳
SPEECH_MIN_BURST_MEDIAN_S = 0.35   # 语音段时长中位数下限，低于说明说话太碎
QUALITY_TOP_N: int = 5             # 每个货主最多保留前 N 名（0 = 不限制）

# ---------- Step 5 ASR 内容过滤 ----------
import os as _os
ASR_BASE_URL: str = _os.environ.get("ASR_BASE_URL", "http://118.196.29.26:27003/asr")
ASR_TIMEOUT_S: float = 15.0        # 单次 ASR 调用超时（秒）
ASR_MIN_CHARS: int = 5             # 有效汉字数下限，低于则丢弃
ASR_MAX_REPEAT_RATIO: float = 0.5  # 最高频字符占比上限，超过视为重复噪声输出
ASR_TOP_N: int = 1                 # 每个货主最多送 ASR 的片段数（取评分最高的 N 个）

# 满帮文件名：{货主id}-{司机id}-{声道}-{录音id}-LR.wav
FILENAME_PATTERN = re.compile(
    r"^(\d+)-(\d+)-([01])-(.+?)-LR\.wav$",
    re.IGNORECASE,
)


# ---------- 数据结构 ----------

@dataclass
class StepResult:
    step: int
    status: str = "ok"          # "ok" 或 "error"
    input_count: int = 0
    output_count: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0

    def fail(self, file: str, reason: str):
        self.errors.append({"file": file, "reason": reason})
        self.status = "error"

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "status": self.status,
            "input_count": self.input_count,
            "output_count": self.output_count,
            "skipped": self.skipped,
            "errors": self.errors,
            "elapsed_ms": self.elapsed_ms,
        }


# ---------- 文件名 ----------

@dataclass
class ParsedName:
    shipper_id: str
    driver_id: str
    channel: str        # "0" 左 / "1" 右
    record_id: str


def parse_filename(filename: str) -> Optional[ParsedName]:
    """无法解析返回 None。"""
    m = FILENAME_PATTERN.match(filename)
    if not m:
        return None
    return ParsedName(
        shipper_id=m.group(1),
        driver_id=m.group(2),
        channel=m.group(3),
        record_id=m.group(4),
    )


def random_suffix(n: int = 3) -> str:
    """生成 n 位 [A-Z0-9] 随机后缀。"""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def add_random_suffix_before_ext(filename: str) -> str:
    """xxx-LR.wav -> xxx-LR-A3F.wav"""
    p = Path(filename)
    return f"{p.stem}-{random_suffix()}{p.suffix}"


MANIFEST_FILENAME = "manifest.json"


def load_manifest(directory: str | Path) -> dict:
    path = Path(directory) / MANIFEST_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_manifest(directory: str | Path, manifest: dict):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    (path / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def origin_from_manifest(manifest: dict, filename: str) -> str:
    entry = manifest.get(filename)
    if isinstance(entry, dict):
        return str(entry.get("origin") or entry.get("source") or filename)
    if isinstance(entry, str):
        return entry
    return filename


# ---------- WAV IO ----------

def read_wav_pcm16(path: str) -> tuple[int, np.ndarray]:
    """
    用 soundfile 读取，强制转为 PCM 16-bit int 数组。
    返回 (samplerate, data)，data shape: (n,) 单声道 / (n, 2) 立体声。
    """
    data, sr = sf.read(path, dtype="int16", always_2d=False)
    return sr, data


def write_wav_pcm16(path: str, samplerate: int, data: np.ndarray):
    """写 16-bit PCM WAV。"""
    sf.write(path, data.astype(np.int16), samplerate, subtype="PCM_16")


def file_size_mb(path: str) -> float:
    return Path(path).stat().st_size / (1024 * 1024)
