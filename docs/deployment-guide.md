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
│   │       ├── widget.py
│   │       ├── widget_builder.py
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

```python
import init_post_render_tool
```

4. 检查输出，预期结果：

```
==================================================
VP Post-Render Tool — Initializing...
==================================================
  OK: Python Editor Script Plugin (running Python now)
  OK: Editor Scripting Utilities
  OK: Camera Calibration (LensFile available)
  OK: CineCameraActor
  OK: LevelSequence
  OK: EditorUtilitySubsystem
All prerequisites met.
--------------------------------------------------
Opening VP Post-Render Tool UI...
[widget_builder] Widget Blueprint created: /Game/PostRenderTool/EUW_PostRenderTool
[widget_builder] Widget tab opened.
==================================================
VP Post-Render Tool ready.
==================================================
```

**工具 UI 面板会自动弹出。** 如果看到 `MISSING`，回到 2.1 启用对应插件。

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

## Step 5: Blueprint UI 使用说明

Blueprint UI 在 Step 2.2 运行 `import init_post_render_tool` 时已自动创建并打开，无需手动搭建。

### 5.1 UI 功能

| 控件 | 功能 |
|------|------|
| **Browse...** | 打开文件选择器，选取 Disguise Designer CSV Dense 文件 |
| **CSV Preview** | 显示帧数、焦距范围、时码、传感器宽度 |
| **FPS SpinBox** | 设置帧率（0 = 从 CSV 自动检测，建议保持默认） |
| **Import** | 执行完整导入流水线（LensFile + CineCameraActor + LevelSequence） |
| **Open Sequencer** | 在 Sequencer 编辑器中打开导入的 LevelSequence |
| **Open Movie Render Queue** | 打开 MRQ 窗口进行渲染 |

### 5.2 日常使用

每次打开 UE 项目后，在 Python 控制台运行：

```python
import init_post_render_tool
```

如果 widget 已存在，会直接打开而不会重复创建。

### 5.3 Widget 管理命令

```python
from post_render_tool.widget_builder import open_widget, rebuild_widget, delete_widget

open_widget()      # 创建（如不存在）并打开
rebuild_widget()   # 删除 + 重建 + 打开（修复异常时使用）
delete_widget()    # 仅删除 widget 资产
```

### 5.4 手动打开 Widget

如果 UI 面板意外关闭：
1. Content Browser → 导航到 `Content/PostRenderTool/`
2. 右键 `EUW_PostRenderTool` → **Run Editor Utility Widget**

> **Tip:** 可以将 Widget 添加到工具栏。菜单 **Tools → Run Editor Utility Widget** → 选择 `EUW_PostRenderTool`。
