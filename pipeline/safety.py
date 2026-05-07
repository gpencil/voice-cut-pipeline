"""
路径安全检查与级联清理。
"""

from __future__ import annotations

from pathlib import Path


class SafetyError(Exception):
    pass


def validate_dst(dst: str, src: str | None = None):
    """
    输出路径必须包含 'temp'，且不能等于或包含 src。
    不通过抛 SafetyError。
    """
    if "temp" not in Path(dst).name and "temp" not in dst:
        raise SafetyError(f"输出目录必须含 'temp' 字样：{dst}")

    if src:
        dst_abs = Path(dst).resolve()
        src_abs = Path(src).resolve()
        if dst_abs == src_abs:
            raise SafetyError(f"输出目录不能等于源目录：{dst}")
        if src_abs in dst_abs.parents:
            raise SafetyError(f"输出目录不能位于源目录之内：dst={dst} src={src}")
        if dst_abs in src_abs.parents:
            raise SafetyError(f"输出目录不能包含源目录：dst={dst} src={src}")


def safe_clear_temp(dst: str):
    """
    清空 dst 目录下的 *.wav（含一级子目录里的 *.wav），不递归 rm -rf。
    dst 必须先经过 validate_dst。
    """
    p = Path(dst)
    if not p.exists():
        return

    for wav in p.glob("*.wav"):
        wav.unlink(missing_ok=True)
    for sub in p.iterdir():
        if sub.is_dir():
            for wav in sub.glob("*.wav"):
                wav.unlink(missing_ok=True)
            try:
                sub.rmdir()
            except OSError:
                pass


def cascade_clear(work_dir: str, from_step: int):
    """
    级联清空 from_step 起的所有 tempN（N..4）。
    使用 work_dir/tempN 作为目标，每个都做 validate_dst + safe_clear。
    """
    for step in range(from_step, 5):
        target = str(Path(work_dir) / f"temp{step}")
        validate_dst(target)
        safe_clear_temp(target)
