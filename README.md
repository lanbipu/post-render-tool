# VP Post-Render Tool

Disguise Designer Shot Recorder CSV Dense → UE 5.7 CineCameraActor + LensFile + LevelSequence

一键将虚拟制片现场录制的摄影机数据导入 Unreal Engine，用于离线重渲染。

## Problem

VP/XR 拍摄后，后期合成师需要在 UE 中对 CG 画面进行离线重渲染，要求 UE 中的摄影机与现场完全一致。当前从 Disguise Designer 导出的 CSV 数据到 UE 重渲染没有自动化链路，手动配置每个镜头需要 2-4 小时且易出错。

## Solution

本工具自动完成：
- **CSV 解析** — 自动识别 camera 前缀，提取全部物理镜头参数
- **坐标系转换** — Designer Y-up (m) → UE Z-up (cm)，可配置轴映射
- **Lens File 生成** — 按焦距采样，自动计算 FxFy / ImageCenter / k1k2k3
- **CineCameraActor 创建** — 配置 Filmback + LensComponent + 畸变
- **Level Sequence 动画** — 逐帧写入 Transform、Focal Length、Aperture、Focus Distance
- **验证报告** — FOV 交叉校验 + 异常帧检测

## Quick Start

### Prerequisites

UE 5.7 项目中启用以下插件：
- Python Editor Script Plugin
- Editor Scripting Utilities
- Camera Calibration

### Installation

将 `Content/Python/` 目录复制到你的 UE 项目 `Content/Python/` 下。

### Usage

**方式 1：Python Console（推荐先用这种方式验证）**

在 UE Output Log 中执行：

```python
# 检查前置条件
py init_post_render_tool

# 一键导入
from post_render_tool.pipeline import run_import
result = run_import(r"C:\path\to\shot1_take5_dense.csv", fps=24.0)
print(result.report.format_report())
```

**方式 2：Blueprint UI**

Plugin 源码里**不包含** `BP_PostRenderToolWidget.uasset`（UE 5.7 的 `UWidgetBlueprint::WidgetTree` 对 Python 反射不可见，无法自动生成，team 决定 Designer 手工搭建）。分布流程：

- **Bootstrap（仅一次）**：项目第一个部署者按 `docs/deployment-guide.md` §1.3 在 UMG Designer 里创建 BP、满足 BindWidget contract、Compile 通过、保存、`git add` / `p4 add` 该 `.uasset` 并提交。
- **后续所有部署**：`git pull` / `p4 sync` 就能拿到同一份 `.uasset`，**不需要**重新搭建。
- **BP 损坏 / 本地误删**：先尝试 sync 回来；sync 不到（比如别人也删了、depot 里没有）才按 §1.3 重新 bootstrap 并重新提交。

## Project Structure

```
Content/Python/
├── init_post_render_tool.py          # 前置条件检查
└── post_render_tool/
    ├── config.py                     # 配置（坐标映射、阈值）
    ├── csv_parser.py                 # CSV Dense 解析
    ├── coordinate_transform.py       # 坐标系转换
    ├── lens_file_builder.py          # .ulens 生成
    ├── camera_builder.py             # CineCameraActor 创建
    ├── sequence_builder.py           # LevelSequence + 动画曲线
    ├── validator.py                  # FOV 校验 + 异常检测
    ├── pipeline.py                   # 流水线编排
    ├── ui_interface.py               # Blueprint UI 接口
    └── tests/
        ├── test_csv_parser.py        # 8 tests
        ├── test_coordinate_transform.py  # 7 tests
        ├── test_validator.py         # 11 tests
        └── test_integration_ue.py    # UE 内集成测试
```

## Testing

纯 Python 单测（无需 UE）：

```bash
cd Content/Python
python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -v
python -m unittest discover -s post_render_tool/tests -p "test_v*.py" -v
```

UE 内集成测试：

```python
py exec(open('Content/Python/post_render_tool/tests/test_integration_ue.py').read())
```

## Configuration

编辑 `config.py` 调整：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `POSITION_MAPPING` | 坐标轴映射（需实测验证） | Designer Z→UE X, X→Y, Y→Z |
| `ROTATION_MAPPING` | 旋转轴映射 | 需实测验证 |
| `ASSET_BASE_PATH` | 资产保存路径 | `/Game/PostRender` |
| `FOV_ERROR_THRESHOLD_DEG` | FOV 校验警告阈值 | 0.05° |
| `FOCAL_LENGTH_GROUP_TOLERANCE_MM` | 焦距分组容差 | 0.1mm |

> **Important:** `POSITION_MAPPING` 和 `ROTATION_MAPPING` 的默认值是初始猜测，必须用真实数据在 UE 视口中验证后调整。

## Output

导入后生成：
1. **Lens File** (`.ulens`) — 畸变标定数据
2. **CineCameraActor** — Filmback + LensComponent 已配置
3. **Level Sequence** — 完整动画曲线，保留原始帧 cadence

资产保存在 `/Content/PostRender/{CSV文件名}/`。

## Limitations (v1)

- 仅支持单相机 CSV
- 仅支持 UE 5.7
- 不支持 Anamorphic 镜头
- 不自动触发 Movie Render Queue
- 坐标转换规则需手动验证

## License

MIT
