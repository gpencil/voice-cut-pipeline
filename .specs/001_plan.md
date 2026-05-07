# 001 - 音频清洗 Pipeline 开发计划

## 目标

把客户提交的满帮电话录音清洗成可用于音色克隆的干净片段。

**本期范围**：仅做音频清洗（4 个处理步骤）。ASR、自动打分、一键全跑 留到下一期。

**使用者**：开发者自用（本地运行）。

## 输入约定

- 文件命名格式（满帮）：`{货主id}-{司机id}-{声道}-{录音id}-LR.wav`
  - 声道 `0` = 左声道是货主
  - 声道 `1` = 右声道是货主
- **要求双声道**：单声道输入 → 直接报错（加入 `errors`，跳过该文件）
- **WAV 格式不固定**：来源音频可能是 32-bit float / 24-bit PCM 等，统一在读入时通过 `soundfile` 转为 16-bit PCM。无法解码的文件 → 报错
- **单文件大小限制**：> 20 MB 直接报错（防 OOM）
- **批次规模**：建议每次处理 20~50 个文件，可控

## 输出

```
{work_dir}/
├── temp1/{shipper_id}/{原文件名}.wav        ← Step 1：按货主分类（拷贝）
├── temp2/{shipper_id}/{原文件名}.wav        ← Step 2：提取货主声道（单声道）
├── temp3/{shipper_id}/{原文件名}_001.wav    ← Step 3：按气口切分成多段
│                     /{原文件名}_002.wav        每段独立文件，段内连续
│                     /...
└── temp4/{shipper_id}/{原文件名}_001.wav    ← Step 4：过滤时长 ≥1s
                       /{原文件名}_003.wav         <1s 的"嗯/哦/好的"丢弃
                       /...
```

最终 `temp4/` 下的文件就是可用于音色克隆的干净片段（每段都是货主一次完整发言）。

## 处理步骤

### Step 1：按货主 ID 分类

- 输入：用户指定的源音频文件夹
- 逻辑：从每个文件名解析 `shipper_id`，拷贝到 `temp1/{shipper_id}/`
- **检查**：单文件大小 ≤ 20 MB；文件名匹配满帮格式；可读取
- **重名**：`temp1/{shipper_id}/` 下已有同名文件时，目标文件名追加 3 位随机后缀（如 `xxx-LR-A3F.wav`）
- 失败：写入 `errors`，跳过该文件

### Step 2：提取货主声道

- 输入：`temp1/`
- 逻辑：通过 `soundfile` 读取 → 转换为 PCM 16-bit → 根据文件名声道字段取出货主一侧 → 写为单声道 WAV
- **检查**：必须是双声道（单声道直接报错入 `errors`）
- 已有实现：迁移自 `~/code/src/yusheng/shipper-voice-demo/audio.py` 的 `extract_channel`、`parse_filename`

### Step 3：按气口切分（多段输出）

输入：`temp2/`。

**为什么切分而不是拼接**：电话录音是双向对话，去掉客户声道后，货主侧由多次发言组成，发言之间是"等客户说话"的长停顿。强行拼接会出现"嗯 → 那你最多多少 → 840 也行吧"这种语义跳跃，做音色克隆会不自然。所以按气口位置切分成独立段。

**气口定义**：
1. **长停顿**：振幅低于阈值（默认 300，16-bit PCM）且持续时间 > 0.3s 的段
2. **爆破声**：< 50ms 内 RMS 远超片段平均的 5~10 倍的孤立尖峰

**逻辑**：
- 用 0.3s 长停顿作为切分点，把音频切成多段连续语音
- **每段首尾保留 0.05s padding**，避免硬切感（沿用之前 `audio.py` 实现）
- 每段单独保存为 `temp3/{shipper_id}/{原文件名}_001.wav` 起编号
- 段内若检测到爆破声尖峰，把那一小段（<50ms）置零或微调拼回
- 此时不做时长过滤（即使 0.5s 的"嗯"也输出，留给 Step 4 过滤）

### Step 4：流畅过滤（时长筛选）

- 输入：`temp3/`
- 时长 ≥ **1s** 的片段拷贝到 `temp4/{shipper_id}/`
- 时长 < 1s 的丢弃（视为"嗯/哦/好的"无意义短答）

阈值 1s 是当前默认值。最终用于音色克隆的"最佳片段"在下期（自动打分）从这些 ≥1s 段里挑选，所以这一步保守一点保留更多素材。

## 错误处理约定

**粒度**：单文件出错不中断 step，跳过继续处理后续文件。

**status 字段**（接口返回）：
- `ok`：所有文件都成功处理
- `error`：有任何文件失败（仍完成了能处理的部分），未处理文件全部列在 `errors` 数组里

**`errors` 数组项格式**：
```json
{ "file": "xxx-LR.wav", "reason": "single channel not supported" }
```

**前端展示**：
- `status=ok` → 绿色 `完成 N/N`
- `status=error` → 黄色 `部分完成 N/M`，可展开看 errors 列表

## 输出目录安全策略

防止用户误填路径导致重要数据被删：

- 输出路径**必须包含 `temp` 子串**，否则接口直接 422 拒绝
- 输出路径**不能等于或包含源路径**
- 清空时只删该目录下匹配 `*.wav` 的文件 + 一级子目录里的 `*.wav`，不递归 `rm -rf`

## 重跑策略

- 重跑某一步时，**该步及其下游所有 tempN 都会清空再写**（避免脏数据）
- 例：重跑 Step 2 → 清空 temp2、temp3、temp4
- 前端在按钮上加 confirm 提示用户「将清空 temp2、temp3、temp4」

## 技术栈

| 维度 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.12+ | 音频处理生态成熟 |
| Web 框架 | FastAPI | 简单、自带 OpenAPI |
| 音频读写 | soundfile + numpy | 支持各种 WAV 格式，统一转 PCM 16-bit |
| 音频处理 | scipy.io.wavfile + numpy | 纯向量化，已验证性能 |
| 前端 | Vanilla HTML/JS | 不引入框架，单文件 |
| 数据 | 文件系统（无数据库） | 中间结果都是文件 |

## UI 设计

单页面，从上到下：

1. **工作目录配置**：输入框 + 确认按钮，配置 `work_dir`（绝对路径，必须含 `temp`）
2. **源文件夹**：输入框，填客户音频源文件夹绝对路径
3. **流水线区域**：4 个步骤卡片，每个卡片：
   - 输入路径（自动填充上一步输出，可手改）
   - 输出路径（自动填充 `{work_dir}/tempN`）
   - **运行**按钮 + **状态**（`pending` / `done` / `error`，运行中显示 button disabled + spinner）
   - 完成后展示统计：输入文件数 / 输出文件数 / 跳过数 / 错误数
   - errors 非空时可展开错误列表
4. 重跑按钮带 confirm，提示会清空哪些 tempN

> 同步 HTTP 接口，无后台任务。运行中前端不做轮询，靠 button disabled 和 loading 表示。

## 项目结构

```
voice-cut-pipeline/
├── app.py                       # FastAPI 入口，挂路由
├── pipeline/
│   ├── __init__.py
│   ├── common.py                # 文件名解析、wav 读写、errors 工具
│   ├── safety.py                # 输出路径安全检查、级联清理
│   ├── step1_classify.py        # 按货主 ID 分类
│   ├── step2_extract_channel.py # 提取货主声道
│   ├── step3_split.py           # 按气口切分成多段
│   └── step4_filter.py          # 时长过滤
├── static/
│   └── index.html               # 前端单页
├── requirements.txt
├── README.md
└── .specs/
    ├── instractions.MD
    └── 001_plan.md              # 本文档
```

## 接口设计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/`                  | 返回前端页面 |
| POST | `/run/step1`         | 入参：`{src, dst}` |
| POST | `/run/step2`         | 入参：`{src, dst}` |
| POST | `/run/step3`         | 入参：`{src, dst}` |
| POST | `/run/step4`         | 入参：`{src, dst}` |

> `/run/all`（一键全跑）放下一期。

每个接口返回：

```json
{
  "step": 3,
  "status": "ok",            // 或 "error"
  "input_count": 280,
  "output_count": 268,
  "skipped": 5,              // 文件名格式不符等
  "errors": [
    { "file": "xxx-LR.wav", "reason": "..." }
  ],
  "elapsed_ms": 1234
}
```

接口请求前置校验（不通过返回 422）：
- `dst` 必须包含 `temp`
- `dst` 不能等于或包含 `src`
- `src` 必须存在；不存在或为空目录直接返回 `input_count=0`，不报错

## 关键参数（默认值，写在 `pipeline/common.py` 常量里）

| 参数 | 默认值 | 用途 |
|---|---|---|
| `MAX_FILE_SIZE_MB` | 20 | Step 1 单文件大小上限 |
| `SILENCE_THRESHOLD` | 300 | 16-bit PCM 振幅阈值，低于此视为静音 |
| `BREATH_MIN_DURATION` | 0.3s | Step 3 气口/切分点最小时长 |
| `SEGMENT_PADDING` | 0.05s | Step 3 每段首尾保留的过渡时长 |
| `PLOSIVE_PEAK_RATIO` | 7.0 | Step 3 爆破声判定：峰值 vs 段均值倍数 |
| `PLOSIVE_WINDOW_MS` | 50 | Step 3 爆破声检测窗口 |
| `SEGMENT_MIN_DURATION` | 1.0s | Step 4 保留片段最短时长 |

## 开发顺序

1. **基础脚手架**：项目骨架、`common.py`、`safety.py`、FastAPI 启动 + 静态前端 hello world
2. **Step 1 + 安全检查**：分类（先打通 → 验证 dst 安全检查 → 验证级联清理）
3. **Step 2**：提取声道（含格式转换、单声道报错处理）
4. **前端 UI**：4 个步骤卡片框架（含错误列表展开）
5. **Step 3**：按气口切分（先实现长停顿检测，爆破声后加）
6. **Step 4**：时长过滤
7. **联调**：用 `~/Downloads/满帮音色/...` 实际数据全流程跑通

## 边界情况处理

| 边界 | 处理策略 |
|---|---|
| 源目录不存在 | `input_count=0`，`status=ok`，不报错 |
| 源目录为空 | 同上 |
| 文件名不符合满帮格式 | 跳过，`skipped+1`，不计入 errors |
| 单声道 WAV | 报错入 `errors`，跳过该文件 |
| WAV 不是 PCM 16-bit（32-bit float / 24-bit 等） | 用 soundfile 自动转换为 PCM 16-bit |
| 损坏的 WAV / 无法解码 | 报错入 `errors`，跳过 |
| 单文件 > 20 MB | 报错入 `errors`，跳过（防 OOM） |
| 采样率不一致 | 不处理，保留原采样率（下游音色克隆自己处理） |
| 重复文件名 | 目标文件名加 3 位随机后缀 |
| Step 3 整个录音切完都 < 1s | Step 4 全部过滤掉，统计中体现"该原文件无产出" |
| 部分电话录音存在串音 | 本期不处理，后期可加"声道相关性检测" |

## 验收标准

用 `~/Downloads/满帮音色/满帮第二次克隆音色/音色克隆外部/20260111/` 这 280 个文件分批次（每批 20~50 个）跑通：

- Step 1：按货主分类正确，重名/超大/损坏文件能正确报错或加随机后缀
- Step 2：所有输出为单声道 WAV，听感为货主声音；单声道输入正确报错
- Step 3：每个原始文件被切成多个段，段内是连续语音，段间无跨气口拼接
- Step 4：每个货主目录下若干 ≥1s 片段；挑 3-5 个人工试听，是货主完整发言、无突兀拼接、无客户串音

如果某些客户的音频本身质量过差导致无产出，**复核确认音频问题后让客户重新提供**，不在 Pipeline 内做兜底。
