# voice-cut-pipeline

满帮电话录音清洗流水线 - 4 步生成可用于音色克隆的干净片段。

## 流水线

| Step | 输入 | 输出 | 说明 |
|---|---|---|---|
| 1 | 源文件夹 | `temp1/{shipper_id}/*.wav` | 按货主 ID 分类（拷贝） |
| 2 | `temp1/` | `temp2/{shipper_id}/*.wav` | 按声道提取货主单声道 |
| 3 | `temp2/` | `temp3/{shipper_id}/*_001.wav, _002.wav, ...` | 按 0.3s 气口切分成多段 |
| 4 | `temp3/` | `temp4/{shipper_id}/*.wav` | 时长 ≥ 1s 过滤 |

最终 `temp4/` 下的片段就是可用于音色克隆的素材。

## 输入文件名约定

满帮格式：`{货主id}-{司机id}-{声道}-{录音id}-LR.wav`

- 声道 `0` = 左声道是货主
- 声道 `1` = 右声道是货主

## 启动

```bash
pip3 install -r requirements.txt
python3 -m uvicorn app:app --port 8801 --reload
```

打开 http://localhost:8801

## 使用

1. 工作目录填一个含 `temp` 字样的绝对路径（如 `/tmp/vcp-test`），temp1-4 自动建在下面
2. 源文件夹填客户音频文件夹绝对路径
3. 顺序点击 Step 1 → 4 的运行按钮，每步会清空当前 step 输出 + 下游 tempN

## 设计文档

`.specs/001_plan.md`

## 关键参数

写死在 `pipeline/common.py`：

| 参数 | 值 | 用途 |
|---|---|---|
| `MAX_FILE_SIZE_MB` | 20 | 单文件大小上限 |
| `SILENCE_THRESHOLD` | 300 | 16-bit PCM 振幅阈值 |
| `BREATH_MIN_DURATION` | 0.3s | 气口切分阈值 |
| `SEGMENT_PADDING` | 0.05s | 切段首尾过渡时长 |
| `SEGMENT_MIN_DURATION` | 1.0s | Step 4 保留下限 |

## 接口

| 方法 | 路径 | 入参 |
|---|---|---|
| GET | `/` | 前端页面 |
| POST | `/run/step1` ~ `step4` | `{src, dst, work_dir?}` |

返回：

```json
{
  "step": 1,
  "status": "ok",
  "input_count": 280,
  "output_count": 280,
  "skipped": 0,
  "errors": [],
  "elapsed_ms": 767
}
```

## 限制

- 仅支持满帮文件名格式
- 单文件 > 20MB 报错（防 OOM）
- 单声道输入报错（需要双声道才能提取货主侧）
- 不做 ASR、不做自动打分（下期）
