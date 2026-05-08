# take_5 静态帧 diff — 验证通过

**日期**: 2026-05-08
**结论**: Path C distortion shader 在 take_5 参数下几何完全对齐,通过验收。

## 测试条件

| 项 | 值 |
|---|---|
| CSV | `test_take_5_dense.csv`(2 帧,机位完全静止) |
| 镜头参数 | focal=43.2886mm, paWidth=50mm, K1=+0.000286, K2=−0.003953, K3=+0.011302 |
| centerShift | (+0.004900, +0.004673) mm |
| Resolution | 1920 × 1080 |
| 参考管道 | Disguise Sequence Shot screenshot (= Transmission Frame 同管道) |
| UE 管道 | Path C `M_PRT_OfficialSensorInverse` material + LevelSequence MRQ |

## 结果

- **几何对齐**: 完全通过(地面网格、sphere mesh、LED wall 标签、PaperPlay logo 位置全部对齐)
- **像素 diff 残差(忽略天空云区域)**: 仅来自 sRGB tone mapping 差异和动态云,无几何偏差
- 50/50 alpha blend 中两组网格完全重合,无双重影像

## 重要陷阱(避免下次误诊)

1. **场景里的粉色 sphere mesh 不是 distortion 校正网格**——它是 UE 场景里固有的可视化 helper(球面曲线 mesh),REF 和 UE 都会画。看起来"凸出"是球本身的几何,不是 distortion artifact。
2. **天空云是动态噪声**——Sequencer 里的 sky material 用 time-based procedural noise,每次渲染云形状都不一样。diff heatmap 里天空区域出现的强残差不计入验收。
3. **整体 sRGB tone mapping 偏差 ≠ shader bug**——UE PNG 输出经过完整渲染管线 tone mapping,REF EXR 是 linear,简单 sRGB 转换后仍有亮度差,这是色彩管线不同,不是 distortion 公式问题。

## 后续

- **take_4 production diff 残差疑点收尾**: take_5 用同套镜头参数 + 干净 Sequence Shot 基准通过 → take_4 残差只能来自 motion 数据或 .seq feed 信号链,与 shader 无关。
- **悬而未决的 normalization 二义性仍在**: 见 `docs/d3-distortion-render-request.md`,take_5 的镜头规格让 fx ≈ W,无法分辨 sensor 全宽归一化 vs 焦距归一化等候选。下次需要变焦或不同 sensor 的 take 才能压力测试。

## 输出物

```
validation_results/take_5_diff/
├── test_take_5.csv
├── test_take_5_dense.csv
├── reference/screen_mr_set_1_00000.exr
├── ue_out/LS_test_take_5_dense.0000.png
├── diff_overlay_50_50.png
├── diff_overlay_cyan_magenta.png
├── diff_heatmap.png
└── summary.md (本文件)
```
