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

### 1.3 首次 Bootstrap：创建 Blueprint 资产并手动搭建 UI（**只做一次**，不是每个部署都要做）

> **谁应该走这一节：**
> - **项目里还没有人做过 BP 时**（全新仓库 / 从未 bootstrap）→ 第一个部署者按本节 Step 1 → Step 7 搭建并提交 `.uasset`，团队里**只需要一个人做这一次**。
> - **BP 已经在 depot 里**（另一位同事已经 bootstrap 过）→ 不要走本节！直接 `git pull` / `p4 sync` 就能拿到同一份 `.uasset`，enable plugin 后工具即刻可用。
> - **BP 本地被误删 / 损坏**（depot 还有）→ `git restore` / `p4 sync -f` 恢复即可，同样不需要走本节。
>
> **判断自己处于哪种情况：** Editor 打开 UI 后如果空白面板 + Output Log 一大片 `A required widget binding "<name>" of type <type> was not found.` → 说明本地没拿到 BP。先 sync 试试；sync 不到再回本节 bootstrap。
>
> **为什么只能手动搭建（决策背景，一次性记录）：** UE 5.7 的 `UWidgetBlueprint::WidgetTree` 在源码里是 `UPROPERTY(Instanced)`，既没有 `BlueprintReadable` 也没有 `EditAnywhere` flag，按 `PyGenUtil.cpp::IsScriptExposedProperty` 规则对 Python 反射完全不可见 —— 纯 Python 脚本无法触及 widget tree，`get_editor_property("widget_tree")` 会抛 "Failed to find property"。写 C++ `UBlueprintFunctionLibrary` 桥接虽然技术上可行，但要完整还原 Figma 设计（容器嵌套 + slot padding + widget styling）需要 600~1000 行 Python + 200~400 行 C++ helper，而且每次 UE 版本升级都要跟 widget slot API 漂移，投入产出比低于 Designer 可视化调整 + 提交 `.uasset` 到版本控制 + 团队 sync 共享这个方案。所以本项目明确选择 bootstrap-once + sync-forever 的路径，决策详见 commit `bd140d7`。

**Step 1：创建 Blueprint 外壳**

1. 启动 Editor，**Content Browser** → 左侧 "Plugins" 区 → **VP Post-Render Tool Content** → `Blueprints/`
2. 右键 → **Blueprint Class** → 底部 "ALL CLASSES" 搜 `PostRenderToolWidget`
3. 选中 `UPostRenderToolWidget` → **Select**
4. 命名 **`BP_PostRenderToolWidget`**（必须一字不差，C++ 与 Python binder 都按这个名字查）
5. 双击进 Widget Designer

**Step 2：替换根节点为 VerticalBox**

6. Hierarchy 面板删除默认 `CanvasPanel_0`
7. Palette 拖一个 **Vertical Box** 到 Hierarchy 作为新根，命名 `RootPanel`

**Step 3：按 BindWidget contract 拖 33 个必需控件**

8. 另开 `docs/bindwidget-contract.md`，对照 "Required widgets (33)" 表
9. 每一行对应一个 widget：
   - 拖 `Type` 列指定的控件类型到 `RootPanel` 内：
     - `UButton` → Palette 的 **Button**
     - `UTextBlock` → **Text**
     - `USpinBox` → **Spin Box**
     - `UComboBoxString` → **Combo Box (String)**
     - `UMultiLineEditableText` → **Editable Text (Multi-Line)**
   - 右侧 Details 面板顶部把 widget 命名为 `Name` 列的字符串（例如 `btn_browse`、`txt_file_path`）
   - **名字必须一字不差** —— 大小写、下划线都不能错，C++ UPROPERTY `meta=(BindWidget)` 精确匹配
   - **保持 "Is Variable" 勾选**（默认已勾，不要取消）—— Python binder 依赖它
10. 视觉布局第一次可以扁平摆放 —— BindWidget 合约只认 widget 名字 + 类型，不看嵌套层级。等 compile 通过后再 Step 6 美化

**Step 4（建议）：加 8 个 optional 控件**

11. 同表 "Optional widgets (8)"：`prereq_label_0` ~ `prereq_label_5`、`prereq_summary`、`txt_frame_hint`，都是 `UTextBlock`
12. 缺这些不会让 BP compile 失败，但 UI 里对应功能会静默降级；建议一次加齐

**Step 5：编译 + 保存**

13. 左上角 **Compile**（Ctrl+B）
14. Compiler Results：
    - **通过** → 无红字、"Compile Succeeded" → 下一步
    - **失败** → 每条 `A required widget binding "X" of type Y was not found` 精确指出缺哪个 / 类型不符，按错误补 / 改、再 Compile
15. **Save**（Ctrl+S）

**Step 6：按 Figma 设计美化（可选，但推荐）**

Compile 通过后可以任意重组 Hierarchy 还原 Figma 视觉设计：

- 按 `docs/bindwidget-contract.md` 的 `Section` 列把 41 个 widget 搬进 6 个分组容器（Prerequisites / CSV File / CSV Preview / Coordinate Verification / Axis Mapping / Actions + Results），每组用 `Border` → `VerticalBox` 嵌套
- 颜色 / padding / 字号的参考值可直接看 `Content/Python/post_render_tool/widget_programmatic.py.bak`（旧的 runtime 构建脚本 archived 版本），里面定义了：
  - `_CARD_BG = LinearColor(0.141, 0.141, 0.141)`（card Border BrushColor，对应 `#242424`）
  - `_SUBCARD_BG = LinearColor(0.102, 0.102, 0.102)`（sub-card，对应 `#1A1A1A`）
  - `_ACCENT = LinearColor(0.0, 0.749, 0.647)`（accent `#00BFA5`，用于 section header / primary button）
  - `_CARD_PADDING = Margin(12, 10, 12, 10)`
  - `_SUBCARD_PADDING = Margin(10, 8, 10, 8)`
- **绝对不要改 widget 的 `Name` 或 `Is Variable` 勾选** —— 改了就断 binding，下次启动时 Python 端 `get_editor_property("<name>")` 会返回 None
- Designer 支持的 Figma 原语：纯色块 / padding / Auto Layout / 字体字号 / Alignment / hover-pressed 三态按钮都能 1:1 还原
- Designer **不直接支持**：`border-radius` 圆角、`box-shadow` 阴影、`linear-gradient` 渐变 —— 如 Figma 用到这些，需从 Figma 导出 9-slice PNG 再作为 `SlateBrush` 引用。**本项目当前 Figma 设计是纯色 flat 风格，无以上三件套**，Designer 100% 能还原
- 调完 Compile + Save

**Step 7：提交资产（bootstrap 的关键一步）**

Content Browser 右键 `BP_PostRenderToolWidget` → Source Control submit；或在 git / p4 命令行里 add 该 `.uasset`。**这一步提交是本次 bootstrap 的唯一产物**：资产一旦进 depot，团队其他成员 `git pull` / `p4 sync` 自动拿到同一份，再也不用走 Step 1~6。忘了提交 = 下一个同事还得重做一遍、且你两份 BP 的 GUID 可能冲突。

---

**后续维护（不是每个部署都做，只在下面这几种情况触发）：**

- **C++ 增 / 删 / 改 `UPROPERTY(BindWidget)`**：原始 bootstrap 者（或任何持有写权限的人）在 Designer 里对齐 binding（老的变 unused 可留着不管，新的按 Step 3 拖一个同名 widget），Compile → Save → 提交更新的 `.uasset`。其他同事照常 sync。
- **BP 在 depot 中意外被删 / 损坏**（例如误 `p4 delete`、合并冲突选错）：任何有权恢复的人先从 depot 历史版本回滚；回滚不了才重新走 Step 1~7 bootstrap。
- **BP 仅本地被删 / 损坏 , depot 还完好**：`git restore Content/Blueprints/BP_PostRenderToolWidget.uasset` 或 `p4 sync -f` 强制覆盖本地，**不要**走 Step 1~7。

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

> **注意：** Blueprint 资产 `BP_PostRenderToolWidget` **不在 plugin 源码仓库里**（见 1.3 节开头说明），bootstrap 完成后由**项目仓库**承载。第一个 bootstrap 的人提交一次之后，团队其他成员 `git pull` / `p4 sync` 直接拿、不用自己搭。Content Browser 里随便删了本地 `.uasset` 的情况：depot 里还在就 sync 回来（秒级恢复）；depot 里也没有才按 1.3 重新 bootstrap（几十分钟的手工工作）。
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
delete_widget()    # 销毁性：删除项目仓库里的 Blueprint 资产——不是 plugin 自带的，删了优先 git/p4 sync 回来；sync 不到才按 1.3 重新 bootstrap
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
