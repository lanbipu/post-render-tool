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

### 1.3 创建 Widget 模板（一次性）

UE 5.7 的 `EditorUtilityWidgetBlueprintFactory` 自动创建的根 widget `bIsVariable=false`，编译后的 UPROPERTY 不带 `CPF_BlueprintVisible`，Python 完全无法访问。所以必须**手动创建一次**模板：

1. **Content Browser** → 进入 `/Game/PostRenderTool/`（不存在就先建文件夹）
2. 右键 → **Editor Utilities** → **Editor Utility Widget**
3. 父类选 **`EditorUtilityWidget`**（native，不是自定义子类）
4. 命名 **`EUW_PostRenderTool`**
5. 双击打开 Widget Designer
6. Palette 拖一个 **Vertical Box** 到 Hierarchy 作为根
7. 选中 Vertical Box，在 Details 面板顶部：
   - 重命名为 **`RootPanel`**
   - **勾选 "Is Variable"**
8. **Compile** (Ctrl+B) → **Save** (Ctrl+S)
9. 关闭 Widget Designer

完整说明见 `docs/blueprint-ui-setup.md`。

### 1.4 启动工具

Output Log 切换到 **Python** 模式，输入：

```python
import init_post_render_tool
```

UI 面板自动弹出，Prerequisites 区域显示所有插件状态。如有 MISSING，回到 1.2 启用对应插件。

如果出现 `Template Blueprint not found` 错误，回到 1.3 创建模板。

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

加载 1.3 创建的模板 Blueprint，spawn 编辑器 tab，注入 Python UI。

**面板意外关闭时：** 再次执行 `import init_post_render_tool` 即可重新打开。

> **注意：** 模板 Blueprint (`EUW_PostRenderTool`) 是用户手动创建的真实 asset，会和项目一起持久化。不要在 Content Browser 里删除它，否则需要按 1.3 重新创建。

---

## 4. 备注

### 轴映射

- **Apply Mapping** — 仅内存生效，重启 UE 后恢复为 config.py 中的值
- **Save to config.py** — 持久化到磁盘（原子写入 + .bak 备份），下次启动自动加载
- 建议流程：反复 Apply + Spawn Test Camera 迭代 → 确认正确 → Save

### Widget 管理

```python
from post_render_tool.widget_builder import open_widget, rebuild_widget, delete_widget

open_widget()      # 加载模板 + spawn tab + 注入 UI
rebuild_widget()   # 重新打开（释放缓存 UI 引用，不删模板）
delete_widget()    # 销毁性：删除模板 asset，下次 open_widget() 前需按 1.3 重建
```

### 故障排查

| 错误 | 原因 | 解决 |
|------|------|------|
| Prerequisites 显示 MISSING | 插件未启用 | Edit → Plugins 启用对应插件，重启编辑器 |
| `ModuleNotFoundError: post_render_tool` | 文件位置不对 | 确认文件在 `Content/Python/post_render_tool/` 下 |
| `Template Blueprint not found` | 模板未创建或被删除 | 按 1.3 步骤手动创建 `EUW_PostRenderTool` |
| `Template is missing the 'RootPanel' variable` | 根 widget 未命名为 `RootPanel` 或未勾选 Is Variable | 在 Widget Designer 中修正后 Compile + Save |
| `'RootPanel' is a CanvasPanel, expected VerticalBox` | 模板根 widget 类型错误 | 替换为 Vertical Box，重命名 + 勾选 Is Variable |
| Import 后摄影机位置/朝向不对 | 轴映射未校准 | 回到 2.2 验证坐标映射 |
| `RuntimeError: LensFile` | Camera Calibration 插件未启用 | 启用插件并重启 |
