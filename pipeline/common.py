"""
通用工具：常量、文件名解析、WAV 读写、错误工具。
"""

from __future__ import annotations

import re
import secrets
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
SEGMENT_MIN_DURATION = 1.0         # Step 4 保留片段最短时长（秒）

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
