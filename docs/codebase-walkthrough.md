# VP Post-Render Tool — 代码库全景导读

> 更新日期：2026-04-19（同步 BP 自动化路径落地、C++ 桥接层引入、UE 5.7 真实 API 对齐）  
> 适用版本：commit `668115d` (branch `main`)  
> UI 参考：[Figma — VP Post-Render Tool · UE Panel Design](https://www.figma.com/design/H6WkczRHFmCVuPmTFahZBN/VP-Post-Render-Tool-%E2%80%94-UE-Panel-Design?node-id=1-2)  
> 阅读前提：了解基本 Python 语法；不需要了解 UE 或 C++，文中会逐一解释。

> ⚠️ **Distortion 路线已变（2026-05-08 更新）**: 本文档 §4.5 / §4.6 描述的
> `lens_file_builder.py` + LensFile + LensComponent 流程已**完整下架**。Distortion
> 现在由 Path C (Custom Post-Process Material + `PostRenderDistortionControllerComponent`)
> 接管, `LF_*` 资产不再生成。下架前的 Path A 代码快照在 `archive/path_a_runtime/`,
> 当前流程见 `CLAUDE.md` 顶部 callout + `docs/custom-postprocess-distortion-final-plan.md`。
> 本文档其余部分(BP 自动化 / WidgetTree / pure-Python 模块)仍有效。

> ⚠️ **架构反转说明**：早期版本（commit `bd140d7`）曾认定"BP 必须手工搭建、不可自动化"。
> 2026-04-17 起，引入 `UPostRenderToolBuildHelper`（C++ 桥接 `UWidgetBlueprint::WidgetTree`）+
> `docs/widget-tree-spec.json`（单一真相源）+ `build_widget_blueprint.run_build()`（幂等编排器），
> **现在自动化才是主路径**，手动搭建（`docs/bootstrap-checklist.md`）退化为兜底方案。
> 见下文 §Phase 1 关键架构特性 / §4.10 / §4.13。

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
├── Source/PostRenderTool/              ← [C++ 层] 三件事：BindWidget 契约 + WidgetTree 桥 + 工具栏命令
│   ├── Public/
│   │   ├── PostRenderToolModule.h      ← 模块入口；持有 FUICommandList 与 ToolMenus 句柄
│   │   ├── PostRenderToolWidget.h      ← 33 个 UPROPERTY 声明（26 Required + 7 Optional）
│   │   ├── PostRenderToolBuildHelper.h ← Python ↔ UWidgetBlueprint::WidgetTree 桥（3 UFUNCTION）
│   │   └── PostRenderToolCommands.h    ← TCommands 子类：PlayToolBar 按钮的 FUICommandInfo
│   └── Private/
│       ├── PostRenderToolModule.cpp    ← 注册 PlayToolBar 按钮 + Python ExecPythonCommand 跳转
│       ├── PostRenderToolWidget.cpp    ← 空 NativeConstruct stub
│       ├── PostRenderToolBuildHelper.cpp ← EnsureRootPanel / FindWidgetByName / EnsureWidgetUnderParent
│       └── PostRenderToolCommands.cpp  ← UI_COMMAND 注册 OpenToolWidget
│
├── Content/
│   ├── Blueprints/
│   │   └── BP_PostRenderToolWidget.uasset  ← [UMG Blueprint] UI 布局；自动化生成为主，commit 后所有部署直接 sync（见 §4.10）
│   └── Python/
│       ├── init_post_render_tool.py    ← [入口点] 前置检查 + 启动 UI
│       └── post_render_tool/           ← [Python 主包]
│           ├── config.py                  ← 所有可调参数（坐标映射、路径、阈值）
│           ├── csv_parser.py              ← 解析 Disguise CSV Dense 格式（纯 Python）
│           ├── coordinate_transform.py    ← 坐标系转换 Designer→UE（纯 Python）
│           ├── validator.py               ← FOV 校验 + 异常帧检测（纯 Python）
│           ├── lens_file_builder.py       ← 生成 UE .ulens 文件（需要 unreal）
│           ├── camera_builder.py          ← 创建 CineCameraActor（需要 unreal）
│           ├── sequence_builder.py        ← 创建 LevelSequence + 写入关键帧（需要 unreal）
│           ├── pipeline.py                ← 流水线编排（总调度，需要 unreal）
│           ├── ui_interface.py            ← UI 辅助：文件对话框、Sequencer、MRQ、前置检查
│           ├── widget.py                  ← 将 C++ 控件指针与 Python 回调绑定（UI 控制器）
│           ├── widget_builder.py          ← 加载 BP 资产、生成 Editor 面板、rebuild_from_spec
│           ├── build_widget_blueprint.py  ← JSON 规约 → UMG WidgetTree 编排器（幂等）（§4.13）
│           ├── spec_loader.py             ← widget-tree-spec.json 解析与契约校验（纯 Python）（§4.14）
│           ├── widget_properties.py       ← 13 种 widget + 常见 slot 属性应用器（§4.15）
│           ├── widget_variants.py         ← 颜色/字体/尺寸 variant 调色板（纯 Python）（§4.16）
│           └── tests/                     ← 纯 Python 单元测试 + 三方契约漂移检测
│
├── docs/                               ← 安装、契约、部署、自动化规约、Bootstrap 兜底清单
│   ├── plugin-setup.md                 ← UBT 编译 + 首次安装
│   ├── deployment-guide.md             ← §1.3：自动化主路径；手动备份
│   ├── bootstrap-checklist.md          ← 无自动化时的手动搭建清单（兜底）
│   ├── bindwidget-contract.md          ← 33 控件契约速查
│   ├── widget-tree-spec.json           ← BP 单一真相源（自动化生成的输入）
│   ├── widget-tree-spec.schema.md      ← spec 的 JSON Schema 描述
│   ├── codebase-walkthrough.md         ← 本文档
│   ├── codebase-walkthrough.html       ← 本文档的可交互 HTML 渲染
│   ├── figma-design-prompt.md          ← Figma 重绘提示词（视觉风格基准）
│   └── PRD.md                          ← 产品需求与成功指标
│
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

**C++ 层做三件事：契约、桥接、工具栏。**

1. **契约层** — `PostRenderToolWidget.h` 用 33 个 `UPROPERTY` 声明（26 Required + 7 Optional）告诉 UE
   "这个 Widget 该有哪些控件、叫什么名字、是什么类型"。BP 编译时 UMG 编译器自动把 BP 里的控件指针
   赋给这些变量；Python 通过 `get_editor_property("btn_browse")` 拿到控件引用再绑定回调。
2. **WidgetTree 桥** — `PostRenderToolBuildHelper.h/.cpp` 暴露 3 个 `BlueprintCallable` UFUNCTION
   （`EnsureRootPanel` / `FindWidgetByName` / `EnsureWidgetUnderParent`），让 Python 能突破
   "`UWidgetBlueprint::WidgetTree` 不暴露反射"的限制，从而以 JSON 规约驱动 UMG 树结构。详见 §4.17。
3. **工具栏入口** — `PostRenderToolCommands.h/.cpp` + `PostRenderToolModule.cpp` 把
   "Open VP Post-Render Tool" 按钮注册到 LevelEditor 的 PlayToolBar，按钮点击通过
   `IPythonScriptPlugin::ExecPythonCommand` 跳转到 `widget_builder.open_widget()`。详见 §4.18。

**四层缺一不可**：C++ 契约 → JSON 规约（`docs/widget-tree-spec.json`）→ Python 编排器
（`build_widget_blueprint.run_build()`，经 BuildHelper 桥落到 BP 资产）→ Python UI 控制器
（`widget.py` 把控件指针绑定到回调）。

**BP 的分发模式：自动化为主、手动为兜底（2026-04-17 反转旧约定）。**

- **首选路径** — `docs/widget-tree-spec.json` 是 BP 的单一真相源；`build_widget_blueprint.run_build()`
  幂等地把规约编排到 `BP_PostRenderToolWidget`：已存在的同名 widget 不动（保留 Designer 里的人工微调），
  仅创建缺失项并仅在新建时应用 spec 属性 / slot。需要批量重设主题（颜色 / 字体 / variant）时
  传 `force_reapply=True` 强制覆盖。
- **手动兜底** — 仅在自动化路径不可用（spec 损坏 / Editor 反射故障）时，按
  `docs/bootstrap-checklist.md` 在 UMG Designer 里手搭一次。完成后 commit `.uasset`，
  其他人继续走 `git pull` / `p4 sync` 同步。
- 旧版本（commit `bd140d7`）曾约定"必须手工搭、不可自动化"，已被推翻。详见 §4.10 与 §4.13。

---

## Phase 2 — UI 面板导读（Figma 设计映射）

这一节以 Figma 设计稿为起点，说明面板上每个标题、控件的业务含义、背后落到哪个 C++ UPROPERTY、被哪段 Python 消费、为什么这么设计。目标是：读完这一节后，打开 Figma 或 UE 面板，**看到任意一个控件都能说出它的名字、职责、所在文件与行号**。

### 2.1 设计来源与定位

- **文件**：`VP Post-Render Tool — UE Panel Design`
- **根节点**：`1:2`
- **URL**：<https://www.figma.com/design/H6WkczRHFmCVuPmTFahZBN/VP-Post-Render-Tool-%E2%80%94-UE-Panel-Design?node-id=1-2>

Figma **不是实现源**——整个面板的 `.uasset` 在 UMG Designer 中手工搭建，Figma 只是"外观基准 + 控件命名基准"。如果 Figma 改了字段顺序或分节，不会自动同步到 BP；反过来，BP 的控件名若偏离 Figma，只要与 `PostRenderToolWidget.h` 的 UPROPERTY 对得上就不会报错，但视觉会漂移——所以三者要保持一致。

### 2.2 面板整体结构（5 个分节）

```
┌ VP Post-Render Tool Panel ─────────────────┐
│                                            │
│  Section 1 · Prerequisites      (折叠态)   │  ← 前置插件检查（启动时自动跑）
│  Section 2 · CSV File                      │  ← 选 CSV，只读路径显示
│  Section 3 · CSV Preview                   │  ← 解析后摘要 + FPS 可覆盖输入
│  Section 4 · Axis Mapping                  │  ← 改坐标映射 + 可持久化回 config.py
│  Section 5 · Actions + RESULTS             │  ← 一键 Import + 产物入口 + 日志
│                                            │
└────────────────────────────────────────────┘
```

自上而下就是用户的线性工作流：**Prereq ✓ → 选 CSV → 看摘要 → 调轴映射 → Import → 查报告**。

**画布尺寸固定 360 × 720**（commit `1f9a96f`）：根布局是 `ScaleBox + SizeBox`，整个面板按
360 × 720 的设计尺寸渲染，**不再随 EUW Tab 自适应**——Tab 拉宽时面板等比缩放，确保
不同显示器上 spacing / typography 一致。Mockup 与导言已同步到这个尺寸（commit `02b638e`）。

每个分节是一个 `#242424` 背景 + `#333` 描边的卡片容器（Figma 节点 `1:3` / `1:10` / `2:2` / `4:2` / `5:2`），标题左侧是 `#e8704d` 橙色竖条——这是工具的品牌色，同一橙色也用在主按钮 `Import` 与 `RESULTS` 小标题上，视觉语言上表示"可操作的焦点"。

### 2.3 命名契约（五处必须一致 + 自动化漂移检测）

| 位置 | 文件 | 举例 |
|---|---|---|
| Figma `data-node-id` 的 `name` | Figma 设计稿 | `btn_browse`（Figma 节点 `1:15`） |
| C++ UPROPERTY 名 | `Source/PostRenderTool/Public/PostRenderToolWidget.h` | `UButton* btn_browse;` |
| Python 控件名字符串 | `widget.py:44-67` 的 `_REQUIRED_CONTROLS` / `_OPTIONAL_CONTROLS` | `"btn_browse"` |
| Designer 中 BP 的 Widget 名 | `Content/Blueprints/BP_PostRenderToolWidget.uasset` | UMG Hierarchy 面板里叫 `btn_browse` |
| **JSON 规约的 `name`** | `docs/widget-tree-spec.json` | `{"name": "btn_browse", "type": "Button", "role": "required"}` |

**五者必须字符串级一致**。多端校验分两层：

- **编译期硬检查**：UMG 编译器在 BP 编译时校验 C++↔BP（`meta=(BindWidget)` 不满足直接编译失败）。
- **测试期漂移检测**（commit `a247ba9`）：`tests/test_spec_drift.py` 用正则解析 `PostRenderToolWidget.h`
  抽取 `BindWidget` / `BindWidgetOptional` 名集合，与 `widget.py` 的 `_REQUIRED_CONTROLS` /
  `_OPTIONAL_CONTROLS`、以及 `widget-tree-spec.json` 收集的 contract 名做三方差集对比。任意一端
  改名 / 漏名都会让 unittest 失败。运行：

  ```bash
  cd Content/Python && python -m unittest post_render_tool.tests.test_spec_drift -v
  ```

Python 端拼写错虽不影响 BP 编译，但 `host.get_editor_property("...")` 会返回 `None`、`widget.py`
打 warning 继续跑——这种"沉默 bug"以前只能等运行时点按钮发现，现在 drift detector 在 CI 里就拦下。
详见 `CLAUDE.md > Gotchas > Python-vs-Designer name drift` 与
`CLAUDE.md > Gotchas > JSON spec is the fourth source of truth`。

---

### 2.4 Section 1 — Prerequisites（前置插件检查）

Figma 节点 `1:3`（容器）、`1:4` / `1:5` / `1:8` / `1:9`（头部）。

**视觉形态**：折叠标题行，左侧 ▶ 表示可展开，右侧 `6 / 6 OK` 用 `#4caf50` 绿色显示统计。
展开后列出 6 条状态行 + 一个 Re-check 按钮。

**折叠机制（commit `b794e2b` / `c123eed`）**：使用 `UExpandableArea` 控件（UE 自带），
两个 named slot — `HeaderContent` 装 summary 文字、`BodyContent` 装 6 条状态行 + Re-check 按钮。
为让 Python 能跨进 named slot 写入 `prereq_label_*` / `prereq_summary` / `btn_recheck`，
C++ 侧通过 `INamedSlotInterface` 桥接（`PostRenderToolBuildHelper.cpp` 的 `EnsureWidgetUnderParent`
分支识别 `ExpandableArea` 父类，分别落到 Header / Body slot）。
JSON spec 约定该节点的 `children[0]` → HeaderContent、`children[1]` → BodyContent，
保证规约 ↔ BP 树结构 1:1。

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
| `2:13` `FPS SpinBox` | `spn_fps` | `USpinBox` | `widget.py:317` `_on_fps_changed`（委托 `on_value_changed`） | 用户必填的目标帧率 |

**功能逻辑**：

- Preview 数据**在 Browse 回调里同步填充**——`parse_csv_dense()` 一次返回后 4 个文本字段一并更新。
- FPS SpinBox 默认 `0.0`，用户需手动填入 24 / 25 / 29.97 / 30 等目标帧率。`pipeline.run_import` 收到 `fps <= 0` 会抛异常，防止沉默地跑出错误帧率的 LevelSequence。

**设计原理**：Preview 把所有与摄影机"物理参数"有关的基础数据摊在桌面上，让用户按 Import 之前就能肉眼校验："焦距范围对不对？时间码长度对不对？传感器 35mm/60mm 有没有预设错？"——这些错带到 LensFile 就得整条流水线重跑。FPS 刻意不做自动检测（commit `63146c8`）：CSV 时间戳抖动常使估算值误差 ≥1 fps，而 fps 错误直接破坏 LevelSequence 时基；强制用户显式选择能换取可预期的输出。

---

### 2.7 Section 4 — Axis Mapping（轴映射编辑器）

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
- 点 `Apply Mapping` → `widget.py:458` `_on_apply_mapping`：读 UI → **直接覆盖** `config.POSITION_MAPPING` / `ROTATION_MAPPING` 内存字典。**不写磁盘**。
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

**设计原理**：轴映射的本质是 6 组 `(source_axis_index, scale_factor)` 元组，可表达绝大多数"右手/左手系 + 单位换算 + 方向翻转"。用 `ComboBox × SpinBox` 暴露给用户，比让他们手编 `config.py` 字典对现场 TD 更友好。`Apply`（内存沙盒）与 `Save`（固化到源码）是**双层承诺模型**——用户可反复拨动确认后一键固化，避免"改了忘存"。

---

### 2.8 Section 5 — Actions + RESULTS（执行与日志）

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
- Section 的标题文字（`Prerequisites` / `CSV File` / `CSV Preview` / `Axis Mapping` / `Actions`）——静态 Label
- `POSITION (m → cm)` / `ROTATION (deg)` / `RESULTS` 子标题（`4:6` / `4:44` / `5:13`）——静态分组 Label
- `UE.X` / `UE.Y` / `UE.Z` / `Pitch` / `Yaw` / `Roll` 行首 Label——静态 Label
- `FPS` 前置 Label（`2:12`）——静态 Label
- `←` / `×` / `▾` / `▲▼` 字符——UMG 会由 `UComboBoxString` / `USpinBox` 自行渲染步进与下拉箭头；Figma 使用这些字符是因为 Figma 里没有等价 primitive，BP 里**不要手写**

**统一原则**：任何"不需要 Python 读或写的文字"都不要出现在 `_REQUIRED_CONTROLS` 里。控件数量保持 **26 Required + 7 Optional = 33**，与 `PostRenderToolWidget.h` 严格一致。

---

### 2.11 33 个 UPROPERTY 速查表（按 Figma 分节）

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
| 4 · Axis Mapping | `cmb_pos_x_src` / `spn_pos_x_scale` | `UComboBoxString` / `USpinBox` | ✓ Required |
| 4 · Axis Mapping | `cmb_pos_y_src` / `spn_pos_y_scale` | 同上 | ✓ Required |
| 4 · Axis Mapping | `cmb_pos_z_src` / `spn_pos_z_scale` | 同上 | ✓ Required |
| 4 · Axis Mapping | `cmb_rot_pitch_src` / `spn_rot_pitch_scale` | 同上 | ✓ Required |
| 4 · Axis Mapping | `cmb_rot_yaw_src` / `spn_rot_yaw_scale` | 同上 | ✓ Required |
| 4 · Axis Mapping | `cmb_rot_roll_src` / `spn_rot_roll_scale` | 同上 | ✓ Required |
| 4 · Axis Mapping | `btn_apply_mapping` | `UButton` | ✓ Required |
| 4 · Axis Mapping | `btn_save_mapping` | `UButton` | ✓ Required |
| 5 · Actions | `btn_import` | `UButton` | ✓ Required |
| 5 · Actions | `btn_open_seq` | `UButton` | ✓ Required |
| 5 · Actions | `btn_open_mrq` | `UButton` | ✓ Required |
| 5 · Actions | `txt_results` | `UMultiLineEditableText` | ✓ Required |

合计 **26 Required + 7 Optional = 33**。这张表与 `docs/bindwidget-contract.md` 冗余但本文档独立可读，两者必须同步更新。

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
│  │  widget.py          ←  绑定 33 个控件引用 + 事件回调    │   │
│  │  ui_interface.py    ←  文件对话框 / 前置检查 / 轴映射写回 │   │
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
# 运行时数据流（CSV → UE 资产）
config.py                        ← 无依赖（纯常量）
csv_parser.py            ← config
coordinate_transform.py  ← config
validator.py             ← config, csv_parser
lens_file_builder.py     ← config, csv_parser                    [requires unreal]
camera_builder.py        ← (无 Python 包内依赖)                   [requires unreal]
sequence_builder.py      ← coordinate_transform, csv_parser      [requires unreal]
pipeline.py              ← 以上全部                              [requires unreal]
ui_interface.py          ← config                                [requires unreal]
widget.py                ← config, coordinate_transform, csv_parser,
                            pipeline, ui_interface                [requires unreal]
widget_builder.py        ← widget, build_widget_blueprint        [requires unreal]
init_post_render_tool.py ← ui_interface, widget_builder          [requires unreal]

# BP 自动化生成路径（独立子图，仅在 rebuild_from_spec / run_build 调用时活跃）
spec_loader.py           ← 无依赖（纯 Python，可单元测试）
widget_variants.py       ← 无依赖（纯 Python）
widget_properties.py     ← widget_variants                       [requires unreal at apply time]
build_widget_blueprint.py ← spec_loader, widget_properties,
                             widget_variants                      [requires unreal]
                          调用 unreal.PostRenderToolBuildHelper.* (C++ UFUNCTION)
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

> **⚠️ 注意：** 注释写明这些是"初始猜测"，必须用真实数据在 UE 视口中验证后，通过 Section 4 的 `Apply Mapping` / `Save to config.py` 固化。

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

> **为什么不自动检测 FPS？** 早期版本曾有 `_detect_fps()` + `txt_detected_fps` 显示（commit `63146c8` 删除）。实践中 Disguise 导出的时间戳抖动常使估算与真实帧率差 ≥1 fps，而错误帧率直接破坏 LevelSequence 时基。现在 fps 改为 `spn_fps` 用户必填，Import 前校验 `fps > 0`，以可预期的显式输入换取沉默失败的风险。

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
参数默认为 `None`，函数内部 `if cfg is None: cfg = _default_cfg()` 从 `config` 模块读取当前配置。这样调用者可以传入自定义配置覆盖默认值（测试时很有用），也可以不传（直接用全局配置）。**这就是为什么 Phase 2 · Section 4 的 `Apply Mapping` 只改 `config` 字典就能立刻生效——`_default_cfg` 每次都去 `config` 读，没有缓存。**

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

将数字结果格式化为中文文本报告，带 ✓/⚠ 符号，直接显示在 UI 的 `txt_results` 文本框里（即 Phase 2 · Section 5 的 RESULTS 区域）。

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

**UE 5.7 真实 API 写入（`:196-227`，commit `6107d4b` 对齐）：**

```python
# CameraCalibrationCore/Public/LensFile.h:174-183 真实签名：
#   AddDistortionPoint(focus, zoom, FDistortionInfo, FFocalLengthInfo)
#   AddImageCenterPoint(focus, zoom, FImageCenterInfo)
zoom_value = focal_mm / frame.sensor_width_mm   # 归一化焦距比

distortion_info = unreal.DistortionInfo()
distortion_info.parameters = [k1, k2, p1, p2, k3]   # TArray<float>

focal_info = unreal.FocalLengthInfo()
focal_info.fx_fy = unreal.Vector2D(fx, fy)

image_center = unreal.ImageCenterInfo()
image_center.principal_point = unreal.Vector2D(cx, cy)

lens_file.add_distortion_point(
    new_focus=0.0, new_zoom=zoom_value,
    new_point=distortion_info, new_focal_length=focal_info,
)
lens_file.add_image_center_point(
    new_focus=0.0, new_zoom=zoom_value, new_point=image_center,
)
```

注意：UE 5.7 的字段命名是 snake_case (`parameters` / `fx_fy` / `principal_point`)，
对应 C++ 端 `Parameters` / `FxFy` / `PrincipalPoint`。畸变点 + 主点偏移要分两次调用
（不再走 `LensDistortionState` 的合一接口）。

**资产创建走 `factory=None` 默认路径（`:148-165`，commit `69ebc88`）：**

`ULensFileFactoryNew` 在 `CameraCalibrationEditor` 的 Private 模块，UE 5.7 不暴露给 Python。
`AssetTools.create_asset(factory=None)` 时 UE 内部走 `NewObject` 默认路径
（`AssetTools.cpp:1762-1764`），照样能拿到合法的 `unreal.LensFile` 实例。
代码保留对旧版本 `LensFileFactoryNew` 的 `getattr` 探测兜底，但 5.7 走默认路径。

---

### 4.6 `camera_builder.py` — CineCameraActor 创建（需要 UE）

**结论：** 在当前 UE 关卡里 Spawn 一个 `CineCameraActor`，配置传感器宽度（Filmback），并挂载 `LensComponent`（关联到刚创建的 LensFile）使畸变生效。

**核心流程（`:98-217`）：**

```
1. 检查 Camera Calibration 插件是否已加载（:24-47）
   → hasattr(unreal, "LensFile") 而不是 PluginBlueprintLibrary.is_plugin_loaded()
   （原因见 CLAUDE.md Gotchas：is_plugin_loaded 在某些 UE 版本不工作）

2. Spawn CineCameraActor 在世界原点（:140-159）
   → EditorLevelLibrary.spawn_actor_from_class(unreal.CineCameraActor, ...)

3. 配置 Filmback 传感器宽度（:165-171）
   → filmback = comp.filmback; filmback.sensor_width = X; comp.filmback = filmback
   （UE Python 的 struct 是值类型，必须"读取→修改→写回"）

4. 用 SubobjectDataSubsystem 添加 LensComponent（:179-183，commit `aa65bb0` / `6818c0d`）
   → lens_class = unreal.load_class(None, "/Script/CameraCalibrationCore.LensComponent")
   → SubobjectDataSubsystem.attach_subobject(...) 走官方 editor 路径
   原因：ULensComponent 无 BlueprintType → unreal.LensComponent 不存在；
        AActor::AddComponentByClass 带 ScriptNoExport → Python 也不可调。
        必须用 load_class 拿 UClass + 走 SubobjectDataSubsystem。

5. 关联 LensFile 到嵌套 struct（:188-197，commit `de3c939`）
   → picker = lens_component.get_editor_property("lens_file_picker")
   → picker.lens_file = lens_file
   → picker.use_default_lens_file = False
   → lens_component.set_editor_property("lens_file_picker", picker)
   原因：ULensComponent 没有顶层 LensFile 属性；真实 UPROPERTY 是
        FLensFilePicker 嵌套（LensComponent.h:280-281 → FLensFilePicker.LensFile，
        CameraCalibrationCore/Public/LensFile.h:361-378）。

6. 开启畸变应用（:202-208）
   → lens_component.set_editor_property("apply_distortion", True)
```

> **技术原理 — UE Python 中的 struct 值语义：**  
> UE 的 `Filmback`、`Vector`、`Rotator`、`LensFilePicker` 等结构体在 Python 中是**值类型**
> （value type），`comp.filmback` / `lens_component.get_editor_property("lens_file_picker")`
> 都返回一份拷贝。修改这份拷贝不会自动写回 C++ 对象，必须显式 set 回去。这条规则在
> §4.6 这两步（Filmback / LensFilePicker）里出现两次，是初学者的常见陷阱。

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

**帧率 / 播放范围 / 绑定调到 LevelSequence 上（`:90-117`，commit `901aba6`）：**

```python
# UE 5.7: UMovieScene 的 SetDisplayRate / SetPlaybackRange / AddPossessable
# 都是 inline / 非 UFUNCTION，Python 不可见。改走 MovieSceneSequenceExtensions
# 提供的 ScriptMethod UFUNCTION，挂在 UMovieSceneSequence (ULevelSequence) 上。
level_sequence.set_display_rate(unreal.FrameRate(numerator, denominator))
level_sequence.set_playback_start(0)
level_sequence.set_playback_end(frame_span)
camera_binding = level_sequence.add_possessable(camera_actor)
comp_binding   = level_sequence.add_possessable(cine_comp)
```

旧文档里的 `movie_scene.set_display_rate(...)` / `movie_scene.add_possessable(...)` 在 5.7
是行不通的——必须挂到 `level_sequence`（即 `ULevelSequence`）上。

**Track 与 Section 结构（`:124-160`）：**

```python
# Transform Track → 位置/旋转（6个通道）
transform_track = camera_binding.add_track(unreal.MovieScene3DTransformTrack)
transform_section = transform_track.add_section()
channels = transform_section.get_all_channels()
# channels[0]=LocX, [1]=LocY, [2]=LocZ, [3]=Roll, [4]=Pitch, [5]=Yaw

# 3个 Float Track → 焦距/光圈/对焦距离（每个 1 个通道）
focal_section     # CurrentFocalLength
aperture_section  # CurrentAperture
focus_section     # FocusSettings.ManualFocusDistance  ← 注意路径更深
```

UE Sequencer 的数据模型：`Track`（轨道，如"位置轨道"）包含一个或多个 `Section`（时间段）；
`Section` 包含 `Channel`（每个轴各一个）；`Channel` 包含逐帧的 `Key`（关键帧）。

**`add_key` 必须用关键字参数（`:203-223`，commit `bc4cc9f`）：**

```python
ch_loc_x.add_key(frame_number, ue_x, interpolation=interp)   # ✓ 正确
ch_loc_x.add_key(frame_number, ue_x, interp)                 # ✗ 报错
```

UE 5.7 的 `add_key` 用 `interpolation` 关键字接收 `MovieSceneKeyInterpolation`；
位置参数透传会触发 `ScriptStructError`。

**`TransformConfig` 预分配优化（`:188-189`）：**

```python
xform_cfg = TransformConfig()  # 在循环外创建一次
for frame in csv_result.frames:
    ue_x, ue_y, ue_z = transform_position(..., cfg=xform_cfg)
```

如果不预分配，`transform_position` 每次都会在函数内部调用 `TransformConfig()`，
对于几千帧的 CSV 就是几千次对象创建。循环前创建一次实例复用给所有帧，是个有意义的优化
（注释 `:187` 明确说明了原因）。

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

**结论：** 提供 UI 层需要的四类辅助功能：文件对话框、Sequencer / MRQ 打开、前置插件检查、轴映射原子写回 `config.py`。与 `widget.py` 的分工是：`ui_interface.py` 是功能函数库（无状态）；`widget.py` 是有状态的 UI 控制器。

**文件对话框三层降级（`:30-75`）：** 详见 Phase 2 · Section 2（Browse 的工作原理）。

**`save_axis_mapping` 的原子写入（`:315-426`）：** 详见 Phase 2 · Section 4（Save to config.py 的七步流程）。函数末尾的 `importlib.reload(config)` 让内存与磁盘同步。

**`open_sequencer`（`:144-164`，commit `b640434`）：** 改用 `ULevelSequenceEditorBlueprintLibrary`
的静态 UFUNCTION，而非 subsystem：

```python
unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(level_sequence)
```

**`open_movie_render_queue`（`:167-201`，commit `47c6fc6` / `5e1eb07` / `668115d`）：**
UE 5.7 没暴露 `FGlobalTabmanager::TryInvokeTab` 到 Python，脚本无法直接打开 MRQ tab。
当前实现是**预填 + 手动指引**：

```python
queue_subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
job = unreal.MoviePipelineEditorLibrary.create_job_from_sequence(  # 注意是 EditorLibrary
    queue_subsystem.get_queue(), level_sequence)
unreal.MoviePipelineEditorLibrary.ensure_job_has_default_settings(job)
unreal.log("请手动打开 Movie Render Queue: 菜单 Window → Cinematics → Movie Render Queue")
```

注意类名是 `MoviePipelineEditorLibrary`（commit `668115d` 修正），不是
`MoviePipelineEditorBlueprintLibrary`（后者在 UE 5.7 不存在）。

---

### 4.10 `widget_builder.py` — Blueprint 加载与 UI 生命周期

**结论：** 负责 UI 面板的**整个生命周期**：加载 Blueprint 资产 → 向 Editor 注册 Tab → 找到 Widget 实例 → 注入 Python UI 控制器。核心难点是 `spawn_and_register_tab` 是异步的，Widget 实例可能不会立刻可用。

**BP 的分发约定（自动化为主、手动为兜底；2026-04-17 反转旧约定）：**

- **首选路径** — 用 `rebuild_from_spec()`（本模块 `:260-281`）一键重建：
  `docs/widget-tree-spec.json` → `build_widget_blueprint.run_build()` → `PostRenderToolBuildHelper`
  C++ UFUNCTION → 写入 `BP_PostRenderToolWidget.uasset` → 自动 reopen tab。幂等：
  默认保留 Designer 里的人工微调；传 `force_reapply=True` 强制覆盖（用于 variant / 主题级改动）。
- **手动兜底** — 仅在 spec 损坏 / Editor 反射故障 / 历史 BP 已 commit 这三种情形下，
  按 `docs/bootstrap-checklist.md` 在 UMG Designer 里手搭，commit 后其他人 `git pull` / `p4 sync`。
- 旧约定（commit `bd140d7`：BP 必须手搭、不可自动化）已被推翻。`load_widget()` 抛
  `RuntimeError` 时的 `TEMPLATE_SETUP_INSTRUCTIONS` 提供四档恢复路径：
  Scenario A（`git pull` / `p4 sync`）/ B（`git restore` / `p4 sync -f`）/
  **C（`rebuild_from_spec()`，自动化主路径）** / D（`docs/bootstrap-checklist.md` 手动兜底）。

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
- `rebuild_from_spec(*, force_reapply=False)`（`:260-281`，commit `6ccbf0e`）：从
  `docs/widget-tree-spec.json` 重建 WidgetTree → `rebuild_widget()`。`force_reapply=True`
  时 spec 里的所有 widget / slot 属性强制覆盖 Designer 微调，用于 variant 或主题级改动后整体回流。
  调用链：本函数 → `build_widget_blueprint.run_build()` → BuildHelper UFUNCTION 桥。
  C++ UPROPERTY 改动后仍需 Editor 重启 + 插件重编（这函数只动 BP 资产，不动 C++ 反射元数据）。
- `delete_widget()`（`:210-245`）：**破坏性**，删除磁盘上的 `.uasset`。通常不需要——
  `git pull` / `p4 sync` / `rebuild_from_spec` 都能恢复。仅在本地文件真的损坏时用。

---

### 4.11 `widget.py` — UI 控制器（事件绑定与状态管理）

**结论：** `PostRenderToolUI` 是整个 UI 层的核心，持有最后一次导入结果（供 `Open Sequencer` 重用），并将 C++ UPROPERTY 声明的 33 个控件引用与 Python 回调绑定。

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

**"Apply Mapping" 按钮的直接内存修改（`:458-478`）：**

```python
def _on_apply_mapping(self):
    pos_mapping, rot_mapping = self._read_mapping_from_ui()
    config.POSITION_MAPPING = pos_mapping   # 直接修改模块全局变量
    config.ROTATION_MAPPING = rot_mapping
```

由于 `coordinate_transform.py` 的 `_default_cfg()` 每次调用时都从 `config` 模块读取（而不是在模块加载时缓存），直接修改 `config.POSITION_MAPPING` 就能立即影响所有后续的坐标变换，无需热重载。

---

### 4.12 C++ 层：`PostRenderToolWidget.h` — BindWidget 契约

**结论：** 这个文件是整个项目的"类型接口文档"——它用 C++ 类型系统正式声明了"UI 面板应该有哪 33 个控件"。Blueprint 必须满足这份契约，Python 通过这份契约拿到控件引用，Figma 的命名也按这份契约对齐。

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

C++ 头文件用 `// ===== Section N: ... =====` 注释把 UPROPERTY 按 Figma 分节分组——Section 1 (Prerequisites) / Section 2 (CSV File) / Section 3 (CSV Preview) / Section 4a+4b (Axis Mapping Position + Rotation) / Section 5 (Actions + Results)。这让文件与 Figma 面板、Phase 2 的文档、BP 的视觉分节、JSON 规约形成**五方对齐**。

---

### 4.13 `build_widget_blueprint.py` — JSON 规约 → BP 编排器

**结论：** 把 `docs/widget-tree-spec.json` 描述的完整 UMG 层级幂等地"播放"到
`BP_PostRenderToolWidget.uasset` 上。"幂等"指：已存在的同名 widget 默认不动（保留 Designer 微调），
仅创建缺失项；属性 / slot 也仅在新建时应用。需要主题级回流时传 `force_reapply=True` 强制覆盖。

**调用栈：**

```
rebuild_from_spec()                          # widget_builder.py:260
   └─ build_widget_blueprint.run_build()     # build_widget_blueprint.py:225
        ├─ spec_loader.load_spec(...)        # 解析 + schema 校验 JSON
        ├─ _load_blueprint(...)              # EditorAssetLibrary.load_asset
        ├─ _build_node(bp, parent=None, root_node)  # 递归
        │    ├─ PostRenderToolBuildHelper.ensure_root_panel(...)
        │    ├─ PostRenderToolBuildHelper.ensure_widget_under_parent(...)
        │    │    → 返回 (EEnsureWidgetResult, widget, slot) 三元组
        │    ├─ widget_properties.apply_widget_properties(widget, props)
        │    └─ widget_properties.apply_slot_properties(slot, slot_props)
        ├─ FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified（在 C++ 桥里）
        ├─ unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        └─ unreal.EditorAssetLibrary.save_asset(bp)
```

**ExpandableArea 特例处理（`:108-164`）：** Section 1 的 `UExpandableArea` 不是普通 `UPanelWidget`，
需要通过 `INamedSlotInterface` 写入 HeaderContent / BodyContent。规约约定 `children[0]`/[1]
对应这两个 named slot；编排器调用 `_ensure_expandable_slot(...)` 单独处理。

**入参：** `run_build(spec_path: str | None = None, *, force_reapply: bool = False)` —
默认从 `<plugin_root>/docs/widget-tree-spec.json` 读取，支持自定义路径用于测试或多 spec 切换。

---

### 4.14 `spec_loader.py` — JSON 规约解析与契约校验（纯 Python）

**结论：** 单一职责的 spec 加载器：读取 JSON、按 schema 校验类型 / 角色 / 嵌套合法性、
收集所有 `role: required` / `role: optional` 的名集合用于 drift detector。**无 unreal 依赖**，
可在 UE 外直接运行（CI / 单元测试），也由 `build_widget_blueprint` 在 UE 内调用。

**关键常量：**

```python
VALID_ROLES = {"required", "optional", "decorative"}
PANEL_TYPES = {"CanvasPanel", "ScrollBox", "VerticalBox", "HorizontalBox"}
CONTENT_TYPES = {"Border", "SizeBox", "Button", "ScaleBox"}
EXPANDABLE_TYPES = {"ExpandableArea"}   # 约定 children=[Header, Body]
LEAF_TYPES = {"Image", "TextBlock", "Spacer", "SpinBox", "ComboBoxString",
              "MultiLineEditableText"}
```

**对外 API：**

- `load_spec(path) -> dict` — 文件 → JSON dict（`FileNotFoundError` / `JSONDecodeError`）
- `validate_spec(spec, raise_on_error=True) -> List[str]` — 返回错误列表或抛 `SpecValidationError`
- `collect_contract_names(spec) -> Tuple[Set[str], Set[str]]` — 返回 `(required, optional)`
  名集合，drift detector 用它与 C++ header / `widget.py` 做三方差集

---

### 4.15 `widget_properties.py` — Widget / Slot 属性应用器

**结论：** 把 spec 里的 `properties` / `slot_properties` 字典通过 UE 反射应用到 widget / slot 实例。
覆盖 13 种常用 widget（`UButton` / `UTextBlock` / `USpinBox` / `UComboBoxString` /
`UImage` / `UMultiLineEditableText` / `UExpandableArea` / `UScaleBox` / `USizeBox` /
`UCanvasPanel` / `UVerticalBox` / `UHorizontalBox` / `UScrollBox`）+ 常见 slot 属性
（CanvasPanelSlot 的 anchors / position / size / alignment、HorizontalBox/VerticalBox
slot 的 padding / size / alignment、SizeBox 的 width / height / aspect ratio）。

**核心函数：**

- `apply_widget_properties(widget, props: dict)` — 按属性类型分发到 `_apply_color` /
  `_apply_font` / `_apply_brush` / `_apply_combo_options` / 通用 `set_editor_property` 等。
- `apply_slot_properties(slot, slot_props: dict)` — 同上，按 slot 子类（CanvasPanelSlot /
  BoxSlot / SizeBoxSlot 等）分发。

**类型转换器（commit `ce4bb07`）：** 三个常见类型转换在 `_coerce_*` 系列函数里收口：
- 颜色：`[r, g, b, a]`（0..1 linear）→ `unreal.LinearColor`
- 字体：`{"font_size": 14, "type_face": "Bold"}` → `unreal.SlateFontInfo`
- 笔刷：`{"image_size": [w, h], "tint_color": [...]}` → `unreal.SlateBrush`

---

### 4.16 `widget_variants.py` — Variant 调色板（纯 Python）

**结论：** 颜色 / 字体 / spacing / 控件样式的语义化 variant 表，把"主题级改动"集中到一个文件。
spec 里每个节点可写 `"variant": "primary_button"`，编排器解析时合并 variant + 节点显式 `properties`
（**显式优先**）。改一处 variant 配方就能让所有引用方同步换肤。

**主要表：**

- `COLORS` — 10 种语义色（`accent_orange` / `card_bg` / `text_title` / `text_primary` /
  `text_secondary` / `status_ok` / `status_err` / `button_primary` / `button_secondary` / `divider`），
  RGBA linear。与 `docs/figma-design-prompt.md` 的视觉 token 表保持一致。
- `FONT_FAMILY` — 字族常量（默认 Roboto）
- `WIDGET_VARIANTS` — `{(widget_type, variant_name): properties_dict}`，例如
  `("Button", "primary")` → `{"background_color": COLORS["button_primary"], ...}`

**纯 Python**，无 unreal 依赖，可单元测试。

---

### 4.17 C++ 层：`PostRenderToolBuildHelper.h/.cpp` — Python ↔ WidgetTree 桥

**结论：** UE 5.7 把 `UWidgetBlueprint::WidgetTree` 用裸 `UPROPERTY()` 声明
（`BaseWidgetBlueprint.h:16-17`），无 `BlueprintVisible` flag → Python 反射不可见
（参见 `PyGenUtil.cpp::IsScriptExposedProperty` 规则）。这个 helper 把
"创建根 panel / 查找已存 widget / 在父节点下确保 widget"这三个最小操作封装成
`BlueprintCallable` UFUNCTION，让 Python 能通过 `unreal.PostRenderToolBuildHelper.*` 驱动它们。

**3 个 UFUNCTION：**

| C++ 签名 | Python 调用 | 行为 |
|---|---|---|
| `EnsureRootPanel(BP, RootName, RootClass)` | `unreal.PostRenderToolBuildHelper.ensure_root_panel(...)` | WidgetTree 为空时创建 root；已有就返回现有 root |
| `FindWidgetByName(BP, Name)` | `find_widget_by_name(...)` | 遍历整棵树找同名 widget |
| `EnsureWidgetUnderParent(BP, Name, Class, Parent)` | `ensure_widget_under_parent(...)` | 返回 `(EEnsureWidgetResult, UWidget, UPanelSlot)` 三元组（UFUNCTION 出参）；slot 仅在新建时非空 |

**EEnsureWidgetResult 枚举：** `Created` / `AlreadyExisted` / `TypeMismatch` /
`InvalidInput` / `ParentCannotHoldChildren`，调用方据此分支决定是否应用 spec 属性。

**两条隐性约束（`PostRenderToolBuildHelper.h` 文件头注释）：**

1. **`UWidget::bIsVariable` 私有 bitfield 无法外部 set**（`Widget.h:318`）。`Widget.cpp:195`
   构造函数默认置 `true`，正好满足 BindWidget 反射需求；副作用是装饰性 widget 也成为 Variable
   （多几个生成类的 UPROPERTY，无害）。
2. **结构性变更必须 `MarkBlueprintAsStructurallyModified`**，普通 `Blueprint->Modify()`
   只服务 Undo，不会让下次编译重建生成类。`EnsureRootPanel` / `EnsureWidgetUnderParent`
   内部都调了它。

**重要操作约束：** 改动 helper 的 UFUNCTION 后，Live Coding 注册新 UFUNCTION 不可靠 —
必须 Editor 重启 + 插件全编译，并用 `help(unreal.PostRenderToolBuildHelper)` 验证可见。

---

### 4.18 C++ 层：`PostRenderToolCommands.h/.cpp` + Module — PlayToolBar 入口

**结论：** 在 LevelEditor 的 PlayToolBar 上加一个 "Open VP Post-Render Tool" 按钮，点击时
通过 `IPythonScriptPlugin::ExecPythonCommand` 跳转到 `widget_builder.open_widget()`。
让用户不必每次开 Python Console 敲 `import init_post_render_tool`。

**为什么走 `TCommands` + `FUICommandList`（MEMORY 已记录）：**
UE 5.7 PlayToolBar 是 `SlimHorizontalToolBar` multi-box，**只渲染走命令系统的按钮**——
直接传 `FUIAction` 的 `AddMenuEntry` 在这里会被静默丢弃。必须按官方 plugin（InEditorDocumentation /
PCG）的模式：`TCommands<>` 子类 + `FUICommandInfo` + `FUICommandList`，再用
`Entry.SetCommandList(PluginCommands)` 把 entry 绑回 list。

**关键代码（`PostRenderToolModule.cpp:55-88`）：**

```cpp
UToolMenu* ToolbarMenu = ToolMenus->ExtendMenu(
    TEXT("LevelEditor.LevelEditorToolBar.PlayToolBar"));
FToolMenuSection& Section = ToolbarMenu->FindOrAddSection(TEXT("PluginTools"));
FToolMenuEntry& Entry = Section.AddEntry(
    FToolMenuEntry::InitToolBarButton(FPostRenderToolCommands::Get().OpenToolWidget));
Entry.SetCommandList(PluginCommands);
Entry.Icon = FSlateIcon(FAppStyle::GetAppStyleSetName(),
                        TEXT("LevelEditor.OpenCinematic"));
ToolMenus->RefreshAllWidgets();   // 注意：不刷新则 Slate 不会重渲染
```

`OpenToolWidget` 回调（`:90-103`）：取 `IPythonScriptPlugin::Get()`，跑
`from post_render_tool.widget_builder import open_widget; open_widget()`。
Python 不可用时仅打 `LogTemp` warning，不抛错。

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
       → 在 UE Editor 创建一个新的浮动面板（Tab），按 Figma 布局呈现 5 个分节
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
       → ... (共 8 个事件)
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

**回到 `widget.py`，Section 3 CSV Preview 全部字段一次性刷新：**

```
  self._set_text("txt_frame_count", "Frames: 1200")
  self._set_text("txt_focal_range", "Focal Length: 35.00 – 50.00 mm")
  self._set_text("txt_timecode", "Timecode: 00:00:00 → 00:00:50.00")
  self._set_text("txt_sensor_width", "Sensor Width: 60.00 mm")
```

---

**Step 4：用户点击 Import 按钮（Section 5 的 `btn_import`）**

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
      → 返回 CsvDenseResult

:115  effective_fps = 24.0（来自 spn_fps，用户必填）

:132  _ensure_directory("/Game/PostRender/shot1_take5_dense")
      → EditorAssetLibrary.make_directory(...)

:138  [Step 2/5] lens_file_builder.build_lens_file(csv_result, "LF_shot1_take5_dense", ...)
```

**`lens_file_builder.build_lens_file()` 执行（`:107-256`）：**

```
:143  AssetToolsHelpers.get_asset_tools()
      .create_asset("LF_shot1_take5_dense", "/Game/PostRender/...",
                    LensFile, factory=None)   ← UE 5.7 走默认 NewObject 路径
      → 在 Content Browser 创建空 .ulens 资产

:176  _group_by_focal_length(frames, 0.1)
      → 例：CSV 只有 35mm 定焦，返回 {35.0: frames[0]}

:187  for focal_mm, frame in sorted(groups.items()):
          nd = _compute_normalized_distortion(frame)
          # nd = {fx:0.583, fy:0.438, cx:0.5, cy:0.5, k1:-0.1, k2:0.05, k3:0.0}
          zoom_value = 35.0 / 60.0 = 0.583
          lens_file.add_distortion_point(new_focus=0.0, new_zoom=zoom_value,
              new_point=DistortionInfo(...), new_focal_length=FocalLengthInfo(...))
          lens_file.add_image_center_point(new_focus=0.0, new_zoom=zoom_value,
              new_point=ImageCenterInfo(...))

:254  EditorAssetLibrary.save_asset("/.../LF_shot1_take5_dense.LF_shot1_take5_dense")
      → 保存到磁盘
```

**回到 `pipeline.py:149`，Step 3/5：**

```
camera_builder.build_camera(sensor_width_mm=60.0, lens_file=<LensFile>, ...)
  → _check_camera_calibration_plugin()  ← hasattr(unreal, "LensFile")
  → EditorLevelLibrary.spawn_actor_from_class(CineCameraActor, Vector(0,0,0), ...)
  → filmback = comp.filmback; filmback.sensor_width = 60.0; comp.filmback = filmback
  → lens_class = unreal.load_class(None, "/Script/CameraCalibrationCore.LensComponent")
  → SubobjectDataSubsystem.attach_subobject(...) ← 加 LensComponent
  → picker = lens_component.get_editor_property("lens_file_picker")
    picker.lens_file = <LensFile>; picker.use_default_lens_file = False
    lens_component.set_editor_property("lens_file_picker", picker)
  → lens_component.set_editor_property("apply_distortion", True)
  → 返回 camera_actor
```

**Step 4/5，`sequence_builder.build_sequence()`：**

```
:79  AssetToolsHelpers 创建 LevelSequence 资产 "LS_shot1_take5_dense"

:93  numerator, denominator = _resolve_frame_rate(24.0) → (24, 1)
     level_sequence.set_display_rate(FrameRate(24, 1))   ← 挂在 LevelSequence 上

:101 first_frame_num = 100 （假设 CSV 从第 100 帧开始）
     last_frame_num  = 1299
     frame_span      = 1200
     level_sequence.set_playback_start(0)
     level_sequence.set_playback_end(1200)

:110 camera_binding = level_sequence.add_possessable(camera_actor)
     comp_binding   = level_sequence.add_possessable(cine_comp)

:124 transform_track = camera_binding.add_track(MovieScene3DTransformTrack)
     focal_section, aperture_section, focus_section = ...（3 个 float 轨道）

:189 xform_cfg = TransformConfig()  ← 只创建一次

:191 for frame in csv_result.frames:  ← 1200 次循环
         seq_frame_idx = frame.frame_number - 100  ← 0, 1, 2, ...
         ue_x, ue_y, ue_z = transform_position(frame.offset_x, ..., cfg=xform_cfg)
         ch_loc_x.add_key(FrameNumber(seq_frame_idx), ue_x, interpolation=interp)
         ...（共 9 个 channel，每帧各写一个 key；interpolation 必须用关键字传）

:230+ EditorAssetLibrary.save_asset(...)
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

**最终回到 `widget.py:512-521`，Section 5 的 `txt_results` 显示报告：**

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
   `config.py:11-21` 的注释明确标注"INITIAL GUESSES"。这是整个项目最大的未完成工作：默认坐标映射在没有真实硬件数据的情况下无法验证正确性。需要用真机数据试跑后通过 Section 4 的 Apply / Save 固化。

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
print(result.frame_count, result.focal_length_range, result.sensor_width_mm)
```

目标：理解 `parse_csv_dense` 的完整返回结构（`CsvDenseResult` 数据类的各字段）。

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
完整走一遍"五源契约同步 + 自动化 BP 重建"的流程：

1. **Figma**：在 Section 5 RESULTS 区域画一个新的 `txt_anomaly_count` 文本节点，命名严格用此字符串
2. **C++**：`PostRenderToolWidget.h` 增加 `UPROPERTY(BlueprintReadOnly, meta=(BindWidget)) UTextBlock* txt_anomaly_count;`
   → 退出 Editor，UBT 全编译插件（Live Coding 不支持 UPROPERTY 改动）
3. **JSON spec**：`docs/widget-tree-spec.json` 在 Section 5 节点的 children 里追加
   `{"name": "txt_anomaly_count", "type": "TextBlock", "role": "required", "properties": {...}}`
4. **widget.py**：`_REQUIRED_CONTROLS` 元组加上 `"txt_anomaly_count"`；
   `_on_import_clicked` 末尾读 `pipeline_result.report.anomalous_frames` 并 `_set_text(...)`
5. **跑 drift detector**：`python -m unittest post_render_tool.tests.test_spec_drift -v`
   → 五源全绿才算同步完成
6. **重启 Editor + 重编插件 → UE Python console**：`from post_render_tool.widget_builder import rebuild_from_spec; rebuild_from_spec()`
   → BP 自动获得新 widget；点 Import 验证

目标：完整体验五源契约（Figma / C++ / JSON / widget.py / BP）+ 自动化 BP 重建路径。

---

**练习 5（困难）：用真实 CSV 数据验证坐标映射**  
使用真实的 Disguise Designer CSV 数据：先按默认 `config.POSITION_MAPPING` 跑一次 Import，在 UE 视口里手动 spawn 一个 `CineCameraActor`（参数取自导入后的 LevelSequence 首帧）核对现场位置；若偏差明显，通过 Phase 2 · Section 4 的轴映射 ComboBox × SpinBox 拨动并 `Apply Mapping` 后重跑 Import，直到对齐。记录正确的映射规则，按 `Save to config.py` 持久化，并补充一条 `# Verified with real data on YYYY-MM-DD` 注释。

目标：坐标映射是工具投入生产前的必要前提——`config.py` 的默认值只是"初始猜测"，必须用真机数据固化。

---

*文档结束*
