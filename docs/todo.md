# Todo

## UI 启动机制改进

**背景**：当前唯一启动方式是在 UE Python Console 手动执行 `import init_post_render_tool`。目标是提供更友好的启动方式，不依赖命令行操作。

### 选项分析（已决策）

| 方案 | 描述 | 状态 |
|------|------|------|
| A. Project Settings Startup Scripts | 每个 UE 项目手动配置一次，Editor 启动自动弹出 UI | 可行，无需改代码 |
| B. C++ StartupModule 自动启动 | 插件加载后自动 `import init_post_render_tool`，UI 自动弹出 | 可行，随插件分发 |
| C. Level Editor 工具栏按钮 | 无自动弹出；工具栏点击触发 `open_widget()`，关闭后可重复点击 | **待实现** ✅ 推荐 |

> **选定方案 C**：用户不希望 Editor 启动时自动弹出 UI，希望在需要时从工具栏一键打开。

### 实现任务（方案 C）

- [ ] C++ `StartupModule()` 注册 Level Editor toolbar extension
- [ ] Toolbar 按钮点击回调：调用 `IPythonScriptPlugin::ExecPythonCommand("from post_render_tool.widget_builder import open_widget; open_widget()")`
- [ ] `PostRenderTool.Build.cs` 添加依赖：`PythonScriptPlugin`、`LevelEditor`、`Slate`、`SlateCore`
- [ ] 按钮图标（可先用文字 label "VPTool"，后续替换自定义 icon）
- [ ] 验证：关闭 UI 后再次点击工具栏按钮能正常重开

### 注意事项

- `spawn_and_register_tab()` 是"注册 + 显示"合一，UE Python API 无单独"只注册不显示"接口；工具栏按钮方案完全绕开这个限制
- Python 回调绑定在 `open_widget()` 内完成，每次点击都重新绑定，关闭后再开不会丢失功能
