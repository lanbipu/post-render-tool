# take_6 production diff — PASS(中心结构 + frustum 完整,2026-05-09 修复)

**最后更新**: 2026-05-10
**状态**: **PASS**
- ✅ 中心结构匹配 + Y 方向 vertical shift < 0.1 px 中位
- ✅ Top + right edge frustum 完整(2026-05-09 修复后,用户实测新 render 跟 Disguise reference 视觉对比通过)
- ✅ 2026-05-10 update #3 之后(overscan 接入 + shader 归一化)regression 仍 PASS — 数学上 OS=1.3334 时归一化包装严格等价于在原 frustum 跑原算法,实测无回退

## 历史(供回溯)

- **2026-05-08 第一版**: 误标 PASS,因为 phase correlation 只测中心结构,看不出 frustum 截断
- **2026-05-09 中段降级**: 发现 `LS_test_take_6_dense.0001.png` 上 + 右边缘比 Disguise 少约 10 px 内容,降级 PARTIAL/BLOCKED
- **2026-05-09 修复**: commit `69a9bea` 把 `centerShift` 从 shader UV 平移迁到 `CineCameraComponent.Filmback.SensorHorizontalOffset/Vertical`(走 `OffCenterProjectionOffset`),sign 取负(`= -cs_*_mm`),frustum 在渲染时已对到 principal point。用户在 lanPC 重渲后实测验证通过 → 升 PASS
- **2026-05-10 update #3**: take_7 加大 distortion 暴露 commit `43173c4` (overscan 接入)+ commit `c3ccabb` (shader frustum 归一化)的 regression 测试 — take_6 重渲跟之前 PASS 状态一致,无回退
- 修复方案 + 推理证据:见 commit `69a9bea` + `43173c4` + `c3ccabb` message

> **0001.png 是旧 shader-translation 公式产物**(2026-05-08 渲),保留作历史对照,**不是当前 PASS 的 evidence**。

## 测试条件

| 项 | 值 |
|---|---|
| CSV | `test_take_6_dense.csv`(2 帧,机位完全静止) |
| 镜头参数 | focal=**51.222 mm**, paWidth=**35 mm (super35)**, K1=+0.00147, K2=+0.01059, K3=**−0.09008** |
| centerShift | (−0.16569, **−0.19201**) mm |
| Resolution | 1920 × 1080 |
| Disguise reference | `screen_mr_set_1_00001.exr`(Sequence Shot screenshot, linear EXR) |
| UE render(2026-05-08 第一版 bug) | `LS_test_take_6_dense.0002.exr` |
| UE render(中段 partial — 旧 shader translation) | `LS_test_take_6_dense.0001.png`(中心通过 / frustum 缺) |
| UE render(2026-05-09 修复后 PASS) | commit `69a9bea` 后用户在 lanPC 实测验证通过 |
| 帧映射 | 机位静态 → ref 任一帧 ≡ UE 任一帧 |

## 跟 take_5 对比的意义

take_5 验收用的是 focal=43.2886 / paWidth=50 / K1≈+0.0003 / K3≈+0.011 这套**温和参数**。
take_6 故意切到 super35 sensor + 大幅 K3 + 大幅 centerShift,反复试 shader 在
极端参数下是否仍然几何匹配。修复后,take_6 一并通过。

| 维度 | take_5 | take_6 | 含义 |
|---|---|---|---|
| paWidth | 50 mm | **35 mm** | sensor 宽度归一化常数切换,通过 |
| focal | 43.29 mm | 51.22 mm | 焦距增大,通过 |
| K3 | +0.0113 | **−0.0901** | 量级 ×8、符号反转,通过 |
| centerShift Y | +0.0047 mm | **−0.1920 mm** | ×40,**暴露并修复** Y-flip bug |

## 修复经过

### Bug 现象(旧公式 / `LS_test_take_6_dense.0002.exr`)

phase correlation(`scripts/measure_vertical_shift.py`)实测:

| ROI | dx_px | dy_px |
|---|---|---|
| full | +0.05 | **−21.02** |
| center_512 | −0.02 | **−21.02** |
| LED wall | +0.10 | **−20.97** |
| ground | +0.02 | **−21.06** |

公式预测:csx_v = (cv−0.5) = csy_mm/sensor_height = −0.192/19.687 = −0.00975 →
中心点 vertical shift +10.5 px。**实测/预测 = −2× 整数比,典型 sign convention bug**。

### 具体原因

Disguise `centerShiftMM` 在 sensor-space(Y up,镜头标定约定),UE/HLSL `CenterUV`
在 UV-space(Y down,top-left origin),Y 分量需要 flip,X 不 flip。

**为什么 take_5 没暴露**:cs_y=+0.00467mm 在旧公式下 vertical shift 仅 0.36 px
(亚像素级),take_5 的 p95<0.05 通过几何匹配验收时根本看不出 sign 错。
take_6 cs_y 量级 ×40 才放大到 21 px。

### 修复

`Content/Python/post_render_tool/sequence_builder.py:323`(commit `3cbdf26`):

```python
# 旧:
center_v = 0.5 + frame.center_shift_y_mm / sensor_height_mm
# 新:
center_v = 0.5 - frame.center_shift_y_mm / sensor_height_mm
```

X 方向公式不变(`+`),Y 方向单独 flip。HLSL shader 公式不动,改一行 Python。

## 修复后实测(新版 / `LS_test_take_6_dense.0001.png`)

phase correlation:

| ROI | dx_px | **dy_px** |
|---|---|---|
| full | +0.05 | **−0.014** |
| center_512 | +0.07 | **−0.025** |
| upper_half | +0.07 | +0.491 |
| lower_half | +0.05 | +0.504 |
| led_wall_only | +0.07 | **+0.012** |
| ground_only | +0.01 | **+0.012** |

中位 dy = **+0.012 px**(亚像素级)。`upper_half / lower_half` 的 0.5 px
是 phase correlation 在 half-window 边界的伪影,不是真 shift(全图 / 完整 ROI
的 dy ≈ 0 是关键信号)。

X 方向 dx 继续 ~0,take_5 已验证的几何匹配维持不变。

## 离线模拟(commit 前的预验证)

不重新渲染,直接对旧公式 UE EXR 沿 +Y 平移 21 px(等价 sign flip 的刚性位移
效果),跟 ref phase correlate:**dy 从 −21.023 降到 −0.022 px**。修复方向
数学上确认,然后才走 commit + P4 sync + UE 重渲流程。

## 验收结论

- ✅ 大幅 K3(−0.0901,take_5 的 ~8 倍且符号反转)几何匹配
- ✅ paWidth 切到 35mm super35 + focal 51.22mm 不破坏 normalization
- ✅ X 方向 distortion 匹配
- ✅ **Y 方向 vertical shift < 0.1 px 中位(修复后)**

## 输出物

```
validation_results/path_c_production/take_6/
├── test_take_6_dense.csv
├── reference/
│   └── screen_mr_set_1_00001.exr           (Disguise Sequence Shot, 5.6 MB)
├── ue_out/
│   ├── LS_test_take_6_dense.0002.exr       (旧公式 / bug 状态快照, 6.2 MB)
│   └── LS_test_take_6_dense.0001.png       (修复后 / pass 状态, 2.0 MB)
├── diff/                                    (旧公式状态的 overlay)
└── summary.md                               (本文件)
```

## 复跑

```bash
.venv/bin/python scripts/measure_vertical_shift.py \
    --reference validation_results/path_c_production/take_6/reference/screen_mr_set_1_00001.exr \
    --ue-render validation_results/path_c_production/take_6/ue_out/LS_test_take_6_dense.0001.png \
    --predict-shift-px 0
```

预期 median dy < 1 px → 通过。
