# voice-cut-pipeline

满帮电话录音清洗流水线 - 7 步生成、验证并管理可用于音色克隆的干净片段。

## 流水线

| Step | 输入 | 输出 | 说明 |
|---|---|---|---|
| 1 | 源文件夹 | `temp1/{shipper_id}/*.wav` | 按货主 ID 分类（拷贝） |
| 2 | `temp1/` | `temp2/{shipper_id}/{shipper_id}_001.wav` | 按声道提取货主单声道，写 `manifest.json` |
| 3 | `temp2/` | `temp3/{shipper_id}/{shipper_id}_001_001.wav …` | 按 0.3s 气口切分 + 丢弃 < 2s 短段 |
| 4 | `temp3/` | `temp4/{shipper_id}/rank{N}_*.wav` | 裁掉开头空白/短语气词 → 9 条音质规则过滤 → 评分排名，默认保留前 5 |
| 5 | `temp4/` | `temp5/{shipper_id}/rank1_*.wav + .txt` | 对 rank1 调自建 ASR，过滤内容不达标片段 |
| 6 | `temp5/` | `temp6/{shipper_id}/r{1,2}_gen{1,2}.wav` | 两轮音色克隆验证 |
| 7 | `voice_id` | 删除远端音色记录 | 根据 voice_id 调删除接口，不清理 temp |

`temp2` 之后每个货主目录都会写 `manifest.json`，用短文件名保留原始录音追踪。

## 输入文件名约定

满帮格式：`{货主id}-{司机id}-{声道}-{录音id}-LR.wav`

- 声道 `0` = 左声道是货主
- 声道 `1` = 右声道是货主

## 启动

```bash
# 首次：用 Homebrew 纯 arm64 Python 创建虚拟环境
/opt/homebrew/bin/python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 后续：激活后直接启动
source .venv/bin/activate
uvicorn app:app --port 8801 --reload
```

打开 http://localhost:8801

## 使用

1. 工作目录填一个含 `temp` 字样的绝对路径（如 `/tmp/vcp-test`），temp1-6 自动建在下面
2. 源文件夹填客户音频文件夹绝对路径
3. 顺序点击 Step 1 → 6 的运行按钮，每步会清空当前 step 输出 + 下游 tempN；Step 7 可单独按 voice_id 删除音色

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
| `SEGMENT_MIN_DURATION` | 2.0s | Step 3 切分时丢弃的短段下限 |
| `QUALITY_TOP_N` | 5 | Step 4 每货主保留的排名数量 |
| `ASR_TOP_N` | 1 | Step 5 每货主送 ASR 的片段数 |

## 接口

| 方法 | 路径 | 入参 |
|---|---|---|
| GET | `/` | 前端页面 |
| POST | `/run/step1` ~ `/run/step5` | `{src, dst, work_dir?}` |
| POST | `/run/step6` | `{src, dst, work_dir?, api_key}` |
| POST | `/run/step7` | `{voice_id, api_key}` |

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
- ASR 仅调自建服务，地址通过环境变量 `ASR_BASE_URL` 配置
