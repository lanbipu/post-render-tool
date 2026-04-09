# VP Post-Render Tool 部署与验证指南

## Step 1: 部署文件到 UE 项目

### 1.1 定位你的 UE 项目目录

找到你的 UE 5.7 项目根目录，通常结构如下：

```
MyVPProject/
├── MyVPProject.uproject
├── Content/
│   ├── Maps/
│   ├── Materials/
│   └── ...             ← 这里还没有 Python/ 目录
├── Config/
└── Source/
```

### 1.2 复制 Python 脚本

将本仓库的 `Content/Python/` 整个目录复制到 UE 项目中：

**macOS / Linux:**
```bash
cp -r /path/to/post-render-tool/Content/Python/ /path/to/MyVPProject/Content/Python/
```

**Windows (PowerShell):**
```powershell
Copy-Item -Recurse "C:\path\to\post-render-tool\Content\Python\" "C:\path\to\MyVPProject\Content\Python\"
```

复制完成后，UE 项目结构应该是：

```
MyVPProject/
├── Content/
│   ├── Python/
│   │   ├── init_post_render_tool.py
│   │   └── post_render_tool/
│   │       ├── __init__.py
│   │       ├── config.py
│   │       ├── csv_parser.py
│   │       ├── coordinate_transform.py
│   │       ├── lens_file_builder.py
│   │       ├── camera_builder.py
│   │       ├── sequence_builder.py
│   │       ├── validator.py
│   │       ├── pipeline.py
│   │       ├── ui_interface.py
│   │       └── tests/
│   │           ├── test_csv_parser.py
│   │           ├── test_coordinate_transform.py
│   │           ├── test_validator.py
│   │           └── test_integration_ue.py
│   └── ...
```

### 1.3 同时复制参考 CSV（可选）

如果需要用参考数据做测试：

```bash
cp "/path/to/post-render-tool/reference/shot 1_take_5_dense.csv" /path/to/MyVPProject/
```

---

## Step 2: 启用必要插件并检查前置条件

### 2.1 启用插件（如果尚未启用）

1. 打开 UE 5.7 Editor，加载你的项目
2. 菜单栏 → **Edit → Plugins**
3. 搜索并启用以下插件（勾选 Enabled）：

| 插件名 | 搜索关键词 | 作用 |
|--------|-----------|------|
| Python Editor Script Plugin | `Python` | Python 脚本支持 |
| Editor Scripting Utilities | `Editor Scripting` | 编辑器自动化 API |
| Camera Calibration | `Camera Calibration` | LensFile / LensComponent 支持 |

4. 点击 **Restart Now** 重启编辑器

### 2.2 运行前置条件检查

1. 编辑器重启后，打开 **Output Log**：菜单栏 → **Window → Developer Tools → Output Log**
2. 在 Output Log 底部的输入框中，确认左侧下拉选择的是 `Cmd`，将其切换为 `Python`
3. 输入以下命令并回车：

```
init_post_render_tool
```

4. 检查输出，预期结果：

```
  OK: Python Editor Script Plugin
  OK: Editor Scripting Utilities
  OK: Camera Calibration
All prerequisites met. VP Post-Render Tool ready.
```

如果看到 `MISSING`，回到 2.1 启用对应插件。

---

## Step 3: 运行集成测试

### 3.1 准备测试数据

集成测试需要参考 CSV 文件。打开 `Content/Python/post_render_tool/tests/test_integration_ue.py`，确认 `CSV_PATH` 指向你的参考 CSV 文件的实际路径。

你可以在 UE Python 控制台中直接修改路径：

```python
import post_render_tool.tests.test_integration_ue as t
t.CSV_PATH = r"C:\MyVPProject\shot 1_take_5_dense.csv"
t.run_all()
```

### 3.2 运行测试

在 Output Log（Python 模式）中输入：

```python
exec(open('Content/Python/post_render_tool/tests/test_integration_ue.py').read())
```

> **注意：** 如果路径报错，使用绝对路径：
> ```python
> exec(open(r'C:\MyVPProject\Content\Python\post_render_tool\tests\test_integration_ue.py').read())
> ```

### 3.3 预期输出

```
=== Integration Tests ===
PASS: CSV parse
  Designer: (0.0022488, 0.998591, -6.00113) m
  UE: (600.1, 0.2, 99.9) cm
PASS: Coordinate sanity
PASS: Full pipeline
=== All Integration Tests Passed ===
```

### 3.4 测试失败排查

| 错误 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: post_render_tool` | Python 路径未包含 Content/Python | 确认文件在 `Content/Python/post_render_tool/` 下 |
| `FileNotFoundError` on CSV | CSV 路径不对 | 修改 `CSV_PATH` 为绝对路径 |
| `RuntimeError: Camera Calibration` | 插件未启用 | 回到 Step 2 启用 |
| `RuntimeError: LensFile 资产创建失败` | 资产路径问题 | 检查 config.py 的 `ASSET_BASE_PATH` |

---

## Step 4: 验证坐标转换（关键步骤）

这是最重要的步骤。`config.py` 中的坐标轴映射是初始猜测，必须用真实数据验证。

### 4.1 准备验证环境

1. 在 Designer 中打开你录制 CSV 的同一场景
2. 在 UE 中打开对应的虚拟制片场景
3. 找到一个特征明显的帧（例如摄影机在已知位置），记录 Designer 中的坐标值

### 4.2 手动测试单帧坐标

在 UE Python 控制台中：

```python
from post_render_tool.csv_parser import parse_csv_dense
from post_render_tool.coordinate_transform import transform_position, transform_rotation

# 解析你的实际 CSV
csv = parse_csv_dense(r"C:\path\to\your_actual_shot.csv")

# 查看第一帧的原始数据
f = csv.frames[0]
print(f"Designer Position: ({f.offset_x}, {f.offset_y}, {f.offset_z}) m")
print(f"Designer Rotation: ({f.rotation_x}, {f.rotation_y}, {f.rotation_z}) deg")

# 查看转换后的 UE 坐标
ue_pos = transform_position(f.offset_x, f.offset_y, f.offset_z)
ue_rot = transform_rotation(f.rotation_x, f.rotation_y, f.rotation_z)
print(f"UE Position: ({ue_pos[0]:.1f}, {ue_pos[1]:.1f}, {ue_pos[2]:.1f}) cm")
print(f"UE Rotation: pitch={ue_rot[0]:.2f}, yaw={ue_rot[1]:.2f}, roll={ue_rot[2]:.2f} deg")
```

### 4.3 在 UE 视口中目视对比

1. 在 UE 场景中手动创建一个临时 CineCameraActor
2. 将上面计算出的 UE Position / Rotation 手动输入到 Transform 面板
3. 切换到该摄影机视角（Pilot），检查画面是否与 Designer 中一致：
   - 位置是否正确（前后/左右/上下）
   - 朝向是否正确（有没有镜像或 180° 旋转）

### 4.4 调整轴映射

如果位置或方向不对，修改 `Content/Python/post_render_tool/config.py`：

```python
# 默认映射（初始猜测）
POSITION_MAPPING = {
    "x": (2, -100.0),  # UE.X ← -Designer.Z × 100
    "y": (0, 100.0),   # UE.Y ← Designer.X × 100
    "z": (1, 100.0),   # UE.Z ← Designer.Y × 100
}
```

**常见调整场景：**

| 现象 | 可能的修复 |
|------|-----------|
| 摄影机前后反了 | 翻转 UE.X 的 scale 符号：`(2, -100.0)` → `(2, 100.0)` |
| 摄影机左右反了 | 翻转 UE.Y 的 scale 符号 |
| 摄影机上下反了 | 翻转 UE.Z 的 scale 符号 |
| X/Z 轴互换了 | 交换 source_axis_index：如 `"x": (2, ...)` → `"x": (0, ...)` |
| 旋转方向反了 | 翻转对应 ROTATION_MAPPING 的 scale 符号 |
| Pitch/Yaw 互换 | 交换 ROTATION_MAPPING 的 source_axis_index |

### 4.5 迭代验证

修改 config.py 后，不需要重启 UE。在 Python 控制台中重新加载模块：

```python
import importlib
import post_render_tool.config as cfg
importlib.reload(cfg)
import post_render_tool.coordinate_transform as ct
importlib.reload(ct)

# 重新测试
ue_pos = ct.transform_position(f.offset_x, f.offset_y, f.offset_z)
print(f"UE Position: ({ue_pos[0]:.1f}, {ue_pos[1]:.1f}, {ue_pos[2]:.1f}) cm")
```

反复调整直到位置和朝向完全匹配。

### 4.6 最终确认

坐标转换确认正确后，用完整 CSV 运行一次导入：

```python
from post_render_tool.pipeline import run_import
result = run_import(r"C:\path\to\your_actual_shot.csv", fps=24.0)
print(result.report.format_report())
```

在 Sequencer 中播放 Level Sequence，目视检查摄影机运动轨迹是否与 Designer 中一致。

---

## Step 5: 创建 Blueprint UI（可选）

如果你想要 GUI 操作面板而不是每次手打 Python 命令，按以下步骤创建。

### 5.1 创建 Editor Utility Widget

1. 在 Content Browser 中，导航到 `Content/` 目录
2. 右键 → **Editor Utilities → Editor Utility Widget**
3. 命名为 `EUW_PostRenderTool`
4. 双击打开 Widget Editor

### 5.2 搭建 UI 布局

在 Designer 面板中，从 Palette 拖入以下控件：

**文件选择区域：**
- `Horizontal Box`
  - `Text Block` → Text: "CSV File:"
  - `Text Block` (命名 `txt_FilePath`) → Text: "No file selected"（灰色）
  - `Button` (命名 `btn_Browse`) → 子 Text: "Browse..."

**帧率设置：**
- `Horizontal Box`
  - `Text Block` → Text: "FPS:"
  - `Spin Box` (命名 `spn_FPS`) → Min: 1, Max: 120, Value: 24
  - `Text Block` (命名 `txt_DetectedFPS`) → Text: "Auto: --"

**CSV 预览区域：**
- `Vertical Box`（加背景 Border）
  - `Text Block` → "── CSV Preview ──"
  - `Text Block` (命名 `txt_FrameCount`)
  - `Text Block` (命名 `txt_FocalRange`)
  - `Text Block` (命名 `txt_Timecode`)
  - `Text Block` (命名 `txt_SensorWidth`)

**操作按钮：**
- `Button` (命名 `btn_Import`) → 子 Text: "Import"（大号，强调色）

**结果显示：**
- `Multi Line Editable Text` (命名 `txt_Results`) → Is Read Only: true

**快捷按钮：**
- `Horizontal Box`
  - `Button` (命名 `btn_OpenSequencer`) → "Open Sequencer"
  - `Button` (命名 `btn_OpenMRQ`) → "Open Movie Render Queue"

### 5.3 连接 Blueprint 事件

切换到 Graph 面板，为每个按钮创建 OnClicked 事件：

**btn_Browse:**
1. 添加 `Execute Python Command` 节点
2. Command: `from post_render_tool.ui_interface import cmd_browse; cmd_browse()`

**btn_Import:**
1. 添加 `Execute Python Command` 节点
2. Command: 需要拼接 csv_path 和 fps 变量
3. 格式: `from post_render_tool.ui_interface import cmd_import; cmd_import(r'<path>', <fps>)`

**btn_OpenSequencer:**
1. `Execute Python Command` → `from post_render_tool.ui_interface import open_sequencer; open_sequencer()`

**btn_OpenMRQ:**
1. `Execute Python Command` → `from post_render_tool.ui_interface import open_movie_render_queue; open_movie_render_queue()`

### 5.4 运行 Widget

1. 在 Content Browser 中右键 `EUW_PostRenderTool`
2. 选择 **Run Editor Utility Widget**
3. Widget 面板出现，可以开始使用

> **Tip:** 可以将 Widget 添加到工具栏。在 Level Editor 中：菜单 **Tools → Run Editor Utility Widget** → 选择 `EUW_PostRenderTool`。
