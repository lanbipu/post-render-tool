# PRD

## VP Post-Render Tool — PRD v2

---

### Problem Statement

VP/XR 虚拟制片现场拍摄后，后期合成师经常需要在 UE 中对 CG 画面进行离线重渲染（穿帮修补、画面扩展、质量升级），再回到 AE / Nuke 与实拍素材合成。这要求 UE 中的摄影机运镜、视角、镜头畸变与现场完全一致。

当前从 Disguise Designer Shot Recorder 导出的 CSV Dense 数据到 UE 重渲染没有自动化链路。现有 FBX 导入方式只能生成 Camera Actor（非 Cine Camera Actor），丢失 Lens Distortion、Sensor Size、Aperture、Focus Distance 等物理镜头参数。手动配置全部参数和动画曲线耗时约 2-4 小时/镜头，且易出错，对不具备 UE 脚本能力的后期合成师而言门槛过高。

**不解决此问题的代价**：每个需要重渲染的镜头增加数小时手工配置时间，参数错误导致 CG 与实拍无法对齐需要反复返工，项目交付周期延长，合成师被迫学习 UE Python 脚本或依赖 TD 支持。

---

### Goals

1. **消除手动配置时间**：将单镜头从 CSV 到可渲染 Level Sequence 的配置时间从 2-4 小时降至 < 60 秒（一键完成）
2. **保证渲染精度**：重渲染画面与现场摄影机的 FOV 误差 < 0.05°，确保 AE / Nuke 中与实拍素材像素级对齐
3. **降低使用门槛**：后期合成师无需编写任何代码，通过 GUI 完成全部操作
4. **覆盖完整物理镜头参数链**：自动处理 Focal Length、Sensor Size、Lens Distortion (k1/k2/k3)、Center Shift、Aperture、Focus Distance，不丢失任何参数

---

### Non-Goals

1. **不负责 Designer 端的录制与导出** — 录制配置属于现场 TD 职责，与本工具解耦
2. **不自动触发 Movie Render Queue 渲染** — 避免误操作长时间占用渲染机器，由用户手动启动和配置输出格式
3. **不支持多相机同时导入（v1）** — 单 CSV 对应单 Camera，多相机场景留给 v2，降低 v1 复杂度
4. **不处理 Anamorphic 镜头 de-squeeze** — 需要额外的 squeeze ratio 参数解析逻辑，作为 v2 独立 feature
5. **不做实拍素材自动对齐** — Timecode 关联 Media Track 涉及素材管理流程，v1 聚焦 CG 重渲染链路

---

### Target Users

**影视后期合成师** — 日常工具为 AE / Nuke，具备基础 UE 操作能力（打开项目、播放 Sequence、使用 Movie Render Queue），不具备 Python / Blueprint 编程能力。

---

### User Stories

**后期合成师**

- As a 后期合成师, I want to 通过文件对话框选择 CSV Dense 文件并立即看到帧数、Timecode 范围等预览信息, so that 我可以确认选对了文件再执行导入
- As a 后期合成师, I want to 一键将 CSV 数据转换为完整的 Cine Camera Actor + Lens File + Level Sequence, so that 我不需要手动配置任何摄影机参数和动画曲线
- As a 后期合成师, I want to 导入完成后看到 FOV 校验结果和异常帧检测报告, so that 我可以确认数据转换精度符合合成要求
- As a 后期合成师, I want to 直接从工具面板打开 Sequencer 和 Movie Render Queue, so that 我可以快速预览和启动渲染，不需要在 UE 界面中手动查找
- As a 后期合成师, I want to 在 CSV 格式异常或字段缺失时看到明确的中文错误提示, so that 我可以自行排查问题而不需要求助 TD

---

### Requirements

#### Must-Have (P0)

**F1 — CSV Dense 解析引擎**

- 支持 Disguise Designer Shot Recorder 导出的 CSV Dense 格式
- 自动识别 camera 字段名前缀（`camera:cam_1`、`camera:cam_2` 等）
- 通过系统文件对话框选择文件
- Acceptance Criteria:
    - Given 一个合法的 CSV Dense 文件, When 用户选择该文件, Then 工具正确解析所有字段并显示预览信息（帧数、Timecode 范围、Focal Length 范围、Sensor Width）
    - Given 一个字段缺失的 CSV 文件, When 用户选择该文件, Then 工具显示明确的中文错误提示，指出缺失的字段名

**F2 — 坐标系转换**

- Designer Y-up（米）→ UE Z-up（厘米）
- Position 轴映射 + 单位转换（×100）
- Rotation 轴映射 + 角度方向约定转换
- 转换规则在代码中集中定义，便于后续调整
- Acceptance Criteria:
    - Given Designer 坐标系数据, When 执行转换, Then UE 中摄影机的空间位置和朝向与 Designer 中完全一致
    - Given 转换规则需要调整, When 修改集中定义的转换参数, Then 无需改动其他代码即可生效

**F3 — Lens File 自动生成**

- 从 CSV 中按 focal length 采样代表性数据点
- 将 Designer mm 单位畸变数据换算为 UE 归一化格式：
    - FxFy：`Fx = focalLengthMM / paWidthMM`，`Fy = Fx × aspectRatio`
    - Image Center：`Cx = 0.5 + centerShiftMM.x / paWidthMM`，`Cy = 0.5 + centerShiftMM.y / (paWidthMM / aspectRatio)`
- P1/P2 设为 0，Nodal Offset 设为 (0,0,0)
- 保存为 UE 原生 `.ulens` 资产
- Acceptance Criteria:
    - Given CSV 中包含畸变参数, When 生成 Lens File, Then 在 UE Lens File Editor 中可查看到正确的标定数据点
    - Given 变焦镜头数据（Focal Length 变化）, When 生成 Lens File, Then 按不同焦距分组包含多个标定点

**F4 — Cine Camera Actor 自动创建与配置**

- 创建 Cine Camera Actor（非 Camera Actor）
- 自动设置 Filmback Sensor Width = CSV 中的 `paWidthMM`
- 自动添加 Lens Component 并关联 F3 生成的 Lens File
- Acceptance Criteria:
    - Given 导入完成, When 检查生成的 Camera, Then 类型为 CineCameraActor，Filmback Sensor Width 与 CSV 一致，Lens Component 已关联正确的 Lens File

**F5 — Level Sequence 自动创建与动画写入**

- 创建 Level Sequence，将 Cine Camera Actor 添加为 Possessable
- 从 CSV 逐帧写入动画曲线：Location、Rotation、Current Focal Length、Current Aperture、Manual Focus Distance
- 帧率从 CSV 时间戳间隔自动推算，或由用户在 UI 中手动指定
- Acceptance Criteria:
    - Given 1,247 帧的 CSV 数据, When 导入完成, Then Level Sequence 包含 1,247 帧，各通道动画曲线关键帧数量正确
    - Given 用户指定 24fps, When 导入完成, Then Sequence 帧率为 24fps，总时长与 CSV 时间戳范围一致

**F6 — 验证报告**

- 统计总帧数、Timecode 范围、Focal Length 范围
- FOV 交叉校验：用写入的 Focal Length + Sensor Width 计算 FOV，与 CSV 中的 `fieldOfViewH` 对比，输出最大误差
- 检测异常帧（Position/Rotation 跳变超过阈值）
- Acceptance Criteria:
    - Given 导入完成, When 查看验证报告, Then 显示 FOV 最大误差值，异常帧列表（如有）
    - Given FOV 误差 > 0.05°, When 查看验证报告, Then 以警告形式高亮显示

**F7 — Editor Utility Widget UI**

- 提供文件选择、帧率设置、CSV 预览、一键导入、执行结果展示、快捷打开 Sequencer / MRQ 的完整 GUI
- Acceptance Criteria:
    - Given 用户打开工具面板, When 完成全部操作, Then 全程无需离开该面板（文件选择、导入、验证、跳转 Sequencer 均在面板内完成）

#### Nice-to-Have (P1)

**F8 — 错误处理与国际化**

- CSV 格式异常、字段缺失、文件损坏时给出明确错误提示，不静默失败
- UI 界面与错误提示支持中英文切换（后期合成团队可能为国际团队）

**F9 — 可配置性**

- 坐标系转换规则、Lens File 采样策略、默认资产保存路径等可在 UI 或配置文件中调整

#### Future Considerations (P2)

- **多相机支持**：单 CSV 包含多台 Camera 时自动识别并分别创建 Cine Camera Actor
- **Anamorphic 镜头支持**：自动识别 squeeze ratio 并配置 de-squeeze
- **MRQ Preset 自动配置**：根据 CSV 中的 resolution 自动创建 Movie Render Queue Preset
- **批量处理**：多个 CSV 文件（多 Slate/Take）批量导入，自动生成对应 Level Sequence
- **实拍素材自动对齐**：通过 Timecode 自动关联实拍视频素材到 Level Sequence 的 Media Track
- **Nuke 直接对接**：导出 `.nk` 脚本或 Camera FBX，使 Nuke 端 Camera 与 UE 重渲染完全一致

---

### Input Data Specification

Disguise Designer Shot Recorder 导出的 **CSV Dense** 文件，示例参考：@'/Users/bip.lan/AIWorkspace/vp/post_render_tool/reference/shot 1_take_5_dense.csv’
逐帧包含以下参数：

| CSV 字段名 | 含义 | 单位 | 示例值 |
| --- | --- | --- | --- |
| timestamp | 时间戳（HH:MM:SS.ff） | — | 00:00:30.00 |
| frame | 帧编号（Designer 内部帧计数） | — | 1790 |
| camera:cam_X.offset.x / .y / .z | 摄影机位置 | 米，Y-up | 0.0022, 0.9986, -6.0011 |
| camera:cam_X.rotation.x / .y / .z | 摄影机旋转 | 度，Y-up | 0.0008, 0.0034, -0.0002 |
| camera:cam_X.focalLengthMM | 焦距 | mm | 30.302 |
| camera:cam_X.paWidthMM | Sensor Width | mm | 35 |
| camera:cam_X.aspectRatio | 宽高比 | — | 1.77779 |
| camera:cam_X.k1k2k3.x / .y / .z | 径向畸变系数（k1, k2, k3） | 归一化 | 0.000286, -0.00395, 0.01130 |
| camera:cam_X.centerShiftMM.x / .y | 光心偏移 | mm | 0.00343, 0.00327 |
| camera:cam_X.aperture | 光圈 f-stop | — | 2.8 |
| camera:cam_X.focusDistance | 焦平面距离 | 米 | 5 |
| camera:cam_X.fieldOfViewH | 水平 FOV | 度 | 60.0145 |
| camera:cam_X.fieldOfViewV | 垂直 FOV | 度 | 35.993 |
| camera:cam_X.overscan.x / .y | 过扫描比率 | — | 1.3, 1.3 |
| camera:cam_X.overscanResolution.x / .y | 过扫描后的实际渲染分辨率 | 像素 | 2496, 1404 |
| camera:cam_X.resolution.x / .y | 基础渲染分辨率 | 像素 | 1920, 1080 |

---

### Output Artifacts

**A. UE 内资产（脚本自动生成）**

1. **Lens File** (`.ulens`) — 包含按 focal length 分组的 distortion 标定数据
2. **Cine Camera Actor** — 已配置 Filmback（Sensor Width）、已挂载 Lens Component 并关联 Lens File
3. **Level Sequence** — 包含 Cine Camera Actor 的全部动画曲线（Transform、Focal Length、Aperture、Focus Distance）

**B. 最终交付物（用户手动触发渲染后）**

EXR / PNG 序列帧，供后期合成师在 AE / Nuke 中与实拍素材合成。

---

### User Workflow

```
Step 1  打开 UE Editor → VP Post-Render Tool 面板
Step 2  点击 [浏览] 选择 CSV Dense 文件 → 自动显示预览信息
Step 3  确认/调整帧率 → 点击 [一键导入] → 等待执行完成（秒级）
Step 4  查看验证报告（FOV 误差、异常帧）
Step 5  点击 [打开 Sequencer] → 目视检查轨迹和画面
Step 6  点击 [打开 Movie Render Queue] → 配置输出格式（EXR/PNG）→ 渲染
Step 7  将渲染序列帧导入 AE / Nuke → 与实拍素材合成
```

---

### UI Wireframe

```
┌─ VP Post-Render Tool ───────────────────┐
│                                         │
│  CSV 文件:  [浏览...] shot1_take5.csv   │
│  帧率:     [自动检测 ▼]  24fps          │
│                                         │
│  ── CSV 预览 ──                          │
│  帧数: 1,247                            │
│  Focal Length: 24mm - 70mm              │
│  Timecode: 01:00:00:00 - 01:00:41:14   │
│  Sensor Width: 35mm                     │
│                                         │
│         [ 一键导入 ]                     │
│                                         │
│  ── 执行结果 ──                          │
│  ✅ Lens File 已生成                     │
│  ✅ Cine Camera Actor 已创建             │
│  ✅ Level Sequence 已创建（1,247 帧）     │
│  ✅ FOV 校验通过（误差 < 0.01°）         │
│                                         │
│         [ 打开 Sequencer ]              │
│         [ 打开 Movie Render Queue ]     │
│                                         │
└─────────────────────────────────────────┘
```

---

### Success Metrics

**Leading Indicators（上线后 1-2 周）**

- **Task Completion Rate**：≥ 95% 的用户首次使用即可独立完成 CSV → Level Sequence 全流程，无需 TD 协助
- **导入耗时**：10,000 帧以内 CSV 导入 < 60 秒
- **FOV 精度**：所有导入镜头的 FOV 交叉校验误差 < 0.05°

**Lagging Indicators（上线后 1-3 月）**

- **配置时间缩减**：单镜头重渲染准备时间从 2-4 小时降至 < 5 分钟（含目视检查）
- **TD 支持工单减少**：与 UE 重渲染配置相关的 TD 支持请求减少 ≥ 80%
- **返工率降低**：因 CG/实拍对齐失败导致的返工次数减少 ≥ 70%

---

### Prerequisites

- UE 项目需启用 **Camera Calibration** 插件（脚本启动时自动检测，未启用则弹出提示并阻止执行）
- UE 项目需启用 **Python Editor Script Plugin**
- 输入文件必须是 Designer Shot Recorder 导出的 CSV Dense 格式
- **UE 版本**：优先支持 UE 5.7，兼容 UE 5.0 - UE5.6
- **无外部依赖**：仅使用 UE 内置 Python 模块 + `unreal` API，不依赖第三方库

---

### Non-Functional Requirements

- **性能**：10,000 帧以内的 CSV 导入应在 60 秒内完成
- **错误处理**：CSV 格式异常、字段缺失、文件损坏时给出明确中文错误提示，不静默失败
- **可维护性**：坐标系转换规则集中定义，Lens File 采样策略可配置
- **可配置性**：默认资产保存路径、采样策略等可在 UI 或配置文件中调整

---

### Open Questions

| # | 问题 | 负责方 | 是否阻塞 |
| --- | --- | --- | --- |
| Q1 | Designer Shot Recorder 的 CSV Dense 格式是否有版本差异？是否需要兼容多个 Designer 版本的输出？ | Engineering | 阻塞 |
| Q2 | Lens File 的 focal length 采样策略：等间距采样 vs. 按变化率自适应采样？哪种在实际项目中精度更高？ | Engineering | 非阻塞 |
| Q3 | 坐标系转换的 Rotation 轴映射和角度方向约定是否已有经过验证的参考实现？ | Engineering | 阻塞 |
| Q5 | FOV 校验误差的可接受阈值 0.05° 是否满足实际合成精度要求？是否需要与合成师确认？ | 后期合成团队 | 非阻塞 |
| Q6 | 资产默认保存路径的命名规则？建议按 `/Content/PostRender/{CSV文件名}/` 组织，是否合适？ | Engineering / 制片 | 非阻塞 |

---

### Timeline Considerations

- **硬性依赖**：需在下一个 VP 拍摄项目的后期阶段前完成，具体日期待确认
- **技术依赖**：依赖 Camera Calibration 插件的 Python API 稳定性；若 UE 5.4 有 breaking change 需额外适配时间
- **建议分期**：
    - **Phase 1（v1 Core）**：F1-F7，覆盖单相机单 CSV 全流程，目标 2-3 周
    - **Phase 2（v1 Polish）**：F8-F9，错误处理完善 + 国际化 + 可配置性，目标 1 周
    - **Phase 3（v2）**：多相机、Anamorphic、批量处理等扩展功能