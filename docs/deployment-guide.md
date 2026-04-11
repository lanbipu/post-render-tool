# VP Post-Render Tool 部署与使用指南

## 1. 安装

### 1.1 复制文件到 UE 项目

将本仓库的 `Content/Python/` 目录复制到 UE 项目中：

```bash
# macOS / Linux
cp -r /path/to/post-render-tool/Content/Python/ /path/to/MyVPProject/Content/Python/

# Windows PowerShell
Copy-Item -Recurse "C:\path\to\post-render-tool\Content\Python\" "C:\path\to\MyVPProject\Content\Python\"
```

最终结构：`MyVPProject/Content/Python/init_post_render_tool.py` + `post_render_tool/` 包。

### 1.2 启用插件

打开 UE 5.7 Editor → **Edit → Plugins**，搜索并启用：

| 插件 | 搜索关键词 |
|------|-----------|
| Python Editor Script Plugin | `Python` |
| Editor Scripting Utilities | `Editor Scripting` |
| Camera Calibration | `Camera Calibration` |

启用后重启编辑器。

### 1.3 启动工具

Output Log 切换到 **Python** 模式，输入：

```python
import init_post_render_tool
```

UI 面板自动弹出，Prerequisites 区域显示所有插件状态。如有 MISSING，回到 1.2 启用对应插件。

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

每次打开 UE 项目后启动工具：

```python
import init_post_render_tool
```

Widget 已存在时直接打开，不会重复创建。

**面板意外关闭时：** 再次执行 `import init_post_render_tool` 即可重新打开。

> **注意：** Widget 仅存在于内存中（PythonGeneratedClass 无法被 UE 序列化到磁盘）。
> 关闭编辑器时如果弹出"保存更改"对话框，对 PostRenderTool 相关资产选择 **Don't Save**。

---

## 4. 备注

### 轴映射

- **Apply Mapping** — 仅内存生效，重启 UE 后恢复为 config.py 中的值
- **Save to config.py** — 持久化到磁盘（原子写入 + .bak 备份），下次启动自动加载
- 建议流程：反复 Apply + Spawn Test Camera 迭代 → 确认正确 → Save

### Widget 管理

```python
from post_render_tool.widget_builder import open_widget, rebuild_widget, delete_widget

open_widget()      # 创建（如不存在）并打开
rebuild_widget()   # 删除 + 重建 + 打开（修复异常时使用）
delete_widget()    # 仅删除 widget 资产
```

### 故障排查

| 错误 | 原因 | 解决 |
|------|------|------|
| Prerequisites 显示 MISSING | 插件未启用 | Edit → Plugins 启用对应插件，重启编辑器 |
| `ModuleNotFoundError: post_render_tool` | 文件位置不对 | 确认文件在 `Content/Python/post_render_tool/` 下 |
| Import 后摄影机位置/朝向不对 | 轴映射未校准 | 回到 2.2 验证坐标映射 |
| `RuntimeError: LensFile` | Camera Calibration 插件未启用 | 启用插件并重启 |
