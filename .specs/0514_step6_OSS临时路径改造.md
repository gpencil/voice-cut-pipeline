# 0514 step6 OSS 临时路径改造

## 背景

`step6_clone.py` 当前把临时 ref_audio 上传到 `lunalab-res` 的 `ttsVoiceV1/` 前缀
下，与 **api-gateway 用户永久克隆音色**挤在同一前缀，违反
`api-gateway/AGENTS.md` 中「`ttsVoiceV1/` = 用户永久资产，禁止写临时文件」的约定，
且无 lifecycle 兜底导致 OSS 永久累积垃圾。

`lunalab-res` 已在 2026-05-14 配置 lifecycle 规则：前缀 `temp_delete/`、距最后
修改 7 天自动删除。本次把 step6 上传路径迁到该规则覆盖的 `temp_delete/{业务名}/...`
下，符合 yusheng 工作区的 OSS 文件分类约定，同时由 lifecycle 兜底自动清理。

## 目标

把 step6 两个上传函数的 OSS 路径从 `ttsVoiceV1/{ms}_{hex}.wav` 改为
`temp_delete/voice-cut-pipeline/{YYYYMMDD}/{ms}_{hex}.wav`，让 lifecycle 7 天规则
覆盖之，无需手动清理。

## 范围

- 仓库：本仓 `voice-cut-pipeline`
- 文件：
  - `pipeline/step6_clone.py`：`_OSS_DIR` 常量 + 两个 `_upload_*` 函数路径拼接
  - `.specs/001_plan.md`：Step 6 描述里「上传到 OSS（`ttsVoiceV1/` 目录）」一行
- **不涉及**：
  - 历史脏数据（已在 `ttsVoiceV1/` 下的对象）—— 临时项目，按用户决定**不清理**
  - api-gateway / yusheng 工作区任何文件
  - lifecycle 规则本身（已配，跨工作区运维操作）

## 设计要点

1. **新路径**：`temp_delete/voice-cut-pipeline/{YYYYMMDD}/{ms}_{hex}.wav`
   - 业务名 `voice-cut-pipeline` 与仓库名一致，与 `temp_delete/ai-detect/` 区分
   - 加 YYYYMMDD 分层方便人工排查特定一天的批次（lifecycle 不依赖该分层）
2. **不动 `oss_manifest.json` 结构**：仍记录完整 object_key，只是新路径
3. **不动 `_save_voice` 等业务逻辑**：`ref_audio` 用 `_oss_url(key)` 生成，仅 URL 路径段变化，api-gateway 侧 HTTP 下载对前缀无感
4. **不增加主动 `DeleteObject`**：与 api-gateway 一致，best-effort 即可，靠 lifecycle 兜底；当前 AK 也无 DeleteObject 权限，调了也是 403

## 步骤

- [x] 1. 起草本计划
- [x] 2. 改 `pipeline/step6_clone.py`：
      - `_OSS_DIR = "ttsVoiceV1"` → `_OSS_DIR = "temp_delete/voice-cut-pipeline"`
      - `_upload_wav` / `_upload_bytes` 里 key 拼接为
        `f"{_OSS_DIR}/{datetime.now():%Y%m%d}/{unique}"`
- [x] 3. 同步 `.specs/001_plan.md` Step 6 描述里的路径
- [x] 4. 跑 `pytest tests/test_step6_inputs.py -v`
      → 验证：测试仍通过（既有测试用 `patch("pipeline.step6_clone._upload_wav")` mock，
      与路径变更解耦，但需要确认 import 等没坏）
- [ ] 5. **人工核验**：用户跑一次完整 Step 6（至少 1 个货主），确认：
      - OSS 控制台 `temp_delete/voice-cut-pipeline/YYYYMMDD/` 下能看到 2 个对象（round1_ref + round2_ref）
      - `temp6/{shipper_id}/oss_manifest.json` 里 key 字段是新路径
      - `report.json` 正常生成，voice clone 流程未受影响

## 残余风险

- `temp6/oss_manifest.json` 里**新旧路径混存**：如果用户之前跑过 step6 留下旧 manifest，
  会有 `ttsVoiceV1/...` 和 `temp_delete/voice-cut-pipeline/...` 两类 key 混着。
  这只影响人工排查可读性，不影响业务。
- 历史 `ttsVoiceV1/{ms}_{hex}.wav` 临时对象**继续残留**：用户明确表示「脏数据不要管，
  这是临时项目」。如果未来需要清理，按命名规律
  「`ttsVoiceV1/` 直接子层、无日期分层、`{毫秒}_{8位hex}.wav`」识别再批量删，
  注意区分 api-gateway 真用户音色（位于 `ttsVoiceV1/YYYYMMDD/` 子目录下）。

## 评审人检查清单（待人工通过）

- [ ] 用户实际跑过一次 step6，OSS 控制台能看到新路径下的对象
- [ ] `oss_manifest.json` key 字段已切换到新前缀
- [ ] voice clone（Round 1 / Round 2）成功，`report.json` 完整
