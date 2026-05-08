# take_6 production diff — 几何主体对齐,Y 方向有几像素小残差

**日期**: 2026-05-09
**判定**: 通过(几何对齐),保留 Y 方向小残差待查

## 测试条件

| 项 | 值 |
|---|---|
| CSV | `test_take_6_dense.csv`(2 帧,机位完全静止) |
| 镜头参数 | focal=**51.222 mm**, paWidth=**35 mm (super35)**, K1=+0.00147, K2=+0.01059, K3=**−0.09008** |
| centerShift | (−0.16569, **−0.19201**) mm |
| Resolution | 1920 × 1080 |
| Disguise reference | `screen_mr_set_1_00001.exr`(Sequence Shot screenshot, linear EXR) |
| UE render | `LS_test_take_6_dense.0002.exr`(MRQ Path C, linear EXR) |
| 帧映射 | 机位静态 → ref 任一帧 ≡ UE 任一帧 |

## 跟 take_5 对比的意义

take_5 验收用的是 focal=43.2886 / paWidth=50 / K1≈+0.0003 / K3≈+0.011 这套**温和参数**。
take_6 故意切到 super35 sensor + 大幅 K3 + 大幅 centerShift,用来反复试 shader 在
极端参数下是否仍然几何对齐。

| 维度 | take_5 | take_6 | 含义 |
|---|---|---|---|
| paWidth | 50 mm | **35 mm** | sensor 宽度归一化常数切换 |
| focal | 43.29 mm | 51.22 mm | 焦距增大 |
| K3 | +0.0113 | **−0.0901** | 量级 ×8、符号反转,大幅 distortion |
| centerShift Y | +0.0047 mm | **−0.1920 mm** | ×40,大幅 Y 偏移 |

## 像素 metrics(linear EXR 直 diff)

| 指标 | 值 |
|---|---|
| RMS | 0.2218 |
| Median | 0.1328 |
| P95 | 0.4873 |
| Max | 0.9487 |
| Mean | 0.1474 |
| ref_mean | 0.4143 |
| ue_mean | 0.3126 |

**注**: 绝对像素差异这次比 take_5 大,主要是色彩管线 / 曝光归一化 / Disguise vs UE
端 ground/wall 材质亮度不一致引起的,**不计入几何对齐验收**(沿用 take_5 口径)。

## 几何判定(肉眼 overlay 验证)

### ✅ 通过项

1. **四角 K3 弧线弯曲**: 50/50 overlay 显示左下、右下角的弧线两边完全重合,
   没有双重影像。K3=−0.0901 的大幅弯曲(画面边缘"羽毛"形状)在两端一一对应。
2. **LED wall 垂直线**: cyan/magenta overlay 里垂直线几乎完全重合,
   X 方向 distortion 没问题。
3. **网格密度**: LED wall 水平/垂直线条数 ref vs UE 一致 → 整体 distortion shape 对。
4. **paWidth 切到 35mm super35 + focal 51.22mm 没破坏 shader normalization 常数。**

### ⚠️ 待查项: Y 方向几像素级 shift

**现象**: cyan/magenta overlay 里 LED wall 上半部 / 地板 grid 的水平线
出现 cyan(ref-only) + magenta(UE-only)交错,垂直方向错开几像素。

**怀疑方向(优先级排序)**:

1. **centerShift Y 公式 sign 或 sensor height normalization** ——
   take_6 的 centerShift Y = −0.192 mm 是 take_5 的 ~40 倍,如果 shader 里 Y 方向
   normalization 用的不是 `cs_y × image_h / sensor_h_mm`(参考 MEMORY 里 K=0
   centerShift 公式定型条目),小值下看不出来,大值下就会暴露。
2. **Disguise 端 LED wall 几何位置跟 UE `/Game/Main` 不严格 1:1** ——
   场景物理坐标差几 cm 在 51mm 焦距下就是几像素错位,不是 shader bug。
3. **paWidth=35mm 下 aspect ratio 处理** —— super35 sensor 物理高度跟 16:9 image
   aspect 之间的转换是否正确进入 shader Y 方向。

**下一步建议**: 不立刻定位。先把 take_6 作为"通过几何对齐 / Y 残差待查"
归档,看后续是否还有更多 take 暴露同类残差。如果只在 take_6 出现 → 优先怀疑 #2;
如果其他 take 也复现 Y shift → 必查 #1。

## 输出物

```
validation_results/path_c_production/take_6/
├── test_take_6_dense.csv
├── reference/screen_mr_set_1_00001.exr     (Disguise Sequence Shot, 5.6 MB)
├── ue_out/LS_test_take_6_dense.0002.exr    (UE MRQ Path C, 6.2 MB)
└── diff/
    ├── diff_overlay_50_50.png
    ├── diff_overlay_cyan_magenta.png
    ├── diff_heatmap.png
    ├── ref_srgb.png
    ├── ue_srgb.png
    ├── metrics.txt
    └── summary.md(本文件)
```

## 复跑

```bash
.venv/bin/python scripts/diff_production_frame.py \
    --reference validation_results/path_c_production/take_6/reference/screen_mr_set_1_00001.exr \
    --ue-render validation_results/path_c_production/take_6/ue_out/LS_test_take_6_dense.0002.exr \
    --output-dir validation_results/path_c_production/take_6/diff \
    --label take_6
```
