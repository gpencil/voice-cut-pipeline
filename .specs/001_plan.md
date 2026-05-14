# 001 - 音频清洗 Pipeline 开发计划

## 目标

把客户提交的满帮电话录音清洗成可用于音色克隆的干净片段。

**使用者**：开发者自用（本地运行）。

---

## 流水线全貌

```
源音频
  │
  ▼ Step 1：按货主 ID 分类                    → temp1/{shipper_id}/
  ▼ Step 2：提取货主声道                      → temp2/{shipper_id}/{shipper_id}_001.wav
  ▼ Step 3：按气口切分 + 时长过滤（≥2s）      → temp3/{shipper_id}/{shipper_id}_001_001.wav
  ▼ Step 4：音质筛选（9 条规则）+ 评分排名    → temp4/{shipper_id}/rank{N}_*.wav
  ▼ Step 5：ASR 内容过滤（仅 rank1）          → temp5/{shipper_id}/rank1_*.wav + .txt
  ▼ Step 6：两轮音色克隆验证                  → temp6/{shipper_id}/r{1,2}_gen{1,2}.wav + report.json
  ▼ Step 7：删除音色记录                      → 按 voice_id 删除远端音色
```

---

## 输入约定

- 文件命名格式（满帮）：`{货主id}-{司机id}-{声道}-{录音id}-LR.wav`
  - 声道 `0` = 左声道是货主
  - 声道 `1` = 右声道是货主
- **要求双声道**：单声道输入 → 直接报错（加入 `errors`，跳过该文件）
- **WAV 格式不固定**：来源音频可能是 32-bit float / 24-bit PCM 等，统一在读入时通过 `soundfile` 转为 16-bit PCM
- **单文件大小限制**：> 20 MB 直接报错（防 OOM）

---

## 处理步骤

### Step 1：按货主 ID 分类

- 输入：用户指定的源音频文件夹
- 逻辑：从每个文件名解析 `shipper_id`，拷贝到 `temp1/{shipper_id}/`
- **检查**：单文件大小 ≤ 20 MB；文件名匹配满帮格式；可读取
- **重名**：目标文件名追加 3 位随机后缀

### Step 2：提取货主声道

- 输入：`temp1/`
- 逻辑：根据文件名声道字段取出货主一侧 → 写为单声道 WAV（PCM 16-bit）
- 输出短文件名：`{shipper_id}_{NNN}.wav`，如 `400000001_001.wav`
- 每个货主目录写 `manifest.json`，记录短文件名对应的原始录音文件名

### Step 3：按气口切分 + 时长过滤

- 输入：`temp2/`，输出：`temp3/`
- 气口定义：振幅低于阈值（300）且持续 > 0.3s 的停顿
- 每段首尾保留 0.05s padding
- 时长 < `SEGMENT_MIN_DURATION`（默认 2s）的段**直接丢弃**，不写磁盘
- 输出短文件名：`{shipper_id}_{源序号}_{切段序号}.wav`，如 `400000001_001_001.wav`
- 延续 `manifest.json`，保留原始录音追踪

### Step 4：音质筛选 + 评分排名

- 输入：`temp3/`，输出：`temp4/`
- 过滤规则（阈值均在 `pipeline/common.py`）：

| # | 规则 | 捕获问题 | 常量 |
|---|------|---------|------|
| 1 | SNR ≥ 15 dB | 持续底噪 / 背景人声 | `QUALITY_SNR_MIN_DB` |
| 2 | 语音帧占比 ≥ 50% | 内容太少 | `QUALITY_SPEECH_RATIO_MIN` |
| 3 | Tukey 爆破帧 = 0 | 瞬间脉冲噪声 | `NOISE_SPIKE_MAX_FRAMES` |
| 4 | max/p95 ≤ 1.8 | 偶发能量异常 | `NOISE_TAIL_MAX_P95_RATIO` |
| 5 | 静音活跃度 ≤ 0.15 | 静音段有背景声 | `SILENCE_ACTIVITY_MAX` |
| 6 | 噪声语音帧占比 ≤ 10% | 频谱平坦/混声/呲声 | `NOISY_VOICED_RATIO_MAX` |
| 7 | 高频擦噪帧数 = 0 | 短促“呲/嘶”声 | `HISS_SPIKE_MAX_FRAMES` |
| 8 | 低频能量比 ≤ 0.25 | 电梯/环境低频噪声 | `LOW_FREQ_ENERGY_MAX` |
| 9 | 短语音段占比 ≤ 30% | 卡壳/断续 | `SPEECH_SHORT_BURST_MAX` |
| - | 中位语音段时长 | 不再硬过滤，仅参与流畅度评分 | `SPEECH_MIN_BURST_MEDIAN_S` |

通过硬过滤的文件进入**评分排名**（综合评分 0~1，越高越好）：

| 维度 | 权重 | 说明 |
|------|------|------|
| 流畅度 | 50% | 语音段连续自然，非磕巴；排序第一优先级 |
| 音量一致性 | 20% | 全段音量稳定，非忽大忽小 |
| SNR | 15% | 信噪比（上限 30 dB） |
| 噪声语音帧 | 10% | 频谱平坦度低（纯人声） |
| 低频能量 | 3% | 无电梯/环境低频 |
| 语音占比 | 2% | 有效内容足够 |

输出文件以 `rank{N}_` 前缀保存，`rank1` 为该货主评分最高的片段；默认每个货主只保留前 5 名。`manifest.json` 同步记录原始文件名和评分。

说明：`SPEECH_MIN_BURST_MEDIAN_S` 早期作为硬过滤会误杀一些听感正常但语句较短的片段，目前只用于流畅度评分，不再单独剔除。

开头清理：Step 4 在音质规则前会先裁掉开头空白；如果开头第一段有声很短（如“嗯/哦/好”）且后面有明显停顿，也会裁掉该短开头，只处理开头，不改中间和结尾。`manifest.json` 记录 `leading_trimmed_s`。

### Step 5：ASR 内容过滤

- 输入：`temp4/`，输出：`temp5/`
- 仅对 `rank1_*` 文件调用自建 ASR（`ASR_TOP_N=1`）

**ASR 过滤**：`POST multipart/form-data`（字段 `audio`），返回 `{"transcript":"..."}`
- 丢弃条件（任一命中）：
  - 有效汉字数 < `ASR_MIN_CHARS`（默认 5）
  - 最高频字符占比 > `ASR_MAX_REPEAT_RATIO`（默认 50%，捕捉"嗯嗯嗯"类）
- ASR 调用失败 → 记入 `errors`，**保留文件**
- 通过的音频存入 `temp5/{shipper_id}/`，同时写同名 `.txt` 保存转录文本，并在 `manifest.json` 中记录转录文本

### Step 6：两轮音色克隆验证

- 输入：`temp5/{shipper_id}/rank1_*.wav`（含同名 `.txt`），输出：`temp6/`
- 目的：验证 rank1 音频实际克隆效果是否流畅，筛出卡顿问题

**Round 1（选优）**：

1. 上传 `rank1_*.wav` 到 OSS（`temp_delete/voice-cut-pipeline/{YYYYMMDD}/` 目录，
   由 `lunalab-res` 上 `temp_delete/` 前缀 7 天 lifecycle 自动清理；详见
   `.specs/0514_step6_OSS临时路径改造.md`）→ 记入 `temp6/oss_manifest.json`
2. `POST /v1/voice/save`（`voice_id=manbang_{ts}_r1`，`ref_audio=OSS URL`，`ref_text=.txt内容`）
3. 用 Round 1 音色生成两段固定测试音频：
   - 句子 A：`我们明天上午十点在仓库见，你到了给我打电话。`
   - 句子 B：`今天天气不错，我们可以明天早上出发。`
   - 保存为 `temp6/{shipper_id}/r1_gen1.wav`、`r1_gen2.wav`
4. 对两段生成音频评分（流畅度 45% + 音量一致性 35% + SNR 20%），取评分较高者为 `best_audio`
5. 上传 `best_audio` 到 OSS → 记入 manifest
6. `DELETE /v1/voice/manbang_{ts}_r1`（释放音色额度）

**Round 2（精炼）**：

7. `POST /v1/voice/save`（`voice_id=manbang_{ts}`，`ref_audio=best_audio OSS URL`，`ref_text=对应句子`）
8. 用 Round 2 音色再生成两段评估音频 → `r2_gen1.wav`、`r2_gen2.wav`
9. 写 `report.json`：含 voice_id、R1/R2 评分、最终参考句子

**OSS 清理**：`temp6/oss_manifest.json` 记录所有上传的 `object_key`，可按需批量删除

**环境变量**：

| 变量 | 说明 |
|------|------|
| `VUILABS_API_KEY` | 音色克隆 API 密钥（必填） |
| `AliyunAccessKeyID` | OSS AK（与 api-gateway 相同） |
| `AliyunAccessKeySecret` | OSS SK |
| `OSS_ENDPOINT` | 默认 `oss-cn-hangzhou.aliyuncs.com` |
| `OSS_BUCKET` | 默认 `lunalab-res` |

### Step 7：删除音色记录

- 输入：`voice_id` + `api_key`
- 逻辑：调用 `DELETE /v1/voice/{voice_id}` 删除远端音色记录
- 不读取/写入/清空任何 `temp` 目录，可独立运行
- 用于人工核验后清理不再需要的 `manbang_{ts}` 音色

---

## 错误处理约定

**粒度**：单文件出错不中断 step，跳过继续处理后续文件。

**status 字段**：
- `ok`：所有文件都成功处理
- `error`：有任何文件失败（仍完成了能处理的部分）

**`errors` 数组项**：
```json
{ "file": "xxx-LR.wav", "reason": "..." }
```

---

## 输出目录安全策略

- 输出路径**必须包含 `temp` 子串**，否则接口直接 422 拒绝
- 输出路径**不能等于或包含源路径**
- 清空时只删该目录下 `*.wav` 文件 + 一级子目录里的 `*.wav`，不递归 `rm -rf`

---

## 重跑策略

重跑某一步时，该步及其下游所有 tempN 都会清空再写。

| 重跑步骤 | 级联清空 |
|---------|---------|
| Step 1 | temp1 → temp2 → temp3 → temp4 → temp5 → temp6 |
| Step 2 | temp2 → temp3 → temp4 → temp5 → temp6 |
| Step 3 | temp3 → temp4 → temp5 → temp6 |
| Step 4 | temp4 → temp5 → temp6 |
| Step 5 | temp5 → temp6 |
| Step 6 | temp6 |
| Step 7 | 不清空 temp，仅调用远端删除接口 |

---

## 技术栈

| 维度 | 选择 |
|------|------|
| 语言 | Python 3.12+ |
| Web 框架 | FastAPI |
| 音频读写 | soundfile + numpy |
| 音频处理 | scipy + numpy（纯向量化） |
| 前端 | Vanilla HTML/JS（单文件） |
| 数据 | 文件系统（无数据库） |

---

## 项目结构

```
voice-cut-pipeline/
├── app.py
├── pipeline/
│   ├── __init__.py
│   ├── common.py                # 常量、文件名解析、WAV 读写
│   ├── safety.py                # 路径安全检查、级联清理
│   ├── step1_classify.py
│   ├── step2_extract_channel.py
│   ├── step3_split.py           # 按气口切分 + 时长过滤
│   ├── step4_quality.py         # 音质筛选（9 条规则）+ 评分排名
│   ├── step5_asr.py             # ASR 内容过滤
│   └── step6_clone.py           # 两轮音色克隆验证
├── static/
│   └── index.html
├── requirements.txt
├── README.md
└── .specs/
    └── 001_plan.md
```

---

## 接口设计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| POST | `/run/step1` | `{src, dst, work_dir?}` |
| POST | `/run/step2` | 同上 |
| POST | `/run/step3` | 同上 |
| POST | `/run/step4` | 同上 |
| POST | `/run/step5` | 同上 |
| POST | `/run/step6` | 同上 |
| POST | `/run/step7` | `{voice_id, api_key}` |

返回格式：
```json
{
  "step": 5,
  "status": "ok",
  "input_count": 94,
  "output_count": 71,
  "skipped": 23,
  "errors": [],
  "elapsed_ms": 12000
}
```

---

## 关键参数

| 参数 | 默认值 | 用途 |
|------|--------|------|
| `MAX_FILE_SIZE_MB` | 20 | Step 1 单文件大小上限 |
| `SILENCE_THRESHOLD` | 300 | 振幅阈值（16-bit PCM） |
| `BREATH_MIN_DURATION` | 0.3s | Step 3 气口最小时长 |
| `SEGMENT_PADDING` | 0.05s | Step 3 每段首尾过渡 |
| `SEGMENT_MIN_DURATION` | 2.0s | Step 3 切分时丢弃短段的下限 |
| `QUALITY_SNR_MIN_DB` | 15.0 | Step 4 最低信噪比 |
| `QUALITY_SPEECH_RATIO_MIN` | 0.5 | Step 4 语音帧占比下限 |
| `NOISE_SPIKE_MAX_FRAMES` | 0 | Step 4 允许爆破帧数 |
| `NOISE_TAIL_MAX_P95_RATIO` | 1.8 | Step 4 尾部能量比上限 |
| `SILENCE_ACTIVITY_MAX` | 0.15 | Step 4 静音活跃度上限 |
| `NOISY_VOICED_RATIO_MAX` | 0.10 | Step 4 噪声语音帧占比上限 |
| `HISS_HIGH_FREQ_RATIO_MIN` | 0.22 | Step 4 高频擦噪候选帧的 3kHz 以上能量占比阈值 |
| `HISS_SFM_MIN` | 0.28 | Step 4 高频擦噪候选帧的频谱平坦度阈值 |
| `HISS_HIGH_BAND_TUKEY_K` | 2.5 | Step 4 高频能量局部突刺 Tukey 阈值 |
| `HISS_SPIKE_MAX_FRAMES` | 0 | Step 4 允许的高频擦噪帧数上限 |
| `LOW_FREQ_ENERGY_MAX` | 0.25 | Step 4 低频能量比上限 |
| `SPEECH_SHORT_BURST_MAX` | 0.30 | Step 4 短语音段占比上限 |
| `SPEECH_MIN_BURST_MEDIAN_S` | 0.35s | Step 4 流畅度评分参考值，不作为硬过滤 |
| `QUALITY_TOP_N` | 5 | Step 4 每货主保留的排名数量 |
| `ASR_BASE_URL` | 环境变量 | Step 5 自建 ASR 服务地址 |
| `ASR_MIN_CHARS` | 5 | Step 5 有效汉字数下限 |
| `ASR_MAX_REPEAT_RATIO` | 0.5 | Step 5 重复字符比例上限 |
| `ASR_TOP_N` | 3 | Step 5 每货主送 ASR 的片段数上限 |
| `ASR_TIMEOUT_S` | 15 | Step 5 单次 ASR 调用超时（秒） |
| `VUILABS_API_KEY` | 环境变量（必填） | Step 6 音色克隆 API 密钥 |
| `AliyunAccessKeyID` | 环境变量 | Step 6 OSS AK |
| `AliyunAccessKeySecret` | 环境变量 | Step 6 OSS SK |
| `OSS_ENDPOINT` | `oss-cn-hangzhou.aliyuncs.com` | Step 6 OSS 节点 |
| `OSS_BUCKET` | `lunalab-res` | Step 6 OSS 存储桶 |
