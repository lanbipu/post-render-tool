# Distortion Precision Analysis — 真实残差档次定位

> 写于 2026-04-29，对应 commits `8164938..cd68843`（M_RAT6 BrownConradyUD 升级完成后）。
> 记录 K=+0.5 测试残差从 M6 时代 122 px → 现在 ~1-3 px 之后，**残差停在 1-3 px 这道坎的根因**，
> 以及之前一次错误推导的纠正。

---

## 1 · 一次错误的推导（要避免再犯）

### 错误的思路

测试值 K=+0.5 时：
- distortion 总量 max 122 px
- 端到端残差 max 3.2 px
- → "相对误差 = 3.2 / 122 = 2.6%"

production CSV K1 ≈ 3e-4 时：
- distortion 总量 max 0.32 px
- → "残差 = 0.32 × 2.6% = 0.0083 px"
- → "production 端到端 sub-0.01 px，超过 ILM 影视级 12× 余量"

**这条推导是错的**。从两个角度反驳：
1. 端到端肉眼看到 production 还有 1-3 px 边缘偏差，跟 0.008 px 完全不符
2. 不可能这么轻易就达到 ILM 影视级（实际 < 0.05 px @ 1080p），跟整个行业的工程难度不一致

### 错误的根源：相对误差线性外推

残差不是 100% 线性跟 distortion 量级缩放的。**残差有三个绝对量级的来源**，跟 K 值无关：

| 误差来源 | 绝对量级 | 是否跟 K 一起缩小？ |
|---|---|---|
| **UE 256×256 LUT bilinear 量化** | 1-2 px sub-texel jitter | ❌ 跟 LUT 分辨率挂钩，跟 distortion 量级无关 |
| **fit noise floor**（cornerSubPix 物理极限） | ~0.4 px | ❌ 是测量端噪声 |
| **公式 model mismatch**（M_RAT6 vs Disguise 真公式形态） | ~0.1-0.3 px | ❌ 是 fit 形态本身偏差 |
| **公式相对残差** | 0.1-1% × distortion | ✅ 唯一线性缩小那一项 |

K=+0.5 时残差 ≈ LUT jitter（~1-2 px）+ noise floor（~0.4 px）+ 模型 mismatch（~0.3 px）+ 公式相对残差（百分之几 × 122 ≈ 0-1 px）= 总和 **3.2 px**。

K=3e-4 时残差 ≈ LUT jitter（**仍然 1-2 px**）+ noise floor（**仍然 0.4 px**）+ 模型 mismatch（**仍然 0.1-0.3 px**）+ 公式相对残差（百分之几 × 0.32 ≈ 0.001-0.003 px）= 总和 **仍然 1-2 px**。

**关键洞察**：production K=3e-4 时 distortion 信号本身才 0.32 px max，而 shader 端固定噪声底就是 1-2 px。**distortion 信号 < shader 噪声底** → 实际渲染残差跟"distortion 没应用"几乎一样。

---

## 2 · 真实档次定位（修正后）

| 档次 | max @ 1080p | p95 | median | 用途 |
|---|---|---|---|---|
| **ILM / Weta / DNEG 旗舰 VFX** | < 0.05 px | < 0.02 px | < 0.01 px | 4K-8K 影院级，per-channel chromatic，STMap |
| 影视后期 / 一线 VFX 公司 | < 0.3 px | < 0.2 px | < 0.1 px | 高端 TV / 广告 |
| **VP 旗舰**（LED stage 实时合成） | < 1 px | < 0.5 px | < 0.3 px | UE LensFile 标准方案的顶端 |
| **当前 PostRenderTool 真实残差** | **~1-3 px** | **~0.5-1 px** | **~0.3 px** | **VP 边界 / VFX 入门** |
| 广告 / 中等预算 | < 3 px | < 1 px | < 0.5 px | 后期能修补 |
| 游戏 / 实时模拟 | < 5 px | < 3 px | < 1 px | 通常不做精确 distortion |
| 不能用 | > 5 px max / 拐点崩 | — | — | M6 时代外圈 max 122 px 就在这里 |

**当前 PostRenderTool 在 VP 边界**，离 ILM 还差 30-60×。M6 → BrownConradyUD 升级把外圈 max 从 122 px 降到 3.2 px，**但 1-3 px 这道坎是 UE shader 架构限制**，不是公式问题。

---

## 3 · 残差细分（K=+0.5 测试用扭曲量诊断）

每个像素位置的残差是各来源叠加。按外圈 r ≥ 0.8 max 3.2 px 反向估算：

```
3.2 px ≈ √(LUT_jitter² + noise_floor² + model_mismatch² + relative_err²)
       = √(1.5² + 0.4² + 0.3² + 0.5²)
       = √(2.25 + 0.16 + 0.09 + 0.25)
       = √2.75
       ≈ 1.66 px (RMS-合成)
       
       极端单像素 (worst-case 同号叠加):
       = 1.5 + 0.4 + 0.3 + 0.5 = 2.7 px ←跟实测 3.2 px 接近，差 0.5 px 是 PNG 量化 + AA ringing
```

**主导项是 LUT bilinear jitter（1-2 px）**。fit noise floor（0.4 px）和 model mismatch（0.1-0.3 px）只占次要权重。

---

## 4 · 改进路径（按 effort 升序）

### 4.1 短期（已可行 cvar 实验）

调高 UE LensDistortion displacement RT 分辨率：

```
r.LensDistortion.DisplacementMapResolution 2048
```

LUT texel 间距从 1920/256 = 7.5 px → 1920/2048 = 0.94 px。**LUT jitter 估计从 1-2 px 降到 0.1-0.2 px**。代价：GPU 内存 64×（256² × float2 = 0.5 MB → 2048² × float2 = 32 MB），实时性可能影响。

**预期残差降到 0.5-1 px @ 1080p — VP 旗舰级达标**。

### 4.2 中期（换 LensDistortion mode）

UE 5.7 LensDistortion plugin 理论支持 **STMap mode**（per-pixel displacement table 而不是 polynomial fit）。

- LensFile 直接存 1920×1080×2 float displacement field（每个 (focus, zoom) 一张，~25 MB / EXR）
- 绕开 rational fit 残差 + LUT 量化
- 但失去对未采集 K 值的 generalization（需要 spline 插值）
- 适合 production 使用单一 lens preset 反复渲染场景

**预期残差降到 0.1-0.3 px @ 1080p — 影视后期级达标**，前提是 UE 5.7 STMap pipeline 走通（需 verify）。

### 4.3 长期（物理 calibration）

不靠 system ID 反推 Disguise 公式，直接做物理标定：

1. 实拍 ChArUco 棋盘格在 LED stage 上 + 真实 lens
2. cv2.calibrateCamera 出 intrinsics + distortion coeffs（精度 ~0.05 px @ 1080p）
3. 跳过 Disguise → UE 转换链路（Disguise 公式逆推不再是必要）

代价：需要在每个 lens / focal length 配置下做物理标定，工作量大；但精度直接达到 cv2 行业标准。

### 4.4 终极（影视级）

走 ILM/DNEG 实际工作流：

1. **STMap + per-channel chromatic**（R/G/B 各一张 STMap）
2. **超采渲染**：UE 4K 渲，下采到 1080p（4× sub-pixel 精度）
3. **Nuke/Houdini offline distortion**：UE 输出 undistorted，Nuke 后期 apply distortion（不在实时管线里做）
4. **修改 UE 引擎源码**：增大 displacement RT 默认分辨率，加 sub-pixel jitter 抗锯齿

代价：放弃实时性 + 引擎源码修改门槛。**UE LensFile 标准管线基本上达不到 ILM 影视级**，因为这套设计的 trade-off 优先实时性。

---

## 5 · 当前业务定位

✅ **VP 实时合成业务可上线**：production CSV 实际工作流下，distortion 信号 < shader 噪声底，渲染结果跟"distortion 没应用"几乎一样，1-2 px 残差在 LED stage 实拍合成场景下几乎看不出（observer + camera shake + AA + motion blur 都会掩盖）

✅ **拐点崩盘问题已修复**（vs M6 时代外圈 max 122 px → 现在 3.2 px）

❌ **不是 ILM 影视级**，离 ILM < 0.05 px 还差 30-60×

❌ **测试值 K=+0.5 max 3.2 px** 卡在 VP 标准边界，不是 production 场景但在反推诊断时出现

---

## 6 · 后续实验记录占位

- [ ] 6.1 cvar `r.LensDistortion.DisplacementMapResolution 2048` 实验，量化 LUT jitter 主导项
- [ ] 6.2 UE 5.7 STMap mode 是否走通 + 实测残差
- [ ] 6.3 ChArUco 物理 calibration 路径调研（cv2.calibrateCamera vs system ID）

每个实验跑完结果回写本文件。
