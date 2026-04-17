# VP Post-Render Tool — 代码库全景导读

> 生成日期：2026-04-17（随 Figma UI 设计落地同步更新）  
> 适用版本：commit `7aeff28` (branch `main`)  
> UI 参考：[Figma — VP Post-Render Tool · UE Panel Design](https://www.figma.com/design/H6WkczRHFmCVuPmTFahZBN/VP-Post-Render-Tool-%E2%80%94-UE-Panel-Design?node-id=1-2)  
> 阅读前提：了解基本 Python 语法；不需要了解 UE 或 C++，文中会逐一解释。

---

## Phase 1 — 项目全景

### 项目用途（一段话）

**VP Post-Render Tool** 解决的是虚拟制片（VP/XR）拍摄后的"摄影机数据回流"问题。现场拍摄时，摄影机运动数据由 Disguise Designer 软件以 "CSV Dense" 格式录制（每帧一行，包含位置、旋转、焦距、光圈等物理参数）。后期需要在 Unreal Engine 中重现完全相同的摄影机运动来渲染 CG 画面，但从 Disguise 导出到 UE 的链路没有自动化工具——手动配置每个镜头需要 2–4 小时且容易出错。这个工具将整个流程压缩为一次点击：解析 CSV → 转换坐标系 → 在 UE 内创建 LensFile + CineCameraActor + LevelSequence 动画曲线，全程自动化。

---

### 技术栈清单

| 技术 | 用途 | 为什么选它 |
|------|------|-----------|
| **Python 3** | 所有业务逻辑 | UE 内置 Python 解释器，无需额外安装 |
| **Unreal Engine 5.7 Python API** (`unreal` 模块) | 在 UE 内创建资产、操作 Level Sequence | UE 官方脚本接口，唯一选择 |
| **C++ / UHT (Unreal Header Tool)** | 声明 UI 控件绑定契约 (`BindWidget`) | Python 无法直接声明 `UPROPERTY`；C++ 是 UE 类型系统的基础 |
| **UMG (Unreal Motion Graphics)** | Editor Utility Widget UI | UE 内置 Editor UI 框架 |
| **`unittest`** | 纯 Python 单元测试 | 标准库，无依赖，可在 UE 外运行 |

---

### 目录地图

```
post_render_tool/                       ← 整个 repo 就是 UE 插件根目录
│
├── PostRenderTool.uplugin              ← [插件清单] UE 识别插件的元数据入口
│
├── Source/PostRenderTool/              ← [C++ 层] 只做一件事：声明 UI 控件绑定契约
│   ├── Public/
│   │   ├── PostRenderToolModule.h      ← 空模块入口（UE 必须有）
│   │   └── PostRenderToolWidget.h      ← 核心：41 个 UPROPERTY 声明（33 Required + 8 Optional）
│   └── Private/
│       ├── PostRenderToolModule.cpp    ← 空实现
│       └── PostRenderToolWidget.cpp    ← 空 NativeConstruct stub
│
├── Content/
│   ├── Blueprints/
│   │   └── BP_PostRenderToolWidget.uasset  ← [UMG Blueprint] UI 布局；bootstrap 一次后存进版本库，
│   │                                          后续部署只需 sync（不随 plugin 源码分发，见 §4.10）
│   └── Python/
│       ├── init_post_render_tool.py    ← [入口点] 前置检查 + 启动 UI
│       └── post_render_tool/           ← [Python 主包]
│           ├── config.py               ← 所有可调参数（坐标映射、路径、阈值）
│           ├── csv_parser.py           ← 解析 Disguise CSV Dense 格式（纯 Python）
│           ├── coordinate_transform.py ← 坐标系转换 Designer→UE（纯 Python）
│           ├── validator.py            ← FOV 校验 + 异常帧检测（纯 Python）
│           ├── lens_file_builder.py    ← 生成 UE .ulens 文件（需要 unreal）
│           ├── camera_builder.py       ← 创建 CineCameraActor（需要 unreal）
│           ├── sequence_builder.py     ← 创建 LevelSequence + 写入关键帧（需要 unreal）
│           ├── pipeline.py             ← 流水线编排（总调度，需要 unreal）
│           ├── ui_interface.py         ← UI 辅助：文件对话框、Sequencer、前置检查
│           ├── widget.py               ← 将 C++ 控件指针与 Python 回调绑定（UI 控制器）
│           ├── widget_builder.py       ← 加载 Blueprint 资产、生成 Editor 面板
│           └── tests/                  ← 纯 Python 单元测试
│
├── docs/                               ← 安装指南、BindWidget 契约参考、部署手册
├── scripts/git-hooks/                  ← post-commit 钩子（自动同步到 Perforce）
└── reference/                          ← 参考资料
```

---

### 入口点（执行如何开始）

有两条路径，都从同一个物理文件开始：

**路径 A — 带 UI 的完整工具**
```python
# 在 UE Python Console 执行
import init_post_render_tool
# → init_post_render_tool.py:69 自动调用 launch_tool()
# → launch_tool() 检查前置插件 → 打开 UI 面板
```

**路径 B — 纯命令行，跳过 UI**
```python
from post_render_tool.pipeline import run_import
result = run_import(r"C:\path\to\shot.csv", fps=24.0)
print(result.report.format_report())
```

---

### 关键架构特性（先说清楚）

**C++ 层几乎是空的，但不可省略。**

`PostRenderToolWidget.h` 里 41 个 `UPROPERTY` 声明（`:37–182`）是整个 UI 系统的"契约"——它告诉 UE 类型系统"这个 Widget 该有哪些控件、叫什么名字、是什么类型"。Blueprint (`BP_PostRenderToolWidget.uasset`) 继承这个 C++ 类；编译时 UMG 编译器自动把 Blueprint 里的控件指针赋给这些变量；Python 之后通过 `get_editor_property("btn_browse")` 拿到控件引用再绑定回调。

**三层缺一不可**：C++ 声明契约 → Blueprint 满足契约（UI 布局）→ Python 绑定行为（业务逻辑）。

**BP 的分发模式是 bootstrap-once + sync-forever。** UE 5.7 不把 `UWidgetBlueprint::WidgetTree` 暴露给 Python 反射，团队评估后放弃自动生成路径（见 commit `bd140d7`），约定：首次项目初始化由某个成员在 UMG Designer 里按 `docs/deployment-guide.md §1.3` 手工搭一次 UI，commit `.uasset` 到 git/p4；之后所有部署（同事、CI、其他机器）只需 `git pull` / `p4 sync` 取回同一份资产，**不再重新搭**。详见 §4.10。

---

## Phase 2 — UI 面板导读（Figma 设计映射）

这一节以 Figma 设计稿为起点，说明面板上每个标题、控件的业务含义、背后落到哪个 C++ UPROPERTY、被哪段 Python 消费、为什么这么设计。目标是：读完这一节后，打开 Figma 或 UE 面板，**看到任意一个控件都能说出它的名字、职责、所在文件与行号**。

### 2.1 设计来源与定位

- **文件**：`VP Post-Render Tool — UE Panel Design`
- **根节点**：`1:2`
- **URL**：<https://www.figma.com/design/H6WkczRHFmCVuPmTFahZBN/VP-Post-Render-Tool-%E2%80%94-UE-Panel-Design?node-id=1-2>

Figma **不是实现源**——整个面板的 `.uasset` 在 UMG Designer 中手工搭建，Figma 只是"外观基准 + 控件命名基准"。如果 Figma 改了字段顺序或分节，不会自动同步到 BP；反过来，BP 的控件名若偏离 Figma，只要与 `PostRenderToolWidget.h` 的 UPROPERTY 对得上就不会报错，但视觉会漂移——所以三者要保持一致。

### 2.2 面板整体结构（6 个分节）

```
┌ VP Post-Render Tool Panel ─────────────────┐
│                                            │
│  Section 1 · Prerequisites      (折叠态)   │  ← 前置插件检查（启动时自动跑）
│  Section 2 · CSV File                      │  ← 选 CSV，只读路径显示
│  Section 3 · CSV Preview                   │  ← 解析后摘要 + FPS 可覆盖输入
│  Section 4 · Coordinate Verification       │  ← 单帧坐标预览 + Spawn 真相机核对
│  Section 5 · Axis Mapping                  │  ← 改坐标映射 + 可持久化回 config.py
│  Section 6 · Actions + RESULTS             │  ← 一键 Import + 产物入口 + 日志
│                                            │
└────────────────────────────────────────────┘
```

自上而下就是用户的线性工作流：**Prereq ✓ → 选 CSV → 看摘要 → 验轴映射 → Import → 查报告**。

每个分节是一个 `#242424` 背景 + `#333` 描边的卡片容器（Figma 节点 `1:3` / `1:10` / `2:2` / `2:19` / `4:2` / `5:2`），标题左侧是 `#e8704d` 橙色竖条——这是工具的品牌色，同一橙色也用在主按钮 `Import` 与 `RESULTS` 小标题上，视觉语言上表示"可操作的焦点"。

### 2.3 命名契约（四处必须一致）

| 位置 | 文件 | 举例 |
|---|---|---|
| Figma `data-node-id` 的 `name` | Figma 设计稿 | `btn_browse`（Figma 节点 `1:15`） |
| C++ UPROPERTY 名 | `Source/PostRenderTool/Public/PostRenderToolWidget.h` | `UButton* btn_browse;` |
| Python 控件名字符串 | `widget.py:44-67` 的 `_REQUIRED_CONTROLS` / `_OPTIONAL_CONTROLS` | `"btn_browse"` |
| Designer 中 BP 的 Widget 名 | `Content/Blueprints/BP_PostRenderToolWidget.uasset` | UMG Hierarchy 面板里叫 `btn_browse` |

**四者必须字符串级一致**。UMG 编译器只检查 C++↔BP 两端（`meta=(BindWidget)` 会硬报错）；Python 端拼写错只会让 `host.get_editor_property("...")` 返回 `None`，然后 `widget.py` 打一条 warning 继续跑——**这是沉默 bug，只有运行时点按钮才发现**。详见 `CLAUDE.md > Gotchas > Python-vs-Designer name drift`。

---

### 2.4 Section 1 — Prerequisites（前置插件检查）

Figma 节点 `1:3`（容器）、`1:4` / `1:5` / `1:8` / `1:9`（头部）。

**视觉形态**：折叠标题行，左侧 ▶ 表示可展开，右侧 `6 / 6 OK` 用 `#4caf50` 绿色显示统计。展开后列出 6 条状态行 + 一个 Re-check 按钮（Figma mock 是折叠态所以展开区未绘出，但 UPROPERTY 中已预留槽位）。

**控件清单**：

| Figma 节点 | C++ UPROPERTY | 类型 | Python 句柄 | 功能 |
|---|---|---|---|---|
| `1:9`（summary 数字） | `prereq_summary` *(Optional)* | `UTextBlock` | `widget.py:253` `_check_and_display_prereqs` 写入 `"<ok>/<total> OK"` | 通过数/总数概览 |
| 展开区每一行 | `prereq_label_0` … `prereq_label_5` *(Optional)* | `UTextBlock` | 同上，文本形如 `OK: Camera Calibration` 或 `MISSING: xxx → <修复提示>` | 每个前置项的状态 |
| Re-check 按钮 | `btn_recheck` | `UButton` | `widget.py:258` `_on_recheck_prereqs` | 重新探测并刷新所有标签 |

**功能逻辑**：`ui_interface.py:188-221` 定义 6 个探测目标，逐项调用 `hasattr(unreal, "<ClassName>")`：

1. `Python Editor Script Plugin` — 恒为 OK（能跑此段代码 ≡ 插件已加载）
2. `Editor Scripting Utilities` — 探测 `EditorAssetLibrary`
3. `Camera Calibration` — 探测 `LensFile`（不用 `PluginBlueprintLibrary.is_plugin_loaded()`，因其在某些 UE 版本不工作，见 `CLAUDE.md > Gotchas`）
4. `CineCameraActor` — 探测同名类
5. `LevelSequence` — 探测同名类
6. `EditorUtilitySubsystem` — 探测同名类

每项返回 `(name, ok, fix_hint)`；UI 层把 `fix_hint` 直接拼到 `MISSING:` 行尾，让用户原地看见修复路径（例如 `Edit > Plugins > search 'Camera Calibration' > Enable > Restart`）。

**设计原理**：插件缺失是 Import 失败最常见的根因（`hasattr` 为 `False` 后续流水线会在创建 `LensFile` 时崩）。把它放面板首行 + 启动时自动跑 + 提供 Re-check 按钮，相当于一个**"环境健康仪表盘"**，让用户不必等 Import 报错才回头找原因。

---

### 2.5 Section 2 — CSV File（输入选择）

Figma 节点 `1:10`（容器）、`1:14`（行）、`1:15`（按钮）、`1:17`（路径显示）。

**控件清单**：

| Figma 节点 | C++ UPROPERTY | 类型 | Python 句柄 | 功能 |
|---|---|---|---|---|
| `1:15` | `btn_browse` | `UButton` | `widget.py:266` `_on_browse_clicked` | 打开文件选择对话框 |
| `1:17` | `txt_file_path` | `UTextBlock` | `widget.py:273` `_set_text("txt_file_path", ...)` | 显示选中的绝对路径（只读） |

**功能逻辑**：

1. 点击 Browse → `ui_interface.py:30` `browse_csv_file()`
2. 按优先级走**三段降级**：
   - `unreal.DesktopPlatformBlueprintLibrary.open_file_dialog`（UE 5.7 里常不可用）
   - macOS：`osascript -e 'choose file ...'`（`_browse_via_osascript`）
   - 跨平台兜底：`tkinter.filedialog.askopenfilename`（`_browse_via_tkinter`）
3. 返回路径 → 写 `txt_file_path` → 立即同步调用 `parse_csv_dense` 填充 Section 3 全部字段

**设计原理**：UE 5.7 Python 环境没有开箱即用的原生文件对话框绑定；VP 现场常跨 Mac（剪辑台）与 Windows（Editor 机），因此需要"哪个平台都能弹框"。三段降级代码路径写死在 `ui_interface.py`，不依赖 `pip install` 任何外部包，部署零摩擦。

---

### 2.6 Section 3 — CSV Preview（摘要与帧率覆盖）

Figma 节点 `2:2`。展开后分两块：纯文本 stats（`2:6`）+ FPS 输入行（`2:11`）。

**控件清单**：

| Figma 节点 | C++ UPROPERTY | 类型 | Python 句柄 | 填充内容 |
|---|---|---|---|---|
| `2:7` `Frames: 974` | `txt_frame_count` | `UTextBlock` | `widget.py:290` | `f"Frames: {result.frame_count}"` |
| `2:8` `Focal Length: 30.30 – 30.30 mm` | `txt_focal_range` | `UTextBlock` | `widget.py:293` | `f"Focal Length: {min:.2f} – {max:.2f} mm"` |
| `2:9` `Timecode: 00:00:30.00 → 00:00:30.00` | `txt_timecode` | `UTextBlock` | `widget.py:297` | `f"Timecode: {start} → {end}"` |
| `2:10` `Sensor Width: 35.00 mm` | `txt_sensor_width` | `UTextBlock` | `widget.py:301` | `f"Sensor Width: {sensor_width_mm:.2f} mm"` |
| `2:13` `FPS SpinBox` | `spn_fps` | `USpinBox` | `widget.py:317` `_on_fps_changed`（委托 `on_value_changed`） | 用户覆盖 FPS；`0.0` 表示沿用自动检测 |
| `2:18` `Auto: 23.976 fps` | `txt_detected_fps` | `UTextBlock` | `widget.py:304` | 显示 `csv_parser._detect_fps()` 的估算值 |

**功能逻辑**：

- Preview 数据**在 Browse 回调里同步填充**——`parse_csv_dense()` 一次返回后 6 个字段一并更新。
- FPS SpinBox 默认值 `0.0`（`widget.py:172`），语义是"让 pipeline 自己选"。`widget.py:508` `fps = self._fps if self._fps > 0 else 0.0`，传 `0.0` 给 `pipeline.run_import` 时会回退到 `csv_result.detected_fps`。
- 用户可手动输入 `24.0` / `29.97` 等覆盖，适用于 CSV 时间戳抖动超过 10%、`_detect_fps()` 返回 `None` 的场景。

**设计原理**：Preview 把所有与摄影机"物理参数"有关的基础数据摊在桌面上，让用户按 Import 之前就能肉眼校验："焦距范围对不对？时间码长度对不对？传感器 35mm/60mm 有没有预设错？"——这些错带到 LensFile 就得整条流水线重跑。`txt_detected_fps` 与 `spn_fps` 并列，是**"机器估算值 + 人工可覆盖值"**的典型"信任但可超越"（trust-but-override）模式。

---

### 2.7 Section 4 — Coordinate Verification（坐标系验证）

Figma 节点 `2:19`。**整个工具最关键的交互区**——`config.py` 的默认映射是"初始猜测"（`config.py:4-7` 明确标注 *"These are INITIAL GUESSES"*），必须由人拿真机数据验证。

**控件清单**：

| Figma 节点 | C++ UPROPERTY | 类型 | Python 句柄 | 功能 |
|---|---|---|---|---|
| `2:25` `spn_frame` | `spn_frame` | `USpinBox` | `widget.py:364` `_on_frame_changed` → `_refresh_coord_preview` | 选要预览的帧（0 … frame_count-1） |
| `2:30` `0 / 973` | `txt_frame_hint` *(Optional)* | `UTextBlock` | `widget.py:360` | "当前/总帧数"提示，防用户忘了上限 |
| `2:33` `Pos (x, y, z) m` | `txt_designer_pos` | `UTextBlock` | `widget.py:336` | CSV 原始位置（Designer 系，米） |
| `2:34` `Rot (rx, ry, rz)°` | `txt_designer_rot` | `UTextBlock` | `widget.py:342` | CSV 原始旋转（度） |
| `2:37` `Pos (x, y, z) cm` | `txt_ue_pos` | `UTextBlock` | `widget.py:351` | 经 `transform_position` 转换的 UE 结果 |
| `2:38` `Rot P=.. Y=.. R=..°` | `txt_ue_rot` | `UTextBlock` | `widget.py:355` | 经 `transform_rotation` 转换的 UE 结果 |
| `2:39` `btn_spawn_cam` | `btn_spawn_cam` | `UButton` | `widget.py:367` `_on_spawn_test_camera` | 按当前帧参数 Spawn 一个 `CineCameraActor` 并把 viewport pilot 到它 |

> Figma 里的 `DESIGNER (source)`（`2:32`）与 `→ UE (result)`（`2:36`）橙色小标签是**静态文本**，不参与 BindWidget 契约——BP 里直接用普通 `UTextBlock` 贴上去即可。

**功能逻辑**：

- `spn_frame` 值变化 → `_refresh_coord_preview()` 重算并刷新 Designer / UE 共 4 个文本字段。轴映射改变（Section 5 的 Apply）时 UE 侧也会自动跟上。
- 点 `Spawn Test Camera` → `ui_interface.py:232` `spawn_test_camera()`：
  1. 在 `Vector(ue_x, ue_y, ue_z)` + `Rotator(pitch, yaw, roll)` 处 `spawn_actor_from_class(CineCameraActor, ...)`
  2. 给新 actor 加 Tag `PostRenderTool_TestCam`（按 Tag 而非 label 识别，免得误删用户同名相机）
  3. 配置 Filmback `sensor_width` 为 CSV 中读到的值
  4. 销毁之前的测试相机（如果存在）
  5. `pilot_level_actor()` 让 viewport 从这台相机视角观察
- 闭环验证流：调 Section 5 的轴映射 → 看 Section 4 数字变化 → Spawn → 在 UE viewport 里对齐"现场拍摄位置"。

**设计原理**：这是工具中**唯一不能自动化的验证步骤**。`POSITION_MAPPING = {"x": (2, -100.0), ...}` 是从"Designer Y-up 米 → UE Z-up 厘米"理论推导得出，但 Disguise 导出坐标经常受 stage 校准偏移、导演镜像需求等影响偏 180°。把"单帧预览 + Spawn 真相机"摆在一起，就是**用 UE viewport 作为坐标系的真值表**，避免让用户在脑子里做矩阵乘法。

---

### 2.8 Section 5 — Axis Mapping（轴映射编辑器）

Figma 节点 `4:2`。分 `POSITION`（`4:6` 标题下 3 行）与 `ROTATION`（`4:44` 标题下 3 行）两个子组，末尾 `Apply Mapping` + `Save to config.py` 两按钮。

**每一行的结构**（以 `UE.X` 为例，Figma `4:8`）：
```
UE.X   ←   [cmb: X (0) / Y (1) / Z (2) ▾]   ×   [spn: -100.0 ▲▼]
```

- `UE.X` 是静态文字 label
- `←` / `×` 字符是视觉装饰（不是控件）
- `▾` / `▲▼` 是 Figma mock 绘制的下拉/步进箭头，**不要在 BP 里手画**——`UComboBoxString` 与 `USpinBox` 会自己渲染

**控件清单**：

| Figma 节点 | C++ UPROPERTY | 类型 | 初值来源 |
|---|---|---|---|
| `4:11` / `4:15` | `cmb_pos_x_src` / `spn_pos_x_scale` | `UComboBoxString` / `USpinBox` | `config.POSITION_MAPPING["x"] = (2, -100.0)` |
| `4:23` / `4:27` | `cmb_pos_y_src` / `spn_pos_y_scale` | 同上 | `config.POSITION_MAPPING["y"] = (0, 100.0)` |
| `4:35` / `4:39` | `cmb_pos_z_src` / `spn_pos_z_scale` | 同上 | `config.POSITION_MAPPING["z"] = (1, 100.0)` |
| `4:49` / `4:53` | `cmb_rot_pitch_src` / `spn_rot_pitch_scale` | 同上 | `config.ROTATION_MAPPING["pitch"] = (0, -1.0)` |
| `4:61` / `4:65` | `cmb_rot_yaw_src` / `spn_rot_yaw_scale` | 同上 | `config.ROTATION_MAPPING["yaw"] = (1, -1.0)` |
| `4:73` / `4:77` | `cmb_rot_roll_src` / `spn_rot_roll_scale` | 同上 | `config.ROTATION_MAPPING["roll"] = (2, 1.0)` |
| `4:83` | `btn_apply_mapping` | `UButton` | — |
| `4:85` | `btn_save_mapping` | `UButton` | — |

ComboBox 的三个选项（由 `widget.py:37` 硬编码）：`X (0)` / `Y (1)` / `Z (2)`。字符串经 `_AXIS_INDEX_MAP`（`widget.py:38`）反查回 `0/1/2` 索引。

**Python 流向**：

- 打开面板时，`widget.py:146` `_push_initial_mapping_values()` 从 `config.POSITION_MAPPING` / `ROTATION_MAPPING` 回填 UI，无需热重载，首次打开即显示磁盘上的真实值。
- 点 `Apply Mapping` → `widget.py:458` `_on_apply_mapping`：读 UI → **直接覆盖** `config.POSITION_MAPPING` / `ROTATION_MAPPING` 内存字典 → 刷新 Section 4 预览。**不写磁盘**。
- 点 `Save to config.py` → `widget.py:480` `_on_save_mapping` → `ui_interface.py:295` `save_axis_mapping`：走完整的原子写入流程（见下）→ `importlib.reload(config)`（`ui_interface.py:405`）。

**为什么 Apply 不需要热重载？**

`coordinate_transform._default_cfg()`（`coordinate_transform.py:35`）每次调用都**从 `config` 模块重新读**两个字典，而不是在模块加载时缓存。`_on_apply_mapping` 直接用新字典替换 `config.POSITION_MAPPING`，下一次 `transform_position()` 调用自然看到新值。这是 Python 模块级变量 + 延迟绑定的惯用法。

**Save 的原子写入流程**（`ui_interface.py:295-406`）：

1. 读 `config.py` 源码
2. 用正则替换 `POSITION_MAPPING = {...}` 与 `ROTATION_MAPPING = {...}` 两个代码块
3. `ast.parse()` 语法验证（若非法就抛 `RuntimeError`，**绝不写磁盘**）
4. `tempfile.mkstemp()` 写临时文件
5. `shutil.copy2(config_path, config_path + ".bak")` 备份原文件
6. `os.replace(tmp, config_path)` 原子替换（POSIX 等价于 `mv`，进程崩溃不会留半写文件）
7. `importlib.reload(config)` 让内存与磁盘同步

**防御性检查**（`widget.py:417-430` `_missing_mapping_controls`）：如果 Designer 在 BP 里漏掉某个 combo/spinbox，日志警告并**拒绝**执行 Apply/Save——否则 SpinBox 读不到就默认 `0.0`，会把 scale 归零，静默破坏坐标变换。

**设计原理**：轴映射的本质是 6 组 `(source_axis_index, scale_factor)` 元组，可表达绝大多数"右手/左手系 + 单位换算 + 方向翻转"。用 `ComboBox × SpinBox` 暴露给用户，比让他们手编 `config.py` 字典对现场 TD 更友好。`Apply`（内存沙盒）与 `Save`（固化到源码）是**双层承诺模型**——用户可反复拨动、配合 Section 4 的 Spawn Test Camera 直到对上，再一键固化，避免"改了忘存"。

---

### 2.9 Section 6 — Actions + RESULTS（执行与日志）

Figma 节点 `5:2`。

**控件清单**：

| Figma 节点 | C++ UPROPERTY | 类型 | Python 句柄 | 功能 |
|---|---|---|---|---|
| `5:6` / `5:7` **橙色主按钮** | `btn_import` | `UButton` | `widget.py:501` `_on_import_clicked` → `pipeline.run_import` | 触发完整 5-step 流水线，结果写 `txt_results` |
| `5:9` | `btn_open_seq` | `UButton` | `widget.py:530` `_on_open_sequencer_clicked` → `ui_interface.py:144` `open_sequencer` | 打开本次 Import 产出的 LevelSequence（依赖 `self._last_result.level_sequence`）|
| `5:11` | `btn_open_mrq` | `UButton` | `widget.py:536` `_on_open_mrq_clicked` → `ui_interface.py:166` `open_movie_render_queue` | 打开 Movie Render Queue 编辑器窗口 |
| `5:13` `RESULTS` | — | 纯文本 | — | 橙色小标题，视觉分隔 |
| `5:14` 多行文本区 | `txt_results` | `UMultiLineEditableText` | `widget.py:543` `_set_results` | 多行滚动日志，显示 `ValidationReport.format_report()` 或错误信息 |

**功能逻辑**：

- Import 在主线程同步执行，UI 会短暂阻塞（1200 帧 CSV 约 3–5 秒），但对话框不会卡死——`run_import` 返回 `PipelineResult` 而不抛异常，所有错误都以 `result.success=False` + `error_message` 形式回传。
- `Open Sequencer` 需要先跑过 Import（它读 `self._last_result`）；没跑则提示 `"No LevelSequence available. Run Import first."`
- `Open MRQ` 不依赖流水线状态，任何时候都能开；MRQ 打开后用户自行添加 Sequence 任务并配置输出分辨率/格式。
- `txt_results` 用 `UMultiLineEditableText`（不是 `UTextBlock`），这样超出可视区会滚动；Figma 里 `height=144px` 对应约 12 行等宽字体。

**设计原理**：

- **`Import` 是面板唯一的橙色主按钮**（`#e8704d` 背景 + 白字 + 加粗加大，Figma `5:6`）。UI 设计中只给一个主操作上高亮色是 Fitts-Law 常规做法，避免用户把次要动作当成主动作。
- **`Open Sequencer` / `Open MRQ` 灰色次按钮并排**（`flex: 1` 均分宽度）表示它们是"Import 之后的后续入口"，视觉上被压在主按钮下方、字号更小。
- **RESULTS 用 `Roboto Mono` 等宽字体**（Figma `5:14`）+ 深灰背景 `#141414` + 浅灰文字 `#a8a8a8`——经典的"日志面板"视觉语法。BP 里 `txt_results` 的 Font Family 请选 Monospace。

---

### 2.10 Figma 里有但契约里没有的元素（装饰 vs 绑定）

设计稿里不少静态文本 / 装饰节点**不进入 BindWidget 契约**，BP 里作为普通 `UTextBlock` 硬编码即可，不需要取名：

- 橙色竖条（Rectangle 节点 `1:7` / `1:12` / `2:4` / `2:21` / `4:4` / `5:4`）——纯视觉分隔条
- Section 的标题文字（`Prerequisites` / `CSV File` / `CSV Preview` / `Coordinate Verification` / `Axis Mapping` / `Actions`）——静态 Label
- `POSITION (m → cm)` / `ROTATION (deg)` / `RESULTS` 子标题（`4:6` / `4:44` / `5:13`）——静态分组 Label
- `DESIGNER (source)` / `→ UE (result)` 标签（`2:32` / `2:36`）——静态说明文字
- `UE.X` / `UE.Y` / `UE.Z` / `Pitch` / `Yaw` / `Roll` 行首 Label——静态 Label
- `FPS` / `Frame` 前置 Label（`2:12` / `2:24`）——静态 Label
- `←` / `×` / `▾` / `▲▼` 字符——UMG 会由 `UComboBoxString` / `USpinBox` 自行渲染步进与下拉箭头；Figma 使用这些字符是因为 Figma 里没有等价 primitive，BP 里**不要手写**

**统一原则**：任何"不需要 Python 读或写的文字"都不要出现在 `_REQUIRED_CONTROLS` 里。控件数量保持 **33 Required + 8 Optional = 41**，与 `PostRenderToolWidget.h` 严格一致。

---

### 2.11 41 个 UPROPERTY 速查表（按 Figma 分节）

| Section | BindWidget 控件 | 类型 | Required? |
|---|---|---|---|
| 1 · Prerequisites | `prereq_label_0` … `prereq_label_5` | `UTextBlock` | Optional |
| 1 · Prerequisites | `prereq_summary` | `UTextBlock` | Optional |
| 1 · Prerequisites | `btn_recheck` | `UButton` | ✓ Required |
| 2 · CSV File | `btn_browse` | `UButton` | ✓ Required |
| 2 · CSV File | `txt_file_path` | `UTextBlock` | ✓ Required |
| 3 · CSV Preview | `txt_frame_count` | `UTextBlock` | ✓ Required |
| 3 · CSV Preview | `txt_focal_range` | `UTextBlock` | ✓ Required |
| 3 · CSV Preview | `txt_timecode` | `UTextBlock` | ✓ Required |
| 3 · CSV Preview | `txt_sensor_width` | `UTextBlock` | ✓ Required |
| 3 · CSV Preview | `spn_fps` | `USpinBox` | ✓ Required |
| 3 · CSV Preview | `txt_detected_fps` | `UTextBlock` | ✓ Required |
| 4 · Coord Verification | `spn_frame` | `USpinBox` | ✓ Required |
| 4 · Coord Verification | `txt_frame_hint` | `UTextBlock` | Optional |
| 4 · Coord Verification | `txt_designer_pos` | `UTextBlock` | ✓ Required |
| 4 · Coord Verification | `txt_designer_rot` | `UTextBlock` | ✓ Required |
| 4 · Coord Verification | `txt_ue_pos` | `UTextBlock` | ✓ Required |
| 4 · Coord Verification | `txt_ue_rot` | `UTextBlock` | ✓ Required |
| 4 · Coord Verification | `btn_spawn_cam` | `UButton` | ✓ Required |
| 5 · Axis Mapping | `cmb_pos_x_src` / `spn_pos_x_scale` | `UComboBoxString` / `USpinBox` | ✓ Required |
| 5 · Axis Mapping | `cmb_pos_y_src` / `spn_pos_y_scale` | 同上 | ✓ Required |
| 5 · Axis Mapping | `cmb_pos_z_src` / `spn_pos_z_scale` | 同上 | ✓ Required |
| 5 · Axis Mapping | `cmb_rot_pitch_src` / `spn_rot_pitch_scale` | 同上 | ✓ Required |
| 5 · Axis Mapping | `cmb_rot_yaw_src` / `spn_rot_yaw_scale` | 同上 | ✓ Required |
| 5 · Axis Mapping | `cmb_rot_roll_src` / `spn_rot_roll_scale` | 同上 | ✓ Required |
| 5 · Axis Mapping | `btn_apply_mapping` | `UButton` | ✓ Required |
| 5 · Axis Mapping | `btn_save_mapping` | `UButton` | ✓ Required |
| 6 · Actions | `btn_import` | `UButton` | ✓ Required |
| 6 · Actions | `btn_open_seq` | `UButton` | ✓ Required |
| 6 · Actions | `btn_open_mrq` | `UButton` | ✓ Required |
| 6 · Actions | `txt_results` | `UMultiLineEditableText` | ✓ Required |

合计 **33 Required + 8 Optional = 41**。这张表与 `docs/bindwidget-contract.md` 冗余但本文档独立可读，两者必须同步更新。

---

## Phase 3 — 架构与数据流

### 核心架构模式：分层流水线（Layered Pipeline）

整体是一条单向数据流水线，外层用一个 UI 层触发，但流水线本身与 UI 完全解耦。

### 组件职责图

```
┌──────────────────────────────────────────────────────────────┐
│                       UE Editor 进程                          │
│                                                              │
│  ┌─────────────────┐                                         │
│  │ init_post_render│  入口点：前置检查 + 触发 widget_builder   │
│  └────────┬────────┘                                         │
│           │                                                  │
│  ┌────────▼──────────────────────────────────────────────┐   │
│  │              UI 层（可选）                              │   │
│  │  widget_builder.py  ←  加载 Blueprint, 生成 Editor Tab │   │
│  │  widget.py          ←  绑定 41 个控件引用 + 事件回调    │   │
│  │  ui_interface.py    ←  文件对话框 / 前置检查 / 测试相机  │   │
│  └────────┬──────────────────────────────────────────────┘   │
│           │ 用户点击 Import                                   │
│           ▼                                                  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              pipeline.py (run_import)                  │  │
│  │                                                        │  │
│  │  Step 1  csv_parser.py   ← 解析 CSV → CsvDenseResult   │  │
│  │  Step 2  lens_file_builder.py ← 生成 .ulens 资产        │  │
│  │  Step 3  camera_builder.py   ← Spawn CineCameraActor   │  │
│  │  Step 4  sequence_builder.py ← 创建 LevelSequence       │  │
│  │  Step 5  validator.py        ← 生成验证报告              │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────┐  ┌──────────────────┐                   │
│  │  coordinate_   │  │    config.py      │                   │
│  │  transform.py  │  │  （全局配置/常量） │                   │
│  │（纯 Python,     │  └──────────────────┘                   │
│  │ 无 unreal 依赖）│                                         │
│  └────────────────┘                                         │
└──────────────────────────────────────────────────────────────┘

外部输入：
  CSV Dense file（Disguise Designer 导出）

最终输出（UE Content Browser）：
  /Game/PostRender/<shot_name>/
    ├── LF_<shot_name>.ulens          ← LensFile 资产
    ├── LS_<shot_name>                ← LevelSequence 资产
    └── CineCamera_<shot_name>        ← 关卡中的 Actor（非资产文件）
```

### 数据流（从 CSV 到 UE 资产）

```
Disguise CSV Dense file
        │
        ▼
csv_parser.parse_csv_dense()
        │  输出：CsvDenseResult
        │    .frames          [FrameData, ...]  ← 每帧一条
        │    .sensor_width_mm
        │    .focal_length_range
        │    .detected_fps
        │
        ├──────────────────────────────────────────┐
        │                                          │
        ▼                                          ▼
lens_file_builder                        coordinate_transform
按焦距分组 → 计算归一化畸变参数               Designer(m, Y-up)
→ 写入 UE LensFile 资产                    → UE(cm, Z-up)
                                           transform_position / _rotation
        │                                          │
        ▼                                          ▼
camera_builder                          sequence_builder
Spawn CineCameraActor                   创建 LevelSequence
设置 Filmback sensor_width              对每一帧写入关键帧：
挂载 LensComponent                        位置 / 旋转 / 焦距 / 光圈 / 焦距
关联 LensFile                             
        │
        └──────────────────────────────────┐
                                           ▼
                                       validator
                              FOV 交叉校验 + 位移/旋转跳变检测
                              生成 ValidationReport
```

### 模块依赖关系（叶节点 → 编排节点）

```
config.py                        ← 无依赖（纯常量）
csv_parser.py     ← config
coordinate_transform.py ← config
validator.py      ← config, csv_parser
lens_file_builder.py ← config, csv_parser          [requires unreal]
camera_builder.py    ← (无 Python 包内依赖)         [requires unreal]
sequence_builder.py  ← coordinate_transform, csv_parser [requires unreal]
pipeline.py          ← 以上全部                     [requires unreal]
ui_interface.py      ← config                      [requires unreal]
widget.py            ← config, coordinate_transform, csv_parser,
                        pipeline, ui_interface      [requires unreal]
widget_builder.py    ← widget                      [requires unreal]
init_post_render_tool.py ← ui_interface, widget_builder [requires unreal]
```

---

## Phase 4 — 模块精读（依赖顺序，叶节点优先）

### 4.1 `config.py` — 全局配置中心

**结论：** 这是全项目唯一的配置文件，所有可调参数集中在这里，其他模块都通过 `from . import config` 读取。修改这里等于修改全局行为，无需重启 UE（用 `importlib.reload(config)` 即可热重载）。

**内容分解：**

```python
# config.py:9-14
POSITION_MAPPING = {
    "x": (2, -100.0),  # UE.X ← -Designer.Z × 100
    "y": (0,  100.0),  # UE.Y ←  Designer.X × 100
    "z": (1,  100.0),  # UE.Z ←  Designer.Y × 100
}
```

每个条目是 `(source_axis_index, scale_factor)` 的元组：
- `source_axis_index`：从 Designer 的 `(x=0, y=1, z=2)` 中选哪个轴
- `scale_factor`：含单位转换（m→cm 乘 100）和方向翻转（负号）

> **⚠️ 注意：** 注释写明这些是"初始猜测"，必须用真实数据在 UE 视口中验证（对应 Phase 2 · Section 4 的工作流）。

其他参数：
- `ASSET_BASE_PATH = "/Game/PostRender"` — 所有生成资产的保存根路径（`:24`）
- `FOCAL_LENGTH_GROUP_TOLERANCE_MM = 0.1` — LensFile 焦距分组容差（`:29`）
- `FOV_ERROR_THRESHOLD_DEG = 0.05` — FOV 校验警告阈值（`:32`）
- `REQUIRED_SUFFIXES / OPTIONAL_SUFFIXES` — CSV 列名后缀白名单（`:37-52`）

---

### 4.2 `csv_parser.py` — CSV Dense 解析器（纯 Python）

**结论：** 读取 Disguise Designer 导出的 CSV 文件，自动识别摄影机前缀，对每一行提取物理参数，聚合为 `CsvDenseResult`，并估算帧率。完全不依赖 UE，可在本机直接测试。

**数据结构：**

```python
# csv_parser.py:29-51
@dataclass
class FrameData:          # 一帧的所有参数
    timestamp: str
    frame_number: int
    offset_x/y/z: float   # 位置（米）
    rotation_x/y/z: float # 旋转（度）
    focal_length_mm: float
    sensor_width_mm: float # paWidthMM
    aspect_ratio: float
    aperture: float
    focus_distance: float
    k1, k2, k3: float     # 径向畸变系数
    center_shift_x/y_mm: float
    fov_h: float
    fov_v: Optional[float]
    resolution_x/y: Optional[int]

@dataclass
class CsvDenseResult:     # 整个 CSV 的聚合结果
    file_path: str
    camera_prefix: str    # 例如 "camera:cam01"
    frames: List[FrameData]
    frame_count: int
    timecode_start/end: str
    focal_length_range: Tuple[float, float]
    sensor_width_mm: float
    detected_fps: Optional[float]
```

**关键逻辑：相机前缀自动识别（`:77-86`）**

```python
def _detect_camera_prefix(headers):
    pattern = re.compile(r"^(camera:\w+)\.offset\.x$")
    for h in headers:
        m = pattern.match(h)
        if m:
            return m.group(1)   # 返回 "camera:cam01" 这样的字符串
```

原理：Disguise CSV 的每列命名为 `camera:<name>.<field>`，通过正则找到 `offset.x` 列就能确定完整前缀。这样工具不需要用户手动告知相机叫什么名字。

**关键逻辑：帧率自动检测（`:117-163`）**

```python
def _detect_fps(timestamps):
    deltas = [t[i+1] - t[i] for i in range(len(t)-1)]  # 相邻帧时间差
    nonzero = [d for d in deltas if d > 0]              # 去掉重复帧
    mean_delta = statistics.mean(nonzero)               # 平均帧间隔
    if stdev / mean_delta >= 0.10:                      # 超过 10% 不稳定 → 放弃
        return None
    raw_fps = 1.0 / mean_delta                          # 1 ÷ 平均帧间隔
    # 对齐到最近的标准帧率（23.976/24/25/29.97/30/...）
    best = min(_COMMON_FPS, key=..., filter=within 5%)
```

设计亮点：标准帧率列表（`:74`）覆盖了广播和电影常用帧率；5% 容差处理轻微时钟漂移；超过 10% 波动则返回 None 而不是乱猜。

**公共 API：`parse_csv_dense(file_path)`（`:188-273`）**

唯一的对外接口。流程：`open(file)` → `DictReader` → 检测前缀 → 校验列名 → 逐行解析 → 聚合统计 → 返回 `CsvDenseResult`。

> **技术原理 — `@dataclass`：**  
> `@dataclass` 是 Python 3.7+ 的装饰器，自动生成 `__init__`、`__repr__`、`__eq__` 方法，省去手写样板代码。`field(default_factory=list)` 用于可变默认值（避免所有实例共享同一个 list 的陷阱）。

---

### 4.3 `coordinate_transform.py` — 坐标系转换（纯 Python）

**结论：** 将 Disguise Designer 的 Y-up 坐标系（米）映射到 UE 的 Z-up 坐标系（厘米），轴映射规则来自 `config.py`，可从 UI 实时修改。

**核心数据结构：**

```python
# coordinate_transform.py:11-27
@dataclass
class TransformConfig:
    pos_x: Tuple[int, float]   # (source_axis_index, scale)
    pos_y: Tuple[int, float]
    pos_z: Tuple[int, float]
    rot_pitch: Tuple[int, float]
    rot_yaw: Tuple[int, float]
    rot_roll: Tuple[int, float]
    # __post_init__ 验证每个字段都是 2-tuple
```

**变换函数（`:35-78`）：**

```python
def transform_position(designer_x, designer_y, designer_z, cfg=None):
    src = (designer_x, designer_y, designer_z)
    def apply(rule):
        idx, scale = rule
        return src[idx] * scale          # 取指定轴 × 缩放系数
    return (apply(cfg.pos_x), apply(cfg.pos_y), apply(cfg.pos_z))
```

极简的设计：整个变换逻辑只有 3 行实质代码。`idx` 决定"取 Designer 的哪个轴"，`scale` 决定"乘什么系数"（包含方向翻转和 m→cm 的 ×100）。

**`cfg=None` 的惯用法（`:39,63`）：**  
参数默认为 `None`，函数内部 `if cfg is None: cfg = _default_cfg()` 从 `config` 模块读取当前配置。这样调用者可以传入自定义配置覆盖默认值（测试时很有用），也可以不传（直接用全局配置）。**这就是为什么 Phase 2 · Section 5 的 `Apply Mapping` 只改 `config` 字典就能立刻生效——`_default_cfg` 每次都去 `config` 读，没有缓存。**

> **技术原理 — 为什么不直接用默认参数 `cfg=TransformConfig()`：**  
> Python 的函数默认参数在模块加载时只求值一次。如果写 `def f(cfg=TransformConfig())`，那个 `TransformConfig` 实例在程序启动时就固定了，之后修改 `config.POSITION_MAPPING` 不会影响它。用 `cfg=None` + 函数体内延迟创建，则每次调用都能看到最新的 `config` 值。

---

### 4.4 `validator.py` — FOV 校验 + 异常帧检测（纯 Python）

**结论：** 对解析后的帧数据做两种质检：① 用物理公式重新计算 FOV，与 CSV 中记录的 `fov_h` 对比，检测数据异常；② 检测相邻帧的位移/旋转跳变，发现数据录制中断或抖动。

**FOV 校验（`:15-69`）：**

```python
def compute_fov_h(focal_length_mm, sensor_width_mm):
    # FOV = 2 × arctan(sensor_width / (2 × focal_length))
    return math.degrees(2.0 * math.atan(sensor_width_mm / (2.0 * focal_length_mm)))
```

这是相机光学的标准公式，不依赖 CSV 中的任何数据——纯数学推导。用它重新算出的 FOV 与 CSV 里的 `fov_h` 字段对比，差值 > `FOV_ERROR_THRESHOLD_DEG`（默认 0.05°）则发出警告。这是一个内部一致性检查：如果 Disguise 记录的 `fov_h` 与 `focalLengthMM` + `paWidthMM` 的组合不一致，说明数据可能有问题。

**异常帧检测（`:76-143`）：**

```python
for i in range(1, len(frames)):
    pos_dist = sqrt(dx² + dy² + dz²)   # 欧氏距离（米）
    max_rot_delta = max(|drx|, |dry|, |drz|)  # 最大单轴旋转差
```

逐帧计算与前一帧的位移距离和旋转变化，超阈值则记录。用欧氏距离（三维空间直线距离）而不是单轴最大值，是因为摄影机可以沿斜方向快速移动。

**`ValidationReport.format_report()`（`:163-205`）：**

将数字结果格式化为中文文本报告，带 ✓/⚠ 符号，直接显示在 UI 的 `txt_results` 文本框里（即 Phase 2 · Section 6 的 RESULTS 区域）。

---

### 4.5 `lens_file_builder.py` — LensFile 资产生成（需要 UE）

**结论：** 将 CSV 中的畸变标定数据（`k1k2k3`、`centerShiftMM`、`focalLengthMM`）转换为 UE Camera Calibration 插件的 `.ulens` 资产格式，按焦距分组写入畸变点。

**畸变参数归一化（`:25-59`）：**

```python
def _compute_normalized_distortion(frame_data):
    fx = focal_mm / pa_width           # 归一化焦距 x
    fy = fx * aspect                   # 归一化焦距 y（考虑宽高比）
    cx = 0.5 + center_shift_x / pa_width    # 主点偏移（0.5=正中心）
    cy = 0.5 + center_shift_y / pa_height
    # k1, k2, k3 直接透传（径向畸变系数，无单位）
    # p1, p2 = 0.0（切向畸变，暂不支持）
```

`fx`、`fy` 是将焦距从 mm 单位转换为"传感器宽度倍数"的归一化值（UE LensFile 使用归一化坐标系，与分辨率无关）。`cx`、`cy` 以 0.5 为中心原点，shift 正负号表示偏离中心的方向。

**按焦距分组（`:62-100`）：**

```python
def _group_by_focal_length(frames, tolerance_mm=0.1):
    sorted_frames = sorted(frames, key=lambda f: f.focal_length_mm)
    for frame in sorted_frames:
        if no existing group within tolerance:
            groups[fl] = frame  # 该组的代表帧取第一帧
```

LensFile 是一张"畸变标定表"：表的每一行对应一个焦距值，存储该焦距下的畸变参数。如果镜头是定焦（CSV 里所有帧焦距相同），那就只有一行；变焦镜头则按焦距采样多行。容差 0.1mm 防止浮点精度导致 "50.001mm" 和 "50.000mm" 被当成两个不同焦距。

**双方案写入（`:183-236`）：**

```python
# 方案 A: 使用 LensDistortionState（UE 5.4+）
try:
    params = unreal.LensDistortionState()
    ...
    lens_file.add_distortion_point(focus=0.0, zoom=zoom_value, distortion_state=params)
    added = True
except ...:
    pass

# 方案 B: 使用独立的 DistortionInfo/FocalLengthInfo 结构体（旧版 API）
if not added:
    try:
        distortion_info = unreal.DistortionInfo()
        ...
```

UE 的 LensFile Python API 在不同版本之间签名有变化。这段代码通过 `try/except` 先尝试新 API，失败则尝试旧 API，两者都失败才记录错误。这是应对 UE 版本不稳定的防御性写法。

---

### 4.6 `camera_builder.py` — CineCameraActor 创建（需要 UE）

**结论：** 在当前 UE 关卡里 Spawn 一个 `CineCameraActor`，配置传感器宽度（Filmback），并挂载 `LensComponent`（关联到刚创建的 LensFile）使畸变生效。

**核心流程（`:43-168`）：**

```
1. 检查 Camera Calibration 插件是否已加载（:22-36）
   → hasattr(unreal, "LensFile") 而不是 PluginBlueprintLibrary.is_plugin_loaded()
   （原因见 CLAUDE.md Gotchas：is_plugin_loaded 在某些 UE 版本不工作）

2. Spawn CineCameraActor 在世界原点（:85-99）
   → EditorLevelLibrary.spawn_actor_from_class(unreal.CineCameraActor, ...)

3. 配置 Filmback 传感器宽度（:110-116）
   → comp.filmback.sensor_width = sensor_width_mm
   注意：必须先 filmback = comp.filmback，修改后再 comp.filmback = filmback
   （UE Python 的 struct 是值类型，必须"读取→修改→写回"）

4. 添加 LensComponent 并尝试两种属性名（:121-148）
   → for prop_name in ("lens_file", "LensFile"):
       lens_component.set_editor_property(prop_name, lens_file)
   （UE 属性名在 Python 中的暴露名可能是蛇形或帕斯卡，试两种）

5. 开启畸变应用（:153-159）
   → lens_component.set_editor_property("apply_distortion", True)
```

> **技术原理 — UE Python 中的 struct 值语义：**  
> UE 的 `Filmback`、`Vector`、`Rotator` 等结构体在 Python 中是**值类型**（value type），`comp.filmback` 返回一份拷贝。修改这份拷贝不会自动写回 C++ 对象，必须显式赋值回去：`comp.filmback = modified_filmback`。这与 Python 普通对象（引用语义）的行为相反，是初学者的常见陷阱。

---

### 4.7 `sequence_builder.py` — LevelSequence 生成（需要 UE）

**结论：** 创建 UE LevelSequence 资产，并对每一帧写入摄影机的变换、焦距、光圈、焦距动画关键帧，完整重现 CSV 中记录的摄影机运动。

**帧率处理（`:26-42`）：**

```python
_FRACTIONAL_FPS = {
    23.976: (24000, 1001),   # drop-frame NTSC
    29.97:  (30000, 1001),
    59.94:  (60000, 1001),
}
def _resolve_frame_rate(fps):
    for known, fraction in _FRACTIONAL_FPS.items():
        if abs(fps - known) < 0.01:
            return fraction      # 用精确分数，避免浮点误差累积
    return (int(fps), 1)
```

`23.976` fps 不是整数，实际上是 `24000/1001`。UE 的 `FrameRate` 使用有理数（分子/分母），这样可以精确表示而不引入浮点误差。

**帧编号偏移（`:100-103, :187-189`）：**

```python
first_frame_num = csv_result.frames[0].frame_number
# ...
seq_frame_idx = frame.frame_number - first_frame_num  # ← 关键
frame_number = unreal.FrameNumber(seq_frame_idx)
```

这是"保留原始帧 cadence"的实现方式。如果 CSV 的帧号从 100 开始（而不是 0），Sequence 里的时间轴也从 0 开始，但帧号差距（gap）被保留了。例如 CSV 帧号 100, 102, 103（跳过了 101），Sequence 里就是关键帧在时间点 0, 2, 3 —— 中间那一帧确实是空白的，与原始录制一致。

**Track 与 Section 结构（`:117-178`）：**

```python
# Transform Track → 位置/旋转（6个通道）
transform_track = camera_binding.add_track(unreal.MovieScene3DTransformTrack)
transform_section = transform_track.add_section()
channels = transform_section.get_all_channels()
# channels[0]=LocX, [1]=LocY, [2]=LocZ, [3]=Roll, [4]=Pitch, [5]=Yaw

# 3个 Float Track → 焦距/光圈/焦距（每个 1 个通道）
focal_section   # CurrentFocalLength
aperture_section  # CurrentAperture
focus_section   # FocusSettings.ManualFocusDistance  ← 注意路径更深
```

UE Sequencer 的数据模型：`Track`（轨道，如"位置轨道"）包含一个或多个 `Section`（时间段）；`Section` 包含 `Channel`（每个轴各一个）；`Channel` 包含逐帧的 `Key`（关键帧）。

**`TransformConfig` 预分配优化（`:184-185`）：**

```python
xform_cfg = TransformConfig()  # 在循环外创建一次
for frame in csv_result.frames:
    ue_x, ue_y, ue_z = transform_position(..., cfg=xform_cfg)
```

如果不预分配，`transform_position` 每次都会在函数内部调用 `TransformConfig()`，对于几千帧的 CSV 就是几千次对象创建。在循环前创建一次实例，复用给所有帧，是个有意义的优化（注释 `:183` 明确说明了原因）。

---

### 4.8 `pipeline.py` — 流水线编排（总调度）

**结论：** 唯一的对外 API 是 `run_import(csv_path, fps)`。它把上面四个构建器串联成一条"5 步流水线"，统一处理错误，始终返回 `PipelineResult` 而不抛出异常（因此调用方无需 try/except）。

**`PipelineResult` 设计（`:34-44`）：**

```python
@dataclass
class PipelineResult:
    success: bool
    error_message: str = ""
    lens_file: Optional[object] = None
    camera_actor: Optional[object] = None
    level_sequence: Optional[object] = None
    report: Optional[ValidationReport] = None
    package_path: str = ""
```

**成功时**：`success=True`，所有对象字段均有值。  
**失败时**：`success=False`，`error_message` 描述原因，对象字段为 `None`。

调用方只需检查 `result.success`，不需要 try/except，这是"让错误变成数据"的设计模式。

**资产路径生成（`:50-52, :94-96`）：**

```python
def _sanitize_stem(name):
    return re.sub(r"[^A-Za-z0-9_]", "_", name)

csv_stem = Path(csv_path).stem             # 取文件名去掉扩展名
stem = _sanitize_stem(csv_stem)            # 非字母数字字符替换为下划线
package_path = f"{config.ASSET_BASE_PATH}/{stem}"  # /Game/PostRender/shot_name
```

例如 `shot1_take5_dense.csv` → stem = `shot1_take5_dense` → 资产路径 `/Game/PostRender/shot1_take5_dense/`。

**错误分层捕获（`:189-217`）：**

```python
except CsvParseError:     # 预期的 CSV 格式错误
except RuntimeError:      # 预期的运行时错误（插件缺失等）
except Exception:         # 未预期的错误（BUG）
    logger.exception(msg) # exception() 会打印完整 traceback
```

三层捕获让日志粒度不同：前两种是"已知可能发生的错误"，后一种是真正的 bug，会打印完整堆栈。

---

### 4.9 `ui_interface.py` — UI 辅助函数

**结论：** 提供 UI 层需要的四类辅助功能：文件对话框、Sequencer 操作、前置插件检查、测试相机管理。与 `widget.py` 的分工是：`ui_interface.py` 是功能函数库（无状态）；`widget.py` 是有状态的 UI 控制器。

**文件对话框三层降级（`:30-75`）：** 详见 Phase 2 · Section 2（Browse 的工作原理）。

**`save_axis_mapping` 的原子写入（`:295-406`）：** 详见 Phase 2 · Section 5（Save to config.py 的七步流程）。该函数末尾 `:405` 的 `importlib.reload(config)` 让内存与磁盘同步。

**`spawn_test_camera`（`:232-288`）：** 被 Phase 2 · Section 4 的 Spawn Test Camera 按钮驱动。核心是**按 Tag 而不是按 label** 追踪"测试相机"身份，避免误删用户自己创建的同名相机。流程：创建新相机 → 配置 Filmback → 删除携带 `PostRenderTool_TestCam` Tag 的旧相机 → `pilot_level_actor` 把 viewport 切到这台相机。

---

### 4.10 `widget_builder.py` — Blueprint 加载与 UI 生命周期

**结论：** 负责 UI 面板的**整个生命周期**：加载 Blueprint 资产 → 向 Editor 注册 Tab → 找到 Widget 实例 → 注入 Python UI 控制器。核心难点是 `spawn_and_register_tab` 是异步的，Widget 实例可能不会立刻可用。

**BP 的分发约定（文件头注释 `:9-26`）：**

`BP_PostRenderToolWidget` **不随 plugin 源码分发**。UE 5.7 不把 `UWidgetBlueprint::WidgetTree` 暴露给 Python 反射（评估后放弃自动生成路径，见 commit `bd140d7`），约定：

- **Bootstrap once**：第一个初始化项目的成员按 `docs/deployment-guide.md §1.3` 在 UMG Designer 里手工搭一次 UI（33 个必选 + 8 个可选控件，按 Figma 布局），然后 commit `.uasset` 到 git / p4
- **Sync forever**：所有后续部署（同事、CI、新机器）只需 `git pull` / `p4 sync` 取回同一份 `.uasset`，**不再重新搭**

`load_widget()`（`:94-124`）只**消费**已 commit 的资产；找不到就抛 `RuntimeError`，错误信息里按"从未存在过 vs 本地误删"两种场景给出不同恢复命令（Scenario A/B/C，见 `TEMPLATE_SETUP_INSTRUCTIONS`）。

**延迟注入机制（`:127-187`）：**

```python
def _inject_ui(widget_bp):
    widget = subsystem.find_utility_widget_from_blueprint(widget_bp)
    
    if widget is not None:
        # 同步路径：能立即拿到实例
        _active_ui = PostRenderToolUI(widget)
        return
    
    # 异步路径：注册 Slate 后处理 tick 回调
    attempts = [0]
    handle_holder = [None]
    
    def _try_inject(delta_time):
        attempts[0] += 1
        w = subsystem.find_utility_widget_from_blueprint(widget_bp)
        if w is not None:
            _active_ui = PostRenderToolUI(w)
            unreal.unregister_slate_post_tick_callback(handle_holder[0])
            return
        if attempts[0] >= 30:
            # 超过 30 帧还拿不到实例，报错并停止轮询
            unreal.unregister_slate_post_tick_callback(handle_holder[0])
    
    handle_holder[0] = unreal.register_slate_post_tick_callback(_try_inject)
```

`register_slate_post_tick_callback` 每次 UE Editor Slate UI 系统渲染完一帧后调一次；相当于"每帧检查 Widget 是否就绪"。最多尝试 30 次（约 0.5 秒），超时放弃并日志错误。

**`_active_ui` 全局引用（`:91`）：**

这个模块级变量是一个刻意保留的引用，防止 `PostRenderToolUI` 实例被 Python 垃圾回收。如果没有这个引用，Python GC 可能在 UI 仍然显示时销毁控制器对象，导致按钮点击后回调失效。

**工具函数：**

- `open_widget()`（`:190-207`）：`load_widget()` → `subsystem.spawn_and_register_tab()` → `_inject_ui()`。失败时尝试 `EditorUtilityLibrary.run_editor_utility_widget` 兜底。
- `rebuild_widget()`（`:248-257`）：把 `_active_ui` 置 `None` 后重新 `open_widget`。热重载 `widget.py` 后调这个，**不会删 BP**。
- `delete_widget()`（`:210-245`）：**破坏性**，删除磁盘上的 `.uasset`。通常不需要——`git pull` / `p4 sync` 就能恢复。仅在本地文件真的损坏时用。

---

### 4.11 `widget.py` — UI 控制器（事件绑定与状态管理）

**结论：** `PostRenderToolUI` 是整个 UI 层的核心，持有所有 UI 状态（当前 CSV 路径、解析结果、最后一次导入结果），并将 C++ UPROPERTY 声明的 41 个控件引用与 Python 回调绑定。

Phase 2 已经详细说明了每个按钮和控件的绑定关系，这里只补充**技术机制**。

**获取控件引用（`:97-113`）：**

```python
def _acquire(self, name, optional=False):
    ref = self._host.get_editor_property(name)
    # 这里的 name 必须与 PostRenderToolWidget.h 中的 UPROPERTY 名称完全一致
    self._controls[name] = ref
    return ref
```

`get_editor_property` 是 UE Python 反射系统的入口。它能工作的前提是 C++ 中有 `BlueprintReadOnly` 修饰词（见 CLAUDE.md Gotchas）。

**事件绑定模式（`:195-207`）：**

```python
def _bind_click(self, name, handler):
    btn = self._get(name)
    self._safe_clear(btn.on_clicked, ...)  # 先清除旧回调（防止热重载时堆叠）
    btn.on_clicked.add_callable(handler)
```

`on_clicked` 是 UE 的委托（Delegate）——类似 C# 的 event 或 JavaScript 的 EventEmitter。`add_callable` 把 Python 函数注册为监听器；`clear()` 移除所有监听器（热重载时必须先清除，否则同一个按钮会有多个处理器）。

**坐标实时预览（`:324-362`，驱动 Phase 2 · Section 4）：**

```python
def _refresh_coord_preview(self):
    idx = int(spn_frame.get_editor_property("value"))  # 读取用户选择的帧
    frame = self._csv_result.frames[idx]
    
    # 显示 Designer 原始数据
    self._set_text("txt_designer_pos", f"Designer Pos: ({frame.offset_x:.4f}, ...)")
    
    # 实时计算 UE 坐标（用当前 config 中的映射规则）
    ue_pos = transform_position(frame.offset_x, frame.offset_y, frame.offset_z)
    self._set_text("txt_ue_pos", f"UE Pos: ({ue_pos[0]:.1f}, ...) cm")
```

每次用户拨动帧号 SpinBox，`_on_frame_changed` → `_refresh_coord_preview`，实时显示当前坐标映射的效果，让用户在真正导入之前就能肉眼验证坐标系是否正确。

**"Apply Mapping" 按钮的直接内存修改（`:458-478`）：**

```python
def _on_apply_mapping(self):
    pos_mapping, rot_mapping = self._read_mapping_from_ui()
    config.POSITION_MAPPING = pos_mapping   # 直接修改模块全局变量
    config.ROTATION_MAPPING = rot_mapping
    self._refresh_coord_preview()  # 立即刷新预览
```

由于 `coordinate_transform.py` 的 `_default_cfg()` 每次调用时都从 `config` 模块读取（而不是在模块加载时缓存），直接修改 `config.POSITION_MAPPING` 就能立即影响所有后续的坐标变换，无需热重载。

---

### 4.12 C++ 层：`PostRenderToolWidget.h` — BindWidget 契约

**结论：** 这个文件是整个项目的"类型接口文档"——它用 C++ 类型系统正式声明了"UI 面板应该有哪 41 个控件"。Blueprint 必须满足这份契约，Python 通过这份契约拿到控件引用，Figma 的命名也按这份契约对齐。

**两种修饰词的区别（`:37-59`）：**

```cpp
UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional))
UTextBlock* prereq_label_0;   // ← BindWidgetOptional：Blueprint 里没有也不报错

UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
UButton* btn_recheck;          // ← BindWidget：Blueprint 里必须有，否则编译失败
```

- `BindWidget`：强制约束，Blueprint 编译时检查
- `BindWidgetOptional`：软约束，Blueprint 里没有则指针为 `nullptr`

**为什么必须有 `BlueprintReadOnly`（非常重要）：**

仅有 `meta=(BindWidget)` 的 `UPROPERTY` 在 Python 中是不可见的。Python 反射系统（`PyGenUtil.cpp:IsScriptExposedProperty`）只暴露带 `CPF_BlueprintVisible` flag 的属性，而这个 flag 由 `BlueprintReadOnly`（或 `BlueprintReadWrite`）设置。`meta=(BindWidget)` 是 UMG 编译器用的提示，不影响 Python 可见性。两个修饰词职责不同，缺一不可。

**按 Figma 分节的组织（`:33-182`）：**

C++ 头文件用 `// ===== Section N: ... =====` 注释把 UPROPERTY 按 Figma 分节分组——Section 1 (Prerequisites) / Section 2 (CSV File) / Section 3 (CSV Preview) / Section 4 (Coord Verification) / Section 5a+5b (Axis Mapping Position + Rotation) / Section 6 (Actions + Results)。这让文件与 Figma 面板、Phase 2 的文档、BP 的视觉分节形成**四方对齐**。

---

## Phase 5 — 端到端追踪

### 场景：用户点击 Browse → Import → 查看报告

以下是一次完整操作从入口到最终输出的跨文件执行链，标注了文件和关键行号。

---

**Step 0：用户运行 `import init_post_render_tool`**

```
init_post_render_tool.py:69 → launch_tool()
  :9  check_prerequisites()
      ui_interface.get_prerequisite_status()  ← 检查 6 个 UE 类/插件是否存在
  :47 检查 EditorAssetLibrary + EditorUtilitySubsystem
  :53 widget_builder.open_widget()
```

---

**Step 1：`widget_builder.open_widget()` 打开 UI 面板**

```
widget_builder.py:190 open_widget()
  :192 load_widget()
       → EditorAssetLibrary.load_asset("/PostRenderTool/Blueprints/BP_PostRenderToolWidget...")
  :196 subsystem.spawn_and_register_tab(widget_bp)
       → 在 UE Editor 创建一个新的浮动面板（Tab），按 Figma 布局呈现 6 个分节
  :207 _inject_ui(widget_bp)
       → 尝试立即找到 widget 实例
       → 如果找不到，注册 Slate post-tick 回调每帧重试
       → 找到后：PostRenderToolUI(widget) ← 进入 widget.py
```

---

**Step 2：`PostRenderToolUI.__init__()` 初始化 UI**

```
widget.py:73 __init__(host_widget)
  :87  _acquire_all_controls()
       → for each name in _REQUIRED_CONTROLS:
           host.get_editor_property(name)  ← 从 C++ UPROPERTY 取控件指针
  :88  _init_axis_combos()    ← 给 cmb_pos_* / cmb_rot_* 填充 X/Y/Z 选项
  :89  _push_initial_mapping_values()  ← 从 config 读映射值写入 UI（Section 5 初值）
  :90  _bind_events()
       → btn_browse.on_clicked.add_callable(self._on_browse_clicked)
       → btn_import.on_clicked.add_callable(self._on_import_clicked)
       → ... (共 10 个事件)
  :91  _check_and_display_prereqs()  ← 填充 prereq_label_0~5 + summary（Section 1）
```

此时 UI 面板已就绪，等待用户操作。

---

**Step 3：用户点击 Browse 按钮（Section 2 的 `btn_browse`）**

```
widget.py:266 _on_browse_clicked()
  ↓ 调用
ui_interface.py:30 browse_csv_file()
  → 尝试 DesktopPlatformBlueprintLibrary（不可用则跳过）
  → 尝试 osascript（macOS，打开原生 Finder 文件选择器，等待用户选择）
  → 返回选择的文件路径字符串

  :273  self._csv_path = csv_path
        self._set_text("txt_file_path", csv_path)  ← Section 2 的路径显示
  :276  parse_csv_dense(csv_path)  ← 进入 csv_parser.py
```

**csv_parser.py 内部执行（`:188-273`）：**

```
parse_csv_dense("shot1_take5_dense.csv")
  :206  open(file, encoding="utf-8-sig")  ← utf-8-sig 自动处理 BOM 头
  :210  reader.fieldnames  ← 读取第一行（CSV 头部）
  :216  _detect_camera_prefix(headers)
        → 正则扫描 "camera:cam01.offset.x" → 返回 "camera:cam01"
  :217  _validate_required_fields(headers, "camera:cam01")
        → 检查 17 个 REQUIRED_SUFFIXES 列都存在
  :227  for row in reader:
            FrameData(timestamp=row["timestamp"], frame_number=..., ...)
            timestamps_sec.append(_parse_timestamp_seconds(ts))
  :260  focal_lengths = [f.focal_length_mm for f in frames]
  :263  return CsvDenseResult(frames=[...], frame_count=1200, ...)
```

**回到 `widget.py:288`，Section 3 CSV Preview 全部字段一次性刷新：**

```
  self._csv_result = result
  self._set_text("txt_frame_count", "Frames: 1200")
  self._set_text("txt_focal_range", "Focal Length: 35.00 – 50.00 mm")
  self._set_text("txt_timecode", "Timecode: 00:00:00 → 00:00:50.00")
  self._set_text("txt_sensor_width", "Sensor Width: 60.00 mm")
  self._set_text("txt_detected_fps", "Auto: 24.0 fps")
  spn_frame.set_editor_property("max_value", 1199.0)   ← Section 4 的帧滑竿范围
  _refresh_coord_preview()  ← 立即更新第 0 帧的 Designer/UE 坐标预览
```

---

**Step 4：用户点击 Import 按钮（Section 6 的 `btn_import`）**

```
widget.py:501 _on_import_clicked()
  :506  self._set_results("Importing...")
  :509  pipeline.run_import(self._csv_path, fps=0.0)
```

**`pipeline.run_import()` 执行（`:74-217`）：**

```
:94   csv_stem = Path("shot1_take5_dense.csv").stem  → "shot1_take5_dense"
      stem = _sanitize_stem(csv_stem)  → "shot1_take5_dense"（本例无需替换）
      package_path = "/Game/PostRender/shot1_take5_dense"

:105  [Step 1/5] parse_csv_dense(csv_path)
      → 返回已有的 CsvDenseResult（再解析一次）

:115  effective_fps = 24.0（用户未设置，使用 detected_fps）

:132  _ensure_directory("/Game/PostRender/shot1_take5_dense")
      → EditorAssetLibrary.make_directory(...)

:138  [Step 2/5] lens_file_builder.build_lens_file(csv_result, "LF_shot1_take5_dense", ...)
```

**`lens_file_builder.build_lens_file()` 执行（`:107-261`）：**

```
:143  AssetToolsHelpers.get_asset_tools()
      .create_asset("LF_shot1_take5_dense", "/Game/PostRender/...", LensFile, ...)
      → 在 Content Browser 创建空 .ulens 资产

:160  _group_by_focal_length(frames, 0.1)
      → 例：CSV 只有 35mm 定焦，返回 {35.0: frames[0]}

:172  for focal_mm, frame in groups.items():
          nd = _compute_normalized_distortion(frame)
          # nd = {fx:0.583, fy:0.438, cx:0.5, cy:0.5, k1:-0.1, k2:0.05, k3:0.0}
          zoom_value = 35.0 / 60.0 = 0.583
          lens_file.add_distortion_point(focus=0.0, zoom=0.583, ...)

:257  EditorAssetLibrary.save_asset("/.../LF_shot1_take5_dense.LF_shot1_take5_dense")
      → 保存到磁盘
```

**回到 `pipeline.py:149`，Step 3/5：**

```
camera_builder.build_camera(sensor_width_mm=60.0, lens_file=<LensFile>, ...)
  → _check_camera_calibration_plugin()  ← hasattr(unreal, "LensFile")
  → EditorLevelLibrary.spawn_actor_from_class(CineCameraActor, Vector(0,0,0), ...)
  → comp.filmback.sensor_width = 60.0
  → camera_actor.add_component_by_class(LensComponent, ...)
  → lens_component.set_editor_property("lens_file", <LensFile>)
  → lens_component.set_editor_property("apply_distortion", True)
  → 返回 camera_actor
```

**Step 4/5，`sequence_builder.build_sequence()`：**

```
:79  AssetToolsHelpers 创建 LevelSequence 资产 "LS_shot1_take5_dense"

:92  numerator, denominator = _resolve_frame_rate(24.0) → (24, 1)
     movie_scene.set_display_rate(FrameRate(24, 1))

:100 first_frame_num = 100 （假设 CSV 从第 100 帧开始）
     last_frame_num = 1299
     frame_span = 1200
     movie_scene.set_playback_range(0, 1200)

:108 camera_binding = movie_scene.add_possessable(camera_actor)
     comp_binding   = movie_scene.add_possessable(cine_comp)

:119 transform_track = camera_binding.add_track(MovieScene3DTransformTrack)
     focal_section, aperture_section, focus_section = ...（3 个 float 轨道）

:185 xform_cfg = TransformConfig()  ← 只创建一次

:187 for frame in csv_result.frames:  ← 1200 次循环
         seq_frame_idx = frame.frame_number - 100  ← 0, 1, 2, ...
         ue_x, ue_y, ue_z = transform_position(frame.offset_x, ..., cfg=xform_cfg)
         ch_loc_x.add_key(FrameNumber(seq_frame_idx), ue_x, LINEAR)
         ...（共 9 个 channel，每帧各写一个 key）

:222 EditorAssetLibrary.save_asset(...)
```

**Step 5/5，`validator.generate_report()`：**

```
validator.py:208 generate_report(csv_result, fps=24.0)
  :225  validate_fov(frames)
        → for each frame: compute_fov_h(focal_mm, sensor_width)
          max_error = max(|computed - csv_fov_h|)
  :226  detect_anomalous_frames(frames)
        → for i in range(1, 1200):
            pos_dist = sqrt(dx²+dy²+dz²)
            if pos_dist > 0.5m: anomalies.append(...)
  → 返回 ValidationReport
```

**最终回到 `widget.py:512-521`，Section 6 的 `txt_results` 显示报告：**

```
self._last_result = pipeline_result   ← 保存以供"Open Sequencer"按钮使用
report_text = pipeline_result.report.format_report()
self._set_results(report_text)        ← 在 txt_results 显示中文报告
```

用户在 UI 的文本框里看到：

```
==================================================
【VP Post-Render 验证报告】
==================================================
  帧数        : 1200
  时间码范围  : 00:00:04.04 → 00:00:54.04
  焦距        : 35.000 mm
  传感器宽度  : 60.000 mm
  帧率        : 24.000 fps

【FOV 一致性检查】
  ✓ 最大 FOV 误差: 0.0002° (帧索引 0)
  阈值        : 0.05°

【异常帧检测】
  ✓ 未发现位置/旋转跳变
==================================================
```

---

## Phase 6 — 观察与学习路径

### 观察（仅列举，不修复）

1. **`sequence_builder.py:165` — Transform Channel 索引硬编码**  
   `channels[3]=Roll, [4]=Pitch, [5]=Yaw` 是通过对 UE 文档的理解写死的，没有用具名属性访问。如果未来 UE 版本改变了 channel 顺序，会静默地把 Roll 写成 Pitch，极难调试。

2. **`csv_parser.py:233` — 帧号解析**  
   `int(float(row["frame"]))` 之所以套两层，是因为 `DictReader` 返回的是字符串，而某些 CSV 可能导出 `"100.0"` 而不是 `"100"`。这是一个未记录的防御假设，值得在注释中说明。

3. **`lens_file_builder.py:93-99` — 焦距分组算法 O(n²)**  
   当前逻辑是对每帧都遍历一次已有的组，时间复杂度 O(n×m)（n=帧数，m=组数）。实践中 m 通常很小（定焦只有 1 组），但变焦镜头可能造成性能问题。可以改用 `bisect` 做二分搜索降到 O(n log m)。

4. **`pipeline.py:196` — `"package_path" in dir()` 的奇特写法**  
   在 `except` 块中用 `"package_path" in dir()` 检查局部变量是否已定义，这是因为 `package_path` 在 try 块的中间赋值，如果 `Path(csv_path).stem` 就抛出异常，`package_path` 可能还未赋值。更 Pythonic 的写法是在 try 块外用 `package_path = ""` 预初始化。

5. **`ui_interface.py:405` — `importlib.reload(config)` 的时序**  
   `save_axis_mapping` 最后调用 `importlib.reload(config)`；而 `widget.py:471` 的 `_on_apply_mapping` 也直接修改 `config.POSITION_MAPPING`。如果 `save_axis_mapping` 刷新了内存中的 config，而 widget 里之前直接修改的值与磁盘不一致，可能导致短暂的状态不同步。

6. **坐标映射未验证**  
   `config.py:11-21` 的注释明确标注"INITIAL GUESSES"。这是整个项目最大的未完成工作：默认坐标映射在没有真实硬件数据的情况下无法验证正确性。Figma 里 Section 4 的设计就是为消除这个不确定性而存在。

7. **Figma 静态文本与 BP 的对齐责任**  
   本文档 §2.10 列出了所有"Figma 里有、契约里没有"的静态文本。这部分没有自动化检查——若 Designer 在 BP 里把 `POSITION (m → cm)` 打错成 `POSITION (cm → m)`，编译不会报错，只是视觉误导。建议未来用一个 `test_designer_contract.py` 之类的脚本在 CI 里对比 BP 里的静态文字与 Figma 导出 JSON。

---

### 值得深入学习的技术概念（按优先级排序）

| 排序 | 概念 | 原因 |
|------|------|------|
| 1 | **UE Python 反射系统**（`UPROPERTY`、`get_editor_property`、`CPF_BlueprintVisible`） | 这是整个 C++↔Python 通信的基础，理解它才能独立扩展 UI |
| 2 | **UE BindWidget 契约机制**（C++ → UMG Blueprint 继承） | 理解为什么三层缺一不可 |
| 3 | **Python `@dataclass` 与值语义** | 项目大量使用，理解 `field(default_factory=...)` 避免常见陷阱 |
| 4 | **UE Sequencer 数据模型**（MovieScene / Track / Section / Channel / Key） | 理解 `sequence_builder.py` 的完整逻辑 |
| 5 | **坐标系变换**（右手/左手系、Y-up vs Z-up、轴映射矩阵） | 项目的核心数学，验证默认映射是否正确需要这个知识 |
| 6 | **相机光学公式**（FOV、Filmback、畸变模型 k1k2k3） | 理解 `validator.py` 和 `lens_file_builder.py` 的计算逻辑 |
| 7 | **Python 原子文件写入**（`tempfile.mkstemp` + `os.replace`） | `save_axis_mapping` 中的工程最佳实践 |
| 8 | **UE 委托机制**（Delegate、`on_clicked`、`add_callable`） | 理解 UI 事件绑定的底层原理 |

---

### 建议练习（由易到难）

**练习 1（简单）：读取 CSV 并打印统计**  
在 UE 外（普通 Python 解释器）：

```python
from Content.Python.post_render_tool.csv_parser import parse_csv_dense
result = parse_csv_dense("你的测试.csv")
print(result.frame_count, result.focal_length_range, result.detected_fps)
```

目标：理解 `parse_csv_dense` 的完整返回结构，以及帧率自动检测的行为。

---

**练习 2（简单）：修改坐标映射并验证**  
修改 `config.py` 中的 `POSITION_MAPPING`，把某一个轴的方向翻转（将 `100.0` 改为 `-100.0`）：

```python
import importlib
import post_render_tool.config as config
import post_render_tool.coordinate_transform as ct
importlib.reload(config)
print(ct.transform_position(1.0, 2.0, 3.0))
```

目标：理解 `importlib.reload` 热重载机制，以及 `cfg=None` 默认参数的延迟绑定行为。

---

**练习 3（中等）：为 `_detect_fps` 写单元测试**  
打开 `tests/test_csv_parser.py`，观察现有的测试结构，然后为以下场景各写一个测试：
- 完全稳定的 24fps 时间戳序列
- 包含一帧重复时间戳（`delta=0`）的序列
- 波动超过 10% 的不稳定序列（应返回 `None`）

目标：深入理解 `_detect_fps` 的边界条件，以及 `statistics.stdev` 的行为。

---

**练习 4（中等）：在 UI 上增加一个显示异常帧数量的 Label**  
在 `PostRenderToolWidget.h` 中增加一个新的 `UTextBlock* txt_anomaly_count`，在 BP 中添加对应控件（记得同步在 Figma 里补一个节点），在 `widget.py` 的 `_on_import_clicked` 里读取 `pipeline_result.report.anomalous_frames` 并更新这个 Label。

目标：完整走一遍"Figma 设计 → C++ 声明 → BP 满足 → Python 绑定"的四层流程。

---

**练习 5（困难）：用真实 CSV 数据验证坐标映射**  
使用真实的 Disguise Designer CSV 数据，通过 Phase 2 · Section 4 的工作流（拨动 `spn_frame` 看预览 → 调 Section 5 的轴映射 → 按 `Spawn Test Camera`）对比 `txt_designer_pos` 与 `txt_ue_pos`，手动调整轴映射直到 UE viewport 中的测试相机位置与现场一致。记录正确的映射规则，按 `Save to config.py` 持久化，并补充一条 `# Verified with real data on YYYY-MM-DD` 注释。

目标：这是整个项目中唯一无法自动化的验证步骤，也是把工具真正投入生产使用的必要前提。

---

*文档结束*
