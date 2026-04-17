# VP Post-Render Tool 部署与使用指南

## 1. 安装

VP Post-Render Tool 打包成**自包含的 UE 5.7 plugin**。把整个仓库目录复制（或 symlink）进宿主 UE 项目的 `Plugins/` 子目录即可：

### 1.1 安装 plugin

```bash
# macOS / Linux (symlink — 开发推荐，改动双向同步)
ln -sfn /path/to/post_render_tool /path/to/MyVPProject/Plugins/PostRenderTool

# macOS / Linux (copy — 分发推荐)
cp -R /path/to/post_render_tool /path/to/MyVPProject/Plugins/PostRenderTool

# Windows PowerShell
Copy-Item -Recurse "C:\path\to\post_render_tool" "C:\path\to\MyVPProject\Plugins\PostRenderTool"
```

最终结构：`MyVPProject/Plugins/PostRenderTool/PostRenderTool.uplugin` + `Source/` + `Content/`。

### 1.2 首次编译 plugin

1. 关闭宿主 UE Editor（如果正在运行）
2. 右键 `.uproject` → **Services → Generate Xcode Project**（macOS）或 **Generate Visual Studio project files**（Windows）
3. 双击 `.uproject` 打开项目
4. UE 检测到新的 C++ plugin 会弹出：
   > *"The following modules are missing or built with a different engine version: PostRenderTool. Would you like to rebuild them now?"*
5. 点击 **Yes**，等待 UBT 编译（30 秒 – 5 分钟）
6. 成功后：**Edit → Plugins** → 搜 "Post-Render" → 看到 "VP Post-Render Tool" 绿色启用

**编译失败时**：检查 `Saved/Logs/` 下的 UBT 日志，或确认系统已装 Xcode（macOS）/ Visual Studio 2022（Windows）。

### 1.3 创建 Blueprint 资产并填充 BindWidget（必做一次性工作）

> **重要：** 当前仓库**没有**完整的 `BP_PostRenderToolWidget.uasset`（git / p4 里只跟踪 C++ 源码和 Python 文件，UMG 资产需要每个部署环境一次性补齐）。
>
> 现象识别：UI 打开是空白面板 + Output Log 一大片 `A required widget binding "<name>" of type <type> was not found.` 编译错误 → 处于"空壳 BP"状态，走本节流程。

**Step 1：创建 Blueprint 外壳**（必做，手动，<30 秒）

1. 启动 Editor，**Content Browser** → 左侧 "Plugins" 区 → **VP Post-Render Tool Content** → `Blueprints/`
2. 右键 → **Blueprint Class** → 底部 "ALL CLASSES" 搜 `PostRenderToolWidget`
3. 选中 `UPostRenderToolWidget` → **Select**
4. 命名 **`BP_PostRenderToolWidget`**（必须一字不差，C++ 和 Python 都按这个名字查）
5. **不用打开 Designer 做任何事**，保存、关闭

**Step 2：用 Python 脚本自动填充 33 + 8 个 BindWidget**（推荐路径）

> **前提：** 本方案通过 C++ `UPostRenderToolBuildHelper`（`BlueprintCallable` UFUNCTION）桥接 Python 到 `UWidgetBlueprint::WidgetTree`，因为 UE 5.7 下 WidgetTree 不被 Python 反射直接暴露。确保 plugin 已包含 `PostRenderToolBuildHelper.cpp` 并完成一次 UBT rebuild（commit 是否包含可用 `git log --oneline Source/PostRenderTool/Public/PostRenderToolBuildHelper.h` 确认）。

打开 Editor 的 Output Log，下面切 **Python** 模式，输入：

```python
from post_render_tool import build_widget_blueprint
build_widget_blueprint.build()
```

脚本会：
1. Load 空 BP
2. 每个 binding 调用 `unreal.PostRenderToolBuildHelper.ensure_bind_widget(bp, name, class)` —— C++ 层在 `WidgetTree` 中查找同名 widget（递归 PanelWidget/ContentWidget），缺失就 `ConstructWidget` 并 append 到 `VerticalBox` 根面板 `RootPanel`（首次创建）
3. 调 `unreal.BlueprintEditorLibrary.compile_blueprint` 编译 BP
4. 调 `unreal.EditorAssetLibrary.save_asset` 保存

成功后日志：

```
[build_widget_blueprint] Created VerticalBox root 'RootPanel'.
[build_widget_blueprint]   + btn_recheck (Button)
[build_widget_blueprint]   + btn_browse (Button)
...（共 41 行 "+")
[build_widget_blueprint] Added 41 widget(s).
[build_widget_blueprint] Saved /PostRenderTool/Blueprints/BP_PostRenderToolWidget.
```

脚本 **rerun-safe**：
- 递归遍历整棵 widget tree 按名字识别已存在的 binding —— 你在 Step 3 把控件搬进嵌套 `VerticalBox` 后再跑也不会重复添加
- 已有的 root panel（无论是你手动换成的 `ScrollBox` / `Overlay` / 还是脚本最初建的 `RootPanel` `VerticalBox`）**不会被替换**，新 binding 直接追加到当前 root
- 只有在 root 完全不是 `PanelWidget`（比如 `SizeBox` 这种只能容纳 1 个子）时脚本会 abort 并报错，不会强行覆盖

典型 rerun 场景：
- C++ 新增 `UPROPERTY(BindWidget)` → 跑一次只追加新 binding
- Designer 里误删某个 widget → 跑一次自动补回
- 同事换机器全新 clone → 跑一次初始化

**Step 3：视觉美化（可选）**

脚本只满足"BindWidget 合规"最低要求，所有控件平铺在 `RootPanel` 里，长得丑。打开 Designer：

- 按 `docs/bindwidget-contract.md` 的 `Section` 列把控件拖到分组（Prerequisites / CSV File / CSV Preview 等 6 个 `VerticalBox` 子容器）
- 调字体、颜色、padding、label
- **千万不要改 widget 的 `Name` 或 `Is Variable` checkbox** —— 改了就断 binding
- Compile + Save

**Step 4：提交资产**

Content Browser 右键 `BP_PostRenderToolWidget` → Source Control / 或直接在 git / p4 里 add 该 `.uasset`。二进制资产提交后团队成员 sync 就能拿同一份，免得每人都跑 Step 1~3。

---

**备选：纯手动搭建**（不推荐，但脚本失败时的兜底方案）

如果 Step 2 的 Python 脚本在你的 UE 版本里报错（比如 `construct_widget` API 签名变化、`widget_tree` 反射不可见等），fallback 到手工：

1. 按 Step 1 新建 BP 后**双击进 Designer**
2. Hierarchy 里删掉默认 `CanvasPanel_0`，拖一个 **Vertical Box** 命名 `RootPanel`
3. 打开 `docs/bindwidget-contract.md`，按"Required widgets (33)"和"Optional widgets (8)"表一条条拖控件：
   - 类型严格按 `Type` 列（`UButton` = Button、`UTextBlock` = Text、`USpinBox` = Spin Box、`UComboBoxString` = Combo Box (String)、`UMultiLineEditableText` = Editable Text (Multi-Line)）
   - 名字严格按 `Name` 列，大小写下划线不能错
   - 保持 "Is Variable" 勾选（默认已勾）
4. Compile → 看 Compiler Results → 缺哪个补哪个 → 再 Compile → Save
5. 提交资产

完整排错见 `docs/plugin-setup.md` 与 `docs/bindwidget-contract.md`。

### 1.4 启动工具

**方式 A — Toolbar 按钮（推荐）**

Editor 主工具栏右侧会自动出现 **VPTool** 按钮（由 `FPostRenderToolModule::StartupModule` 通过 `UToolMenus` 注册到 `LevelEditor.LevelEditorToolBar.User` 扩展点）。点击按钮直接执行：

```python
from post_render_tool.widget_builder import open_widget; open_widget()
```

仅加载并 spawn widget tab — **不做命令行侧的 prerequisite 诊断输出**。如果依赖缺失，widget 里的 Prerequisites 区域仍会显示 MISSING。

> 按钮没出现？插件没启用或 UBT 没重新编译。见第 4 节故障排查。

**方式 B — Python Console（首次验证 / 诊断使用）**

Output Log 切换到 **Python** 模式，输入：

```python
import init_post_render_tool
```

这会调用 `launch_tool()`：**先**把 `get_prerequisite_status()` 的结果逐项 log 到 Output Log（OK / MISSING + 修复提示），**再**调用 `open_widget()`；若 widget 依赖（`EditorAssetLibrary` / `EditorUtilitySubsystem`）缺失，则打印诊断信息、不打开 UI。首次部署、排查"按钮点了没反应"时用这条路径。

> **两条路径的差异**：toolbar 按钮只"开窗"；Python Console 入口额外做 prerequisite 日志诊断 + 依赖缺失 fallback。运行态上两者最终都调到 `open_widget()`，但日志输出和失败处理路径不同。

> **Prerequisites**：`ui_interface._PREREQUISITE_CHECKS` 会检查 6 项：Python Editor Script Plugin、Editor Scripting Utilities、Camera Calibration、CineCameraActor、LevelSequence、EditorUtilitySubsystem。
>
> - **自动启用（随 `PostRenderTool.uplugin` 依赖级联）**：`PythonScriptPlugin`、`EditorScriptingUtilities`
> - **典型内建（UE 5.7 标准 Editor build 里可用）**：`CineCameraActor`、`EditorUtilitySubsystem`
> - **可能需要手动启用**：**Camera Calibration**（提供 `LensFile`）、**Level Sequence Editor**（提供 `LevelSequence`，多数项目默认开启但并非保证）
>
> UI 里 Prerequisites 区域会列出所有项，MISSING 的按各自 hint 去 **Edit → Plugins** 启用并重启。

---

## 2. 使用流程

所有操作在 UI 面板中完成，无需 Python 控制台。

### 2.1 加载 CSV

点击 **Browse...** 选择 Disguise Designer CSV Dense 文件。CSV Preview 区域自动显示：
- 帧数、焦距范围、时码范围、传感器宽度
- 自动检测的帧率（FPS SpinBox 设为 0 即使用自动检测值）

### 2.2 验证坐标映射

> `config.py` 中的轴映射是初始猜测，**首次使用必须验证**。

1. 在 **Frame** SpinBox 选择一个特征帧（摄影机在已知位置的帧）
2. 对比 **Designer** 原始坐标和 **UE** 转换坐标是否合理
3. 点击 **Spawn Test Camera** — 在该帧位置生成临时摄影机，视口自动 Pilot 到摄影机视角
4. 在视口中目视对比：位置是否正确、朝向有没有镜像或 180° 旋转

### 2.3 调整轴映射（如需要）

如果视口中的画面与 Designer 不一致：

1. 在 **Axis Mapping** 区域修改 ComboBox（源轴）和 SpinBox（缩放系数）
2. 点击 **Apply Mapping** — 坐标预览立即刷新
3. 再次 **Spawn Test Camera** 验证
4. 反复迭代直到匹配

**常见调整：**

| 现象 | 修复 |
|------|------|
| 前后反了 | 翻转 UE.X 的 scale 符号 |
| 左右反了 | 翻转 UE.Y 的 scale 符号 |
| 上下反了 | 翻转 UE.Z 的 scale 符号 |
| 轴互换了 | 交换对应 ComboBox 的源轴选择 |
| 旋转方向反了 | 翻转对应 Rotation 的 scale 符号 |

确认正确后点击 **Save to config.py** 持久化。

### 2.4 导入

点击 **Import** 执行完整流水线：CSV → LensFile → CineCameraActor → LevelSequence。

Results 区域显示验证报告（FOV 误差、异常帧检测等）。

### 2.5 验证与渲染

- **Open Sequencer** — 播放 LevelSequence，目视检查摄影机轨迹
- **Open Movie Render Queue** — 打开 MRQ 进行最终渲染

---

## 3. 日常使用

每次打开 UE 项目后：点工具栏 **VPTool** 按钮 → UI 面板弹出 → 加载 `BP_PostRenderToolWidget`、spawn 编辑器 tab、绑定 Python callback。

**面板意外关闭时：** 再次点击 **VPTool** 按钮即可重开。

> 在 Python Console 重开要用 `from post_render_tool.widget_builder import open_widget; open_widget()`（toolbar 按钮执行的正是这行）。**不要**第二次敲 `import init_post_render_tool` — Python 会返回缓存的模块而不重新执行 `launch_tool()`。

**修改 Python 代码后热重载（无需重启 UE）：**
```python
import importlib
import post_render_tool.widget as w
import post_render_tool.widget_builder as wb
importlib.reload(w); importlib.reload(wb)
wb.rebuild_widget()
```

> **注意：** Blueprint 资产 `BP_PostRenderToolWidget` 随 plugin 一起提交到版本控制，团队成员 `git pull` / `p4 sync` 就能拿到同一份。不要在 Content Browser 里随便删除，否则要按 1.3 重新创建。
>
> **C++ UPROPERTY 变更**（在 `PostRenderToolWidget.h` 里增/删/改 BindWidget 属性）**不支持 Live Coding**，必须关闭 Editor 完整重编 plugin，然后重新 compile Blueprint。
>
> **C++ 模块启动逻辑变更**（`PostRenderToolModule.cpp` 的 `StartupModule` / toolbar 注册）同样**不支持 Live Coding**。新增或修改 toolbar 按钮需关闭 Editor 完整 rebuild plugin 后再启动。

---

## 4. 备注

### 轴映射

- **Apply Mapping** — 仅内存生效，重启 UE 后恢复为 config.py 中的值
- **Save to config.py** — 持久化到磁盘（原子写入 + .bak 备份），下次启动自动加载
- 建议流程：反复 Apply + Spawn Test Camera 迭代 → 确认正确 → Save

### Widget 管理

```python
from post_render_tool.widget_builder import open_widget, rebuild_widget, delete_widget

open_widget()      # 加载 BP_PostRenderToolWidget + spawn tab + 绑定 callback
rebuild_widget()   # 重新打开（释放缓存 UI 引用，不删 Blueprint 资产）
delete_widget()    # 销毁性：删除 plugin-shipped Blueprint 资产——正常情况下不应调用
```

### 故障排查

| 错误 | 原因 | 解决 |
|------|------|------|
| Plugins 窗口里看不到 "VP Post-Render Tool" | plugin 目录没放在 `<UEProject>/Plugins/` 下 | 检查路径，确认 `PostRenderTool.uplugin` 存在 |
| UE 启动时提示 "module missing / rebuild?" | 首次编译未完成 | 点 Yes，等 UBT 编译 |
| UBT 编译失败 | 缺 C++ 工具链 | 装 Xcode（macOS）或 Visual Studio 2022（Windows），重试 |
| 工具栏上看不到 **VPTool** 按钮 | plugin 未启用 / UBT 未 rebuild / Editor 未重启 | 确认 plugin 绿色启用，完全关闭 Editor 后触发一次 rebuild，重开 |
| 点 **VPTool** 按钮无反应，日志提示 `Python plugin unavailable` | `PythonScriptPlugin` 未加载 | 确认 `.uplugin` 里 `PythonScriptPlugin` enabled，或在 Edit → Plugins 手动启用并重启 |
| Prerequisites 显示 MISSING | 对应插件未启用 / 未内建 | 按各项 hint 去 Edit → Plugins 启用并重启（常见手动项：**Camera Calibration** → `LensFile`；**Level Sequence Editor** → `LevelSequence`）。`PythonScriptPlugin` / `EditorScriptingUtilities` 已随 PostRenderTool 通过 `.uplugin` 自动启用，若仍显示 MISSING 说明依赖未生效，检查 plugin 版本与完整性 |
| `ModuleNotFoundError: post_render_tool` | plugin 未启用或 Python path 未挂载 | 确认 plugin 在 Plugins 窗口里是绿色的，重启编辑器 |
| Blueprint compile 报 `A required widget binding "X" of type Y was not found` | Blueprint 里缺少对应控件或类型不符 | 在 Designer 里添加/改类型，按 `docs/bindwidget-contract.md` 对照 |
| `'btn_browse' UPROPERTY is None` | Blueprint 没有用当前 C++ class 重新 compile | 打开 `BP_PostRenderToolWidget`，Compile，然后重启工具 |
| UI 打开但按钮点击没反应 | callback 未绑定（热重载副作用）| `wb.rebuild_widget()` 或重启 tab |
| Import 后摄影机位置/朝向不对 | 轴映射未校准 | 回到 2.2 验证坐标映射 |
| `RuntimeError: LensFile` | Camera Calibration 插件未启用 | 启用插件并重启 |
