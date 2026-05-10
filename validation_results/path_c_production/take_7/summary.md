# take_7 production diff — PASS(distortion 加大 + overscan 完整流程,2026-05-10)

**最后更新**: 2026-05-10
**状态**: **PASS**
- ✅ Distortion 形状 + 量级跟 Disguise reference 视觉对比一致
- ✅ Overscan 边缘内容完整(无黑边 — 修复前 distortion 弯出去的边缘是黑)
- ✅ 中心结构 + frustum 中心(centerShift)继承 take_6 PASS 行为

## 设计意义

take_7 故意把 distortion 量级拉大,目的是:
1. 测试 Disguise overscan 1.3334 流程的 UE 镜像 — distortion 弯曲量大时边缘 sourceUV 弯到原 frustum 外 = 必须 overscan 多渲一圈才有数据采样
2. 暴露之前所有"边缘问题假修"的盲点 — phase correlation 看不出来 frustum 截断,小 distortion 也不会出现明显黑边,只有大 distortion 才能可视化看到

## 测试条件

| 项 | 值 |
|---|---|
| CSV | `test_take_7_dense.csv`(lanPC: `E:\d3 Projects\0408\output\shots\test\take_7\`) |
| Disguise reference | `screen_mr set 1_00002.exr`(lanPC: `E:\d3 Projects\0408\screenshots\`) |
| UE render(commit `c3ccabb` 之后 PASS) | `LS_test_take_7_dense.<frame>.png`(lanPC: `E:\RenderStream Projects\test_0311\Saved\MovieRenders\`) |
| CSV.overscan | 1.3334(等比)→ UE.Overscan = 0.3334 |
| Distortion | 加大(具体 K 值见 CSV;比 take_6 量级显著大) |

## 修复链(三 commit 协同生效)

1. **commit `69a9bea`**: centerShift 走 `Filmback.SensorHorizontalOffset/Vertical`(`OffCenterProjectionOffset`)— frustum 中心对到 principal point
2. **commit `43173c4`**: 接入 UE 5.7 引擎原生 `UCameraComponent.Overscan` + `bScaleResolutionWithOverscan` + `bCropOverscan` — 扩大 frustum + 渲染分辨率,distortion shader 在 overscanned SceneTexture 上跑,末端 crop
3. **commit `c3ccabb`**: shader 加 frustum 归一化包装(`normUV = (UV-0.5)*(1+Overscan)+0.5`)— SceneTexture 是 2560×1440 时把 UV 转回原 1920×1080 frustum space 套 K1/K2/K3,核心 distortion 算法 1:1 不变

## 历史 / 失败回溯

- **commit 43173c4 之后第一次实测**: distortion 形状完全错 — shader 把 K1/K2/K3 公式直接套在扩大 viewport UV [0,1] 上,r²/d 偏离原 frustum 标定 → 形状跟量级都不对
- **诊断**: shader 不知道 viewport 已扩大,K 是按原 1920×1080 标定的
- **修法选项**: A) shader 加 frustum 归一化(包装核心算法,不改公式)/ B) 缩放 K 系数让 viewport 等效(改 input 含义)
- **决定**: A(物理意义清晰,Sequencer K 仍 = CSV 原值,Overscan=0 时严格退化等价于旧 SHADER_VERSION)
- **commit c3ccabb 实施 + 用户实测验证通过**

## 修复方案 + 推理

- 见 commit `69a9bea` + `43173c4` + `c3ccabb` message
- `CLAUDE.md` 顶部 2026-05-10 update #3 段(shader 归一化 + 部署步骤)
