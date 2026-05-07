"""
Step 1：按货主 ID 分类。
- 解析文件名 → 拷贝到 dst/{shipper_id}/
- 检查：≤20MB、文件名格式、可读
- 重名加 3 位随机后缀
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from .common import (
    MAX_FILE_SIZE_MB,
    StepResult,
    add_random_suffix_before_ext,
    file_size_mb,
    parse_filename,
)


def run(src: str, dst: str) -> StepResult:
    t0 = time.time()
    result = StepResult(step=1)

    src_path = Path(src)
    dst_path = Path(dst)

    if not src_path.exists() or not src_path.is_dir():
        result.elapsed_ms = int((time.time() - t0) * 1000)
        return result

    dst_path.mkdir(parents=True, exist_ok=True)

    files = sorted([f for f in src_path.iterdir()
                    if f.is_file() and f.suffix.lower() == ".wav"])
    result.input_count = len(files)

    for f in files:
        meta = parse_filename(f.name)
        if not meta:
            result.skipped += 1
            continue

        try:
            size = file_size_mb(str(f))
        except OSError as e:
            result.fail(f.name, f"读取失败: {e}")
            continue

        if size > MAX_FILE_SIZE_MB:
            result.fail(f.name, f"超过 {MAX_FILE_SIZE_MB}MB 限制（{size:.1f}MB）")
            continue

        target_dir = dst_path / meta.shipper_id
        target_dir.mkdir(parents=True, exist_ok=True)

        target_name = f.name
        if (target_dir / target_name).exists():
            target_name = add_random_suffix_before_ext(f.name)

        try:
            shutil.copy2(str(f), str(target_dir / target_name))
            result.output_count += 1
        except OSError as e:
            result.fail(f.name, f"拷贝失败: {e}")

    result.elapsed_ms = int((time.time() - t0) * 1000)
    return result
