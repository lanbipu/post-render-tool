# Lens Distortion Investigation — 接力交班文档

> **状态**：进行中。Disguise CSV K → UE LensFile 的映射做到了 95-98% 视觉匹配，
> 还差最后 ~1-3 像素残差未达到 pixel-perfect。明天接着做。

## 目标

让 UE post_render_tool 渲染输出跟 d3 designer 端 compositor frame **逐像素一致**
（用户明确要求 pixel-perfect，不能接受残差）。

## 已知事实（commit 3468a67 落地）

| 已修 | commit |
|---|---|
| K3↔P2 数组槽位错位 | b6377e1 |
| zoom key 单位（应该 mm 不是归一化） | b6377e1 |
| evaluation_mode 默认 UseLiveLink → UseCameraSettings | b6377e1 |
| LensComponent 不 auto_activate（tick 不跑、MID 不挂） | d09cd84 |
| LensComponent.lens_model 没显式设 → handler 不创建 | d09cd84 |
| LensFile.LensInfo.lens_model 没写 | d09cd84 |
| K 系数方向（CSV K → UE K 要取反号 -K） | 3468a67 |

**这些修复的共同特点**：是 Bug，修了之后整条管线**通**。剩下的不是 Bug，是
**Disguise 跟 UE 的 distortion 数学模型本质不同**。

## K1 单变量扫描结果（今天做的）

Controlled experiment：相机不变，K2=K3=0，CenterShift=0，只调 K1：

| Disguise 端 K1 | UE 端最匹配的 K1 | scale factor |
|---|---|---|
| +0.5 | -0.75 | **1.5x** + 取反 |

差值图（用户在达芬奇做的 abs(A-B) 导出）显示残差**有结构性**：
- 画面中心区域几乎全黑 → K1=-0.75 在小 r 处匹配很好
- 画面边缘有红绿描边 → 大 r 处两边公式不一致
- 残差峰值在四角附近，~1-3 像素

**结论**：单一线性 scale factor (1.5x) 不能达到 pixel-perfect，因为两边
**polynomial 模型的高阶行为不同**。

## 关键资产 / 数据

### lanPC 上现有的

```
E:/temp/k_sweep_all/                          → 6 张 K1 sweep 图（已重命名 K1_neg_XpY.png）
  K1_neg_0p5.png   (UE K1=-0.5)
  K1_neg_0p75.png  (UE K1=-0.75)  ← 视觉最接近 Disguise K1=+0.5
  K1_neg_1p0.png
  K1_neg_1p5.png
  K1_neg_2p0.png
  K1_neg_3p0.png

E:/RenderStream Projects/test_0311/Plugins/post-render-tool/  → 主代码（P4 同步）

C:/temp/ue-remote/                            → Remote Execution bridge
  run_ue.py                                   → 接受文件路径参数，dispatch 到 UE
  diag*.py / sweep_*.py / probe*.py            → 历史诊断脚本（可参考）
```

### Mac 上现有的

```
/tmp/sweep_neg_*.png                         → 6 张 K1 sweep 图（缩略图缓存）
/tmp/ue_*.py                                 → 历史诊断脚本（可参考实现细节）
```

### Disguise 端（用户那边的）

- d3 designer 的 stage 测试场景：LED surface + 16:9 直线网格图 + Disguise camera 对准
- image 44：K1=K2=K3=0 / CenterShift=0 → 完美直线网格 ground truth
- image 45：K1=+0.5 / K2=K3=0 / CenterShift=0 → pincushion 单变量参考
- 差值图：K1=+0.5 (Disguise) - K1=-0.75 (UE) 的 abs diff，达芬奇导出

### UE LensFile 当前状态

```
LensFile 资产路径: /Game/PostRender/shot_1_take_13_dense/LF_shot_1_take_13_dense
当前内容：K1=-3.0, K2=K3=0, principal=(0.5, 0.5)  ← K1 sweep 最后一帧设置
```

**注意**：LensFile 处于"测试 mode"，**不是生产数据**。明天开始前先重跑
`run_import` 让它写回生产 K（CSV 原值 -K）。

## 明天接着做：两条路径

### 路径 A · 黑盒反推 Disguise 真实公式（System Identification）

通过密集采样 + 候选公式拟合，反推 Disguise 内部 distortion 公式。

**实验设计**：
1. 选 5 个 r 位置（0.1、0.2、0.3、0.4、0.45）× 5 个 K 值（0.1、0.2、0.3、0.4、0.5）
2. 每个 (r, K) 组合：在 Disguise 端 controlled 渲染棋盘格 → OpenCV `findChessboardCornersSB`
   亚像素角点检测 → 测量 Δr(r, K)
3. 拟合候选公式：
   - Polynomial: `r·(1 + K·r²)` ← UE 当前用的
   - Division: `r/(1 + K·r²)`
   - Modified polynomial: `r·(1 + α·K·r²)` 含 scale α
   - 高阶 polynomial: `r·(1 + K·r² + β·K²·r⁴)`
   - 不同归一化的 polynomial: `r·(1 + K·(r/α)²)`
4. 拟合误差最小的 = Disguise 真公式
5. 在 UE 用 Newton 迭代精确反算

**优点**：找到真公式后能 closed-form 解决，所有 K 值自动正确。
**缺点**：~1 个工作日实验 + 拟合，依赖 Disguise 用确定性公式（不是查找表）。

### 路径 B · 棋盘格 → STMap（Black-box Direct Solve）

不管 Disguise 内部公式是什么，直接构造每像素位移真值。

**Disguise 没原生 STMap export，但可以这么干**：

1. **生成精密棋盘格 PNG**（Python/PIL 程序生成，比如 19×11 格子，角点位置精确到 0.0 像素）
2. **Disguise 端**：把棋盘格放到 LED surface → 设置 K（CSV 原值或单变量都行）→ 渲染 transmission frame → 导出
3. **OpenCV 角点检测**：`cv::findChessboardCornersSB` + `cornerSubPix` → 得每个角点亚像素位置
4. **配对**：(原棋盘格已知位置) ↔ (Disguise 渲染后位置) → 一组稀疏 displacement
5. **稀疏 → 稠密**：用 RBF / thin-plate spline 插值到全画面每个像素都有 displacement
6. **写入 UE LensFile**：用 `add_stmap_point` API（UE 5.7 LensFile 原生支持 STMap 表）

**关键 UE API**（待验证具体调用形式）：
- `unreal.LensFile.add_stmap_point(focus, zoom, undistortion_stmap, distortion_stmap)`
- 或用 `set_lens_data_table` 等

**优点**：完全绕开数学公式问题，pixel-perfect 直接达成。
**缺点**：每个 K 设置需要单独一张 STMap（不能像公式一样跨 K 通用）。
但因为我们做 post-render，一个 take 一组 STMap 也合理。

### 我推荐的执行顺序

**先做路径 B（STMap）**——不依赖任何假设，直接给出 pixel-perfect 结果。先把
"能做到 pixel-perfect"这件事落地，再考虑后续优化。

如果路径 B 不通（UE LensFile API 不支持 STMap 写入或别的卡点），再做路径 A。

## 路径 B 的明天第一步

明天 session 开始就这么干：

```python
# 1. 生成棋盘格（Mac 上跑）
# /tmp/checkerboard_1920x1080.png — 19×11 格子，黑白棋盘，pixel-precise corners

# 2. 把棋盘格发给用户，让用户：
#    - 在 d3 designer 里把它放到 LED surface（textures 或 video assets）
#    - 用 image 44/45 那个相同相机对准
#    - 用 image 45 那个相同 K（K1=0.5/K2=K3=0/CenterShift=0）渲染 transmission frame
#    - 把渲染结果发回 Mac

# 3. Mac 上跑 OpenCV：
import cv2
import numpy as np

source = cv2.imread('/tmp/checkerboard_1920x1080.png', cv2.IMREAD_GRAYSCALE)
rendered = cv2.imread('/tmp/disguise_K1_0p5_render.png', cv2.IMREAD_GRAYSCALE)

# 已知棋盘格规格
pattern_size = (18, 10)  # 19×11 格 = 18×10 内角点

# 检测两边角点
ret_s, corners_s = cv2.findChessboardCornersSB(source, pattern_size)
ret_r, corners_r = cv2.findChessboardCornersSB(rendered, pattern_size)
# Refine to subpixel
criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
corners_s = cv2.cornerSubPix(source, corners_s, (5,5), (-1,-1), criteria)
corners_r = cv2.cornerSubPix(rendered, corners_r, (5,5), (-1,-1), criteria)

# 现在 corners_s[i] 和 corners_r[i] 是配对的（原始 vs 渲染后位置）
# displacement[i] = corners_r[i] - corners_s[i]

# 4. 插值成 dense STMap（用 scipy thin-plate spline）
from scipy.interpolate import Rbf

# 5. 写 STMap 到 UE LensFile（需要先确认 UE 5.7 Python API 支持哪种 STMap 写入）
```

## 命令快速复用

### Remote Execution（已就绪）

```bash
# 测试连接
echo 'import unreal; print("hello")' | ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py'

# 执行任意脚本
scp /tmp/your_script.py lanpc:C:/temp/ue-remote/your_script.py
ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/your_script.py'
```

### 重置 LensFile 到生产模式（明天先做）

```bash
# 让用户在 UE Editor 里 hot-reload + 重跑 import
# 或者通过 RE 让代码重新执行 run_import
```

## 还要做的（继任清单）

- [ ] 路径 B 第一步：生成棋盘格 PNG，发给用户
- [ ] 路径 B 第二步：用户 d3 端渲染对照
- [ ] 路径 B 第三步：OpenCV 角点检测 + STMap 构造
- [ ] 路径 B 第四步：UE LensFile STMap 写入 API 调研 + 实现
- [ ] 路径 B 第五步：渲染验证 → 跟 Disguise 端做 diff，应该 ≈ 全黑
- [ ] CenterShift 单变量验证（task #7，还没做）
- [ ] 如果路径 B 不通，回退路径 A

## 投入历史回顾（避免重复踩坑）

**注意：跟 Disguise 端 K 系数对照实验时，不要被 d3 designer 里的
calibration overlay 误导**。Calibration overlay 显示的是 inverse / undistortion grid，
方向跟 compositor 实际输出相反。判断真实方向必须用 transmission feed 的
"export compositor frame"——这是 d3 真正应用 K 后送出去的画面。

**不要做的**：
- 不要再做"Taylor 反演近似"了——那个数学上 0 阶近似就是单纯 -K，
  高阶反而把 K2/K3 削得更小，跟 Disguise 强度差更大
- 不要在不知道目标的情况下盲目"调 K scale factor"——已经验证 1.5x 有结构性残差
- 不要再说"够用了"——用户标准是 pixel-perfect

**继任 session 第一句话**：
> 你好，正在交接 distortion 调试。先读 docs/distortion-investigation.md。
> 当前状态：commit 3468a67 完成 -K 取反，UE 端跟 Disguise compositor 视觉
> 95-98% 匹配，还差最后 1-3 像素残差。今天确认了 1.5x 单一 scale factor
> 不能 pixel-perfect，明天走 STMap 路径（路径 B）从棋盘格反推每像素位移。
