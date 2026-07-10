# CLAUDE.md

> **史料归档说明(2026-07-10)**:开发史料(`validation_results/`、
> `scripts/distortion_calibration/`、`archive/`、`Assets/`、`reference/`、
> `docs/archive/`、`docs/superpowers/` 及各类 spike/probe 脚本)已从工作区
> 移除,repo 清理为标准源码插件形式。**全部内容在 git 历史中完整保留**——
> 要复盘验证证据、Path A 代码快照或校准 dataset,checkout 清理 commit 的
> 父提交即可(`git log --diff-filter=D` 可定位)。

> **Distortion 路线状态(2026-05-08)**:Path C(Custom Post-Process Material)
> 已落地,take_4 production diff 通过(commit `5f2fa2b`),take_5 静态帧 diff
> 几何完全对齐。Path A(LensFile + M_RAT6/M_RAT8 公式拟合)已**完整下架**
> (2026-05-08),plugin 不再生成 `LF_*` 资产、不再挂 LensComponent 到 camera。
> Path A 代码快照与验证史料均在 git 历史(见上方归档说明)。
>
> **看 diff 时的坑**:场景里的粉色 sphere mesh 是 helper 几何,不是 distortion
> 校正网格;天空云是 time-based procedural noise,每次渲染都不一样,diff
> heatmap 上的天空残差不计入验收。详见 take_5 summary。
>
> **2026-05-09 update**: take_6 完整 production diff 暴露非对称 frustum 截断
> (上 + 右少 ~10 px),原因是 `centerShift` 当成 post-process UV 平移只能搬
> 已渲像素,补不回 frustum 外内容(phase correlation 看不出来,它测中心结构,
> 不测 frustum 范围)。修复:`centerShift` 改走
> `CineCameraComponent.Filmback.SensorHorizontalOffset/Vertical`(UE 原生
> `OffCenterProjectionOffset`),shader 只剩 radial term,radial 中心 = 图心
> (0.5, 0.5)。SHADER_VERSION → `2026-05-09-centershift-via-projection-offset`,
> 部署后必须重跑 `build_distortion_material.run_build()` 才能通过 metadata-tag
> 校验。详见 commit `69a9bea`。
>
> **2026-05-09 update #2 (overscan)**: take_7 加大 distortion 暴露
> 边缘黑边 — 因为 UE 之前一直没用 CSV 自带的 overscan 字段(1.3334),
> radial 弯曲把边缘 sourceUV 弯到 frustum 外 = 黑;Disguise 多渲一圈
> 后边缘有内容。修复:接上 UE 5.7 引擎原生 `UCameraComponent.Overscan`
> + `bScaleResolutionWithOverscan` + `bCropOverscan`,Sequencer 关键帧
> 写 `Overscan = (CSV.overscan_x + overscan_y) / 2 - 1.0`(等比检查
> fail-fast,>2.0 fail-fast)。**这一修复跟 commit 69a9bea(centerShift
> via SensorOffset)并存,不冲突** — uniform overscan 不动
> `OffCenterProjectionOffset`(`CameraStackTypes.cpp:528`),引擎自己
> 处理两个修复的交互。Custom PP material 在 crop 之前
> (`PostProcessing.cpp:3270` BL pass 在 `:3340` SecondaryUpscale 之前),
> blendable location 不需要改。详见 commit `43173c4` + `c3ccabb`。
>
> **2026-05-10 update #3 (overscan shader frustum 归一化)**: commit
> 43173c4 (overscan support)实测 take_7 渲染 distortion 形状完全错 —
> 因为 SceneTexture 现在是扩大 viewport (2560×1440),shader UV [0,1]
> 跨整个扩大区,但 K1/K2/K3 是按原 1920×1080 frustum 标定的,直接套
> 得到的 r²/d 偏离原标定。修复:shader **不动核心算法**,在外面包一层
> 坐标变换 — `normUV = (UV - 0.5) * (1+Overscan) + 0.5` 把 viewport UV
> 转回原 frustum UV space → 原 distortion 公式照常作用 → 反映射回
> viewport sample 位置。Overscan=0 时 OS=1.0 → 两层换算恒等 → 跟旧
> SHADER_VERSION 1:1 一致(take_5/6 重 import 不会回退)。
> SHADER_VERSION → `2026-05-10-overscan-frustum-normalized`,
> controller `PostRenderDistortionControllerComponent` 加 `Overscan`
> UPROPERTY(Interp)+ MID set,sequence_builder 在 controller_binding
> 也加一条 Overscan track(跟 camera 上的 Overscan 同源)。**改了 C++
> UPROPERTY → 必须 UBT 重编 plugin + 重启 UE Editor + run_build()
> 重生 material**。
>
> **2026-05-13 update #4 (Custom MovieScene Track)**: Path C 实施层从
> "19 条 Sequencer Float Track + 1 条 Transform Track + per-frame add_key"
> 切换到 "1 条 UPostRenderCameraTrack + UPostRenderCameraSamples DataAsset".
> 解决 68k 帧大 CSV import 卡死 (130 万次 add_key × Section->Modify O(N²))
> 和 Sequencer scrub 卡顿 (Curve Editor 渲染 ~130 万个 keyframe 点).
> Evaluator 走 Sequencer 标准三段式: Evaluate (worker-thread 安全, 通过
> SampleAsset->FindBoundingIndices 算 lerp 包围帧) → push ExecutionToken
> → Execute (game-thread 写 actor / camera / controller + 显式调
> RefreshMaterialParameters, 不依赖 TickComponent ordering).
> 新加 C++ 类: FPostRenderCameraSample USTRUCT / UPostRenderCameraSamples
> DataAsset / UPostRenderCameraSection / UPostRenderCameraTrack /
> FPostRenderCameraSectionTemplate. Editor 侧 FPostRenderCameraTrackEditor
> + FPostRenderCameraSection (FSequencerSection) 注册 Sequencer UI (缺
> 这一步 Sequencer 打开 LevelSequence 会崩). Build.cs 加 MovieScene /
> MovieSceneTracks / LevelSequence (Public), Sequencer / MovieSceneTools
> (Private) 依赖. 每个 LevelSequence 现在配一份
> /Game/PostRender/<csv_stem>/LS_<csv_stem>_Samples DataAsset 持 dense
> 样本 (跟 LevelSequence 同目录). plan + 全部回归 evidence 在 git 历史
> (原 docs/superpowers/plans/2026-05-13-custom-moviescene-track.md).
> take_4 完整 import + Sequencer scrub + MRQ 渲染验证全部通过.
> **改了 C++ + 加了私有模块依赖 → 必须 UBT 重编 plugin + 重启 UE Editor**.

## Project Overview

VP Post-Render Tool: Disguise Designer CSV Dense → UE 5.7 CineCameraActor +
Custom Post-Process Distortion(Path C)+ LevelSequence。Distortion 完全由
Path C 接管,LensFile 资产不再生成。

Packaged as a **self-contained UE 5.7 plugin** (`PostRenderTool.uplugin` at repo root). Drops into any `<UEProject>/Plugins/` directory. C++ module provides a `UEditorUtilityWidget` subclass with a `meta=(BindWidget)` UPROPERTY contract; child Blueprint authored in the UMG Designer satisfies the contract; Python binds callbacks and drives the CSV → UE import pipeline.

## Commands

```bash
# Unit tests (pure Python, no UE needed)
cd Content/Python && python -m unittest discover -s post_render_tool/tests -p "test_c*.py" -p "test_v*.py" -v

# Syntax check for UE-dependent modules
for f in post_render_tool/{camera_builder,sequence_builder,pipeline,ui_interface,widget,widget_builder,build_distortion_material}.py; do
  python3 -c "import ast; ast.parse(open('$f').read()); print('OK: $f')"
done

# UE Python console — launch tool
import init_post_render_tool

# UE Python console — full pipeline (bypass UI)
from post_render_tool.pipeline import run_import
result = run_import(r"path/to/csv", fps=24.0)

# UE Python console — widget management
from post_render_tool.widget_builder import open_widget, rebuild_widget, delete_widget, rebuild_from_spec
open_widget()        # load BP_PostRenderToolWidget + spawn tab + bind callbacks
rebuild_widget()     # reopen (drops cached UI, does NOT delete the Blueprint asset)
rebuild_from_spec()  # regenerate BP from docs/widget-tree-spec.json (idempotent — preserves user tweaks on existing widgets) + reopen tab
delete_widget()      # destructive: delete the deployment-authored asset (not shipped; must be re-authored per deployment-guide.md §1.3 or re-synced from version control)

# UE Python console — build BP from JSON spec (standalone, without reopen)
from post_render_tool import build_widget_blueprint
build_widget_blueprint.run_build()

# UE Python console — hot reload after editing .py files (no UE restart)
import importlib
import post_render_tool.widget_builder as wb
import post_render_tool.widget as w
importlib.reload(wb); importlib.reload(w)
wb.rebuild_widget()

# Cross-check widget names across C++ / widget.py / JSON spec (drift detector)
cd Content/Python && python -m unittest post_render_tool.tests.test_spec_drift -v
```

## Git / P4 Workflow

- **Post-commit hook pushes the CURRENT branch to the Helix4Git depot** on every commit (`scripts/git-hooks/post-commit`, `core.hooksPath = scripts/git-hooks`, installed via commits `0581b3c` → `a46045f`). `main` and feature branches both push; hook exits 0 on failure so it never blocks commits. Output: `[p4-sync] ✓ <branch> pushed to p4` on stderr; rolling log at `.git/p4-push.log`.
- **P4 workspace mirror**: `/Users/bip.lan/AIWorkspace/vp/p4-workspace/ue/post-render-tool/` is a parallel clone of the same depot, pinned to `main` for UE Editor consumption. Feature-branch commits land in the depot but don't advance this mirror. `P4CLIENT = claude-workspace` (set via `P4CLIENT=claude-workspace p4 ...` or `~/.p4config`).
- **Worktree convention**: For multi-commit refactors, create a worktree outside the repo: `git worktree add ~/.config/superpowers/worktrees/post_render_tool/<branch> -b feature/<name>`. Keeps the main working tree and the p4 workspace mirror clean. Each commit still pushes the feature branch to the depot (safe — `main` doesn't move until merge).
- **Main repo vs worktree**: Edits in a worktree on a non-main branch are invisible to the main repo's working tree until you `git checkout <branch>` in main or merge. If someone says "I don't see the new files", that's usually why.
- **Known hook quirk — `--no-ff` merges don't trigger the hook.** `git merge --no-ff` creates a merge commit, but the `post-commit` hook does NOT fire on it in this setup (observed at `2db9686`, session 2026-04-12). After any `--no-ff` merge into `main`, manually run `git push p4 main` to advance the p4 depot. Fast-forward merges (no new commit) don't need a push at all.
- **lanPC P4 workspace overlap — plugin `.uasset` risks mis-add to traditional depot.** `graph-sync-lanPC` (`//ue/post-render-tool/`) and `super_lanPC_rs_projects` (`//rs_projects/test_0311/...`) both map the same physical path. Plugin assets (BP / Material / textures) belong in graph depot only — commit to plugin git, hook pushes to `//ue/post-render-tool/`. Fix mis-add: `p4 revert` (pending) or `p4 delete -k + submit` (already submitted). Ref `3b28d1c`.

## First-time setup

See `docs/plugin-setup.md` for first-time plugin installation, UBT build, and Blueprint authoring instructions.

## Architecture

VP Post-Render Tool is a self-contained UE 5.7 plugin. The repo root IS the plugin root:

```
post_render_tool/                                       ← plugin root
├── PostRenderTool.uplugin                              ← plugin manifest
├── Source/
│   └── PostRenderTool/
│       ├── PostRenderTool.Build.cs                     ← module descriptor (UMG, Blutility, UnrealEd, MovieScene/MovieSceneTracks/LevelSequence Public, Sequencer/MovieSceneTools Private, …)
│       ├── Public/
│       │   ├── PostRenderToolModule.h                  ← empty module entry point
│       │   ├── PostRenderToolWidget.h                  ← C++ BindWidget contract (33 UPROPERTYs)
│       │   ├── PostRenderToolBuildHelper.h             ← C++ bridge for WidgetTree mutation + DataAsset write (6 UFUNCTIONs)
│       │   ├── PostRenderToolCommands.h                ← FUICommandInfo for VPTool toolbar button
│       │   ├── PostRenderDistortionControllerComponent.h ← Path C: 7 Sequencer-facing UPROPERTYs (K1/K2/K3/CenterU/CenterV/Aspect/DistortionWeight) + MID 管理
│       │   ├── PostRenderCameraSample.h                ← FPostRenderCameraSample USTRUCT(16 float per-frame 测量值 + 静态 Lerp)
│       │   ├── PostRenderCameraSamples.h               ← UPostRenderCameraSamples DataAsset(dense 样本 + metadata + FindBoundingIndices)
│       │   └── PostRenderCameraTrack.h                 ← UPostRenderCameraTrack Sequencer 自定义 track(替换旧 19 条 Float Track)
│       └── Private/
│           ├── PostRenderToolModule.cpp                ← toolbar + command 注册
│           ├── PostRenderToolWidget.cpp                ← empty NativeConstruct stub
│           ├── PostRenderToolBuildHelper.cpp
│           ├── PostRenderToolCommands.cpp
│           ├── PostRenderDistortionControllerComponent.cpp
│           ├── PostRenderCameraSamples.cpp
│           ├── PostRenderCameraSection.h               ← UPostRenderCameraSection (持 SampleAsset 引用)
│           ├── PostRenderCameraSection.cpp
│           ├── PostRenderCameraTrack.cpp
│           ├── PostRenderCameraSectionTemplate.h       ← FPostRenderCameraSectionTemplate eval template + FPostRenderCameraExecutionToken (worker→game thread 三段式)
│           ├── PostRenderCameraSectionTemplate.cpp
│           ├── PostRenderCameraTrackEditor.h           ← FPostRenderCameraTrackEditor + FPostRenderCameraSection(FSequencerSection)(Editor 侧, 注册 Sequencer UI)
│           └── PostRenderCameraTrackEditor.cpp
├── Content/
│   ├── Blueprints/
│   │   └── BP_PostRenderToolWidget.uasset              ← not in upstream plugin source; first bootstrap authors once via deployment-guide.md §1.3 and commits to the project repo, later clones/deployments just sync
│   ├── Materials/
│   │   └── M_PRT_OfficialSensorInverse.uasset          ← Path C Post-Process Material(K1/K2/K3/CenterUV/Aspect/Weight 参数 + HLSL 公式)
│   └── Python/
│       ├── init_post_render_tool.py                    ← entry point, calls widget_builder.open_widget()
│       └── post_render_tool/
│           ├── config.py                               # Configurable constants (axis mapping, thresholds)
│           ├── csv_parser.py                           # CSV Dense parser (pure Python; 支持 legacy + spatialmap schema)
│           ├── coordinate_transform.py                 # Coord transform (pure Python, configurable)
│           ├── validator.py                            # FOV check + anomaly detection (pure Python)
│           ├── distortion_math.py                      # Path C `official_sensor_inverse_uv` (HLSL 镜像, pure Python)
│           ├── build_distortion_material.py            # Path C: 程序化生成 M_PRT_OfficialSensorInverse material asset (requires unreal)
│           ├── camera_builder.py                       # CineCameraActor + Path C controller component (requires unreal)
│           ├── sequence_builder.py                     # LevelSequence + UPostRenderCameraTrack + _Samples DataAsset 一次性写入 (requires unreal)
│           ├── sample_packer.py                        # Pure Python: CSV rows → FPostRenderCameraSample 列表 + DataAsset payload 序列化
│           ├── pipeline.py                             # Orchestrator (requires unreal)
│           ├── ui_interface.py                         # File dialog, sequencer, MRQ (requires unreal)
│           ├── widget.py                               # BindWidget binder + callbacks
│           ├── widget_builder.py                       # Asset loader + tab spawner
│           ├── spec_loader.py                          # Pure Python: 解析 widget-tree-spec.json
│           ├── widget_properties.py                    # Pure Python: per-widget + slot-layout 反射写入器
│           ├── widget_variants.py                      # Widget tree variant 处理(deprecated 入口的 stub)
│           └── widget_programmatic.py.bak              # archival (pre-plugin builder, unused)
├── scripts/
│   ├── git-hooks/                                      ← post-commit p4 推送 hook
│   ├── build_all_versions.ps1                          ← lanPC 批量打包(UE 5.1–5.8)
│   └── package_releases.sh                             ← Mac 侧 driver(rsync + ssh 触发 + 拉回产物)
└── docs/
    ├── plugin-setup.md                                 ← first-time install guide
    ├── bindwidget-contract.md                          ← 33 widget name/type reference
    ├── deployment-guide.md
    └── widget-tree-spec.json / .schema.md              ← WidgetTree 单一真源(build_widget_blueprint 读取)
```

UE loads the plugin from `<UEProject>/Plugins/PostRenderTool/`, mounts `Content/` at the virtual path `/PostRenderTool/`, and adds `Content/Python/` to `sys.path`.

**BindWidget contract:** `UPostRenderToolWidget` (C++) declares 26 required + 7 optional widget pointers via `UPROPERTY(BlueprintReadOnly, meta=(BindWidget))` / `meta=(BindWidgetOptional)`. The child Blueprint `BP_PostRenderToolWidget` must contain widgets with matching names and types, or the UMG compiler fails the Blueprint build with `A required widget binding "X" of type Y was not found.`

**Runtime flow:**
1. User runs `import init_post_render_tool` in the UE Python console
2. `widget_builder.open_widget()` loads `/PostRenderTool/Blueprints/BP_PostRenderToolWidget`
3. `EditorUtilitySubsystem.spawn_and_register_tab()` spawns the widget instance
4. `PostRenderToolUI(widget)` acquires every bound widget via `host.get_editor_property("btn_browse")` (etc.) and wires callbacks
5. Button clicks drive the existing pure-Python business logic (`parse_csv_dense`, `transform_position`, `run_import`, …)

**Build flow (Designer bootstrap automation):**
1. `docs/widget-tree-spec.json` is the single source of truth for the full WidgetTree (33 contract + decorative nesting + widget properties + slot padding).
2. `build_widget_blueprint.run_build()` parses the spec → calls `UPostRenderToolBuildHelper` (C++ bridge, 3 UFUNCTIONs) to mutate `UWidgetBlueprint.WidgetTree`. Python cannot touch WidgetTree directly (`BaseWidgetBlueprint.h:16-17` → bare `UPROPERTY()` without `BlueprintVisible` is invisible to Python reflection per `PyGenUtil.cpp::IsScriptExposedProperty`).
3. `widget_properties.apply_widget_properties/apply_slot_properties` sets per-widget + slot-layout values via `set_editor_property()` reflection.
4. `unreal.BlueprintEditorLibrary.compile_blueprint` + `unreal.EditorAssetLibrary.save_asset` persist the `.uasset`.
5. Idempotent: rerun only creates widgets that are missing by name; existing ones (possibly user-tweaked in Designer) are left untouched. Properties/slot are applied ONLY on fresh creation — user edits survive.
6. C++ side: `UPostRenderToolBuildHelper` exposes `EnsureRootPanel`, `FindWidgetByName`, `EnsureWidgetUnderParent` (the latter returns `(result_enum, widget, slot)` as a Python tuple via UFUNCTION out-params).

Pure-Python modules (`csv_parser`, `coordinate_transform`, `validator`, `spec_loader`, `widget_properties`) have no `unreal` import and are testable outside UE Editor.

## Gotchas

- **Coordinate transform defaults are VERIFIED (2026-04-20).** `config.py` POSITION_MAPPING swaps
  Disguise (z, x, y) → UE (X, Y, Z) all positive ×100; ROTATION_MAPPING is identity per axis.
  Validated against an FBX-imported camera wrapped in a Z=+90° parent Actor (the user-confirmed
  correct reference); two pose pairs match to <0.001 cm / <0.001°. Regression-guarded by
  `tests/test_coordinate_transform.py::TestKnownPoses` — rerun after any axis-mapping change.
- **Distortion 完全由 Path C 接管,LensFile 已下架(2026-05-08).** Pipeline 不再
  生成 `LF_*` 资产、不再挂 LensComponent 到 camera。Distortion 走
  `M_PRT_OfficialSensorInverse` material + `PostRenderDistortionControllerComponent`,
  7 条参数轨由 `sequence_builder.py` 写入 LevelSequence。如果未来 Path C 出现
  不可调和 regression 需要回退,Path A 代码快照在 git 历史(原
  `archive/path_a_runtime/`,内含回退 README)。**不要**重新引入 LensFile 路径 —— 没经过验证就同时跑两条
  路线 = `apply_distortion` 没关时双倍畸变。
- **per-frame 参数现在走 Custom MovieScene Track (2026-05-13),不再走 19 条 Float Track.**
  Sequencer UI 上 camera binding 下只看到 1 条 PostRenderCameraTrack
  (Post-Render Camera Samples horizontal section) + 1 条 Camera Cut Track —
  这是正常状态,不是"数据丢了". 每帧 K1/K2/K3/CenterU/CenterV/Aspect/
  Overscan/Sensor offset/transform/focal/aperture/focus_distance 全部存在
  配对的 `LS_<csv_stem>_Samples` DataAsset 里(同目录, sample count 跟原 CSV
  帧数一致). Evaluator 在评估时按 FFrameTime 从 DataAsset 取插值后写到
  CineCameraActor + DistortionController. 要看具体数值,Content Browser 打开
  Samples DataAsset 看 Details 面板. 旧 Float Track 路径在 git 历史里
  (commit `f6f71fb` 之前), 不归档到 archive/.
- **如何 override 单帧/少量帧** (Custom MovieScene Track 之后的工作流).
  Custom track 的 sample DataAsset 设计上是只读的 dense tracker 数据,
  不能在 Sequencer 里直接调任意一帧. 如果需要修正几帧 (例如修一个
  tracker glitch / 加 jitter / 手 key 一段 zoom),正确做法是在 **同一个
  camera binding 上额外加一条 Transform Track 或 Float Track** 打 1-2 个
  keyframe 做 additive override. Sequencer 评估顺序: Custom track 先把
  base sample 写到 actor → Transform/Float track 后 evaluate 覆盖
  对应通道. 几个 keyframe 不会引起任何卡顿 (旧的 68k 帧问题源头是
  *dense* keyframes,不是 keyframes 本身). 不要重新 import CSV 修单帧 —
  那样会重写整个 sample DataAsset,丢失之前的所有手动修正.
- **Path A 史料归档位置.** 全部在 git 历史(2026-07-10 清理前):runtime 代码在
  原 `archive/path_a_runtime/`;公式拟合脚本 / UV probe 资产 / k1_sweep dataset 在
  原 `scripts/distortion_calibration/{archive,validation_results/archive}/`
  (commit `ce3cbcc` 归档);决策文档 / 5 个旧 plan 在原 `docs/archive/path_a/`。
  要复盘 K1 公式或 reverse-engineer K2/K3,checkout 清理 commit 的父提交。
- **Frame cadence preserved.** sequence_builder uses `frame_number - first_frame_number` as keyframe
  time, NOT consecutive indices. Gaps in CSV frame column create gaps in LevelSequence.
- **`PluginBlueprintLibrary.is_plugin_loaded()` does NOT work** in some UE builds.
  Use `hasattr(unreal, "ClassName")` to detect plugin availability instead.
- **UE Python module reload:** After editing config.py, use `importlib.reload()` — no UE restart needed.
- **UE Python reflection visibility:** `get_editor_property` / `dir()` only see
  UPROPERTYs with `CPF_BlueprintVisible | CPF_BlueprintAssignable`, or editor-only
  UPROPERTYs with `CPF_Edit` (see `PyGenUtil.cpp` `IsScriptExposedProperty` /
  `ShouldExportEditorOnlyProperty`). Bare `UPROPERTY()` is invisible from Python.
- **BindWidget requires explicit `BlueprintReadOnly`.** `UPROPERTY(meta=(BindWidget))`
  alone is NOT Python-visible. You must write
  `UPROPERTY(BlueprintReadOnly, meta=(BindWidget)) UButton* btn_foo;`
  to make `host.get_editor_property("btn_foo")` work from Python. `BlueprintReadOnly`
  is what sets `CPF_BlueprintVisible`; `meta=(BindWidget)` is the UMG compiler hint
  that auto-binds the pointer to a same-named widget in the child Blueprint.
- **Live Coding does NOT support UPROPERTY changes.** Adding, removing, or renaming
  a BindWidget UPROPERTY in `PostRenderToolWidget.h` requires a full Editor restart
  and a full plugin rebuild (UHT must re-run to regenerate reflection metadata).
  Live Coding only works for method body edits. Child Blueprints must be recompiled
  after parent UPROPERTY changes.
- **Python-vs-Designer name drift is a silent bug.** A mismatch between
  `_REQUIRED_CONTROLS` in `widget.py` and the UPROPERTY names in
  `PostRenderToolWidget.h` causes `get_editor_property()` to return None, and the
  binder logs a warning but keeps going. Keep the two sides in sync; see
  `docs/bindwidget-contract.md` for the authoritative list.
- **JSON spec is the fourth source of truth for widget names.** Besides `PostRenderToolWidget.h`
  UPROPERTY names and `widget.py`'s `_REQUIRED_CONTROLS`/`_OPTIONAL_CONTROLS`, `docs/widget-tree-spec.json`
  also lists the 33+8 contract names. Three-way drift (C++ / widget.py / JSON) is detected by
  `post_render_tool/tests/test_spec_drift.py` — rerun it after any contract rename.
- **`UWidget::bIsVariable` cannot be set from business C++.** Widget.h:318 is a private bitfield with
  no public setter; `UMGEditor::SWidgetDetailsView.cpp:641` is the only code that writes it (because
  UMGEditor module has compile-time private access). Workaround: `Widget.cpp:195` constructor
  initializes it to `true` by default, which satisfies BindWidget reflection for all widgets
  constructed via `UWidgetTree::ConstructWidget`. Cost: decorative widgets become variables too
  (harmless; a few extra UPROPERTYs on the generated class).
- **Widget tree structural changes need `FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified`,
  not `Blueprint->Modify()`.** `Modify()` is Undo-only; structural mutations require the stronger
  marker to invalidate the generated class layout for the next compile. Used inside
  `UPostRenderToolBuildHelper::{EnsureRootPanel,EnsureWidgetUnderParent}`.
- **C++ UFUNCTION changes require full Editor restart + plugin rebuild.** Live Coding registers new
  UFUNCTIONs inconsistently. After touching `PostRenderToolBuildHelper.h`/`.cpp`, quit the Editor,
  rebuild the plugin via UBT, relaunch, and verify `unreal.PostRenderToolBuildHelper.ensure_widget_under_parent`
  is visible in `help(unreal.PostRenderToolBuildHelper)` before running `build_widget_blueprint.run_build()`.

## 多版本支持(UE 5.1–5.8)

目标:一条命令编出 UE 5.1–5.8 全部 Win64 编辑器插件包。范围决策(2026-07-10):
不支持 5.0(lanPC 未安装,用户量低);Mac/Linux 不在范围。

**打包流程:**
- Mac 侧:`scripts/package_releases.sh` — rsync 白名单源码到 lanPC → ssh 触发
  批量打包 → 拉回汇总与日志。
- lanPC 侧:`scripts/build_all_versions.ps1` — 对每个版本:复制源码到 temp →
  改写 `.uplugin` 的 `EngineVersion` → `RunUAT.bat BuildPlugin` → zip 到
  `E:\PluginReleases\PostRenderTool_<ver>_Win64.zip`。源码里 `.uplugin` 永远
  保持 `5.7.0`,版本改写只发生在打包 temp 中。
- **≤5.6 的包剔除 `Content/Blueprints`、`Content/Materials` 下的 `.uasset`**
  (5.7 保存的资产老引擎打不开),用户装好后在目标引擎里跑
  `rebuild_from_spec()` + `build_distortion_material.run_build()` 现场生成。

**跨版本问题记录表**(2026-07-10 首轮适配实测,全部 8 版本编译通过):

| 版本 | 问题 | 处理方式 |
|---|---|---|
| 全部 | BuildPlugin 按引擎插件严格模式编译,BindWidget UPROPERTY 缺显式 Category 报错(项目内编译不强制) | 源码修复:40 个 UPROPERTY 加 `Category="PostRenderTool"` |
| ≤5.5 | `ISequencerTrackEditor::GetDisplayName` 是 5.6 新增虚函数,老版本 override 报 C3668 | 版本宏 `>=5.6`(`PostRenderCameraTrackEditor.h/.cpp`) |
| ≤5.4 | `FCameraFilmbackSettings.SensorHorizontal/VerticalOffset` 与 `UCineCameraComponent.Overscan` 不存在(5.5 起才有,实测) | 版本宏 `>=5.5`;老版本**降级**:centerShift/overscan 修正禁用 + 一次性 log warning(`PostRenderCameraSectionTemplate.cpp`) |
| 5.1 | `UScrollBox::GetWheelScrollMultiplier` getter 不存在(5.2 加入),5.1 直接读 public 成员 `WheelScrollMultiplier` | 版本宏 `>=5.2`(`PostRenderToolWidget.cpp`) |
| ≤5.4 | 引擎不兼容新 MSVC 14.44(引擎自身头文件 `__has_feature` 报错) | 环境:lanPC VS2022 Professional 加装 14.33(给 5.1)+ 14.34(给 5.2–5.4),打包脚本按版本写 `BuildConfiguration.xml` pin `CompilerVersion`(须用完整版本号如 `14.34.31933`,只写 `14.34` 匹配不上) |
| — | macOS tar 的 AppleDouble `._*` 文件会被 UBT 当源码编译 | `package_releases.sh` 用 `COPYFILE_DISABLE=1` + `--exclude '._*'` |
| — | lanPC 无 rsync;PS 5.1 here-string 结尾符不能缩进;`powershell -File` 下逗号列表是单字符串;`setup.exe` 不认 `--wait`(87) | 均已修进脚本;VS 组件安装用 `modify --channelId VisualStudio.17.Release --productId ...` |

**功能降级表(≤5.4,发布 README 必须写明):**
- centerShift 修正(SensorOffset)与 overscan 补边不可用 → 大 centerShift 镜头
  有几何偏移、大畸变镜头边缘有黑边。radial distortion(K1/K2/K3)本身不受影响。

版本宏统一写法:`#include "Runtime/Launch/Resources/Version.h"` +
`#if ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= N`。每轮改动后必须
全量重跑 `scripts/package_releases.sh` 回归全部版本。编译通过 ≠ 功能正确:
发布前至少在最老支持版本 + 最新版本各跑一次完整 import 验证
(资产生成 → run_import → Sequencer scrub)。Python 侧 `unreal` API 差异
编译期查不出,只能靠上述运行时验证。

## UE Source Code Reference

UE 5.7 engine source: `/Users/bip.lan/AIWorkspace/vp/UnrealEngine/`

For uncertain UE Python API behavior, read the source directly instead of guessing:
- `Engine/Plugins/Experimental/PythonScriptPlugin/Source/PythonScriptPlugin/Private/PyGenUtil.cpp`
  — property/function script-exposure rules (`IsScriptExposedProperty`, `ShouldExportEditorOnlyProperty`)
- `Engine/Source/Runtime/UMG/` — UMG runtime (`UserWidget`, `WidgetTree`, `PanelWidget`)
- `Engine/Source/Editor/UMGEditor/` — `WidgetBlueprint`, `WidgetBlueprintCompiler` (BindWidget validation lives here)
- `Engine/Source/Editor/Blutility/` — `EditorUtilityWidget`, `EditorUtilityWidgetBlueprintFactory`, `EditorUtilitySubsystem`
- `Engine/Source/Editor/BlueprintEditorLibrary/Public/BlueprintEditorLibrary.h` — `CompileBlueprint` UFUNCTION

For API edge cases, dispatch an `Explore` subagent with a concrete question (e.g. "verify X is a UFUNCTION in UE 5.7") and require `file:line` citations. Faster than grepping the engine source yourself and keeps the main context clean.

## Remote UE Test Environment (lanPC)

The plugin is exercised inside UE 5.7 Editor on `lanPC` (Windows 11 workstation). SSH alias is already configured in `~/.ssh/config` via the global `CLAUDE.md`.

- SSH entry: `ssh lanpc` → `lanpc@192.168.10.20` (SSH key via 1Password Agent)
- UE 5.7 install: `D:\Program Files\Epic Games\UE_5.7\` (other versions UE_4.27 / 5.1–5.6 coexist under the same root)
- Target project: `E:\RenderStream Projects\test_0311\test_0311.uproject`
- Plugin location: `E:\RenderStream Projects\test_0311\Plugins\post-render-tool\`

**PowerShell remote execution pattern:**
- Pipe script via stdin: `echo '<ps-cmd>' | ssh lanpc powershell -Command -`
- Avoid inline `ssh lanpc 'powershell -Command "..."'` — Bash eats `\t` inside Windows paths like `E:\test_0311` before `ssh` sees it
- For paths with spaces, use `-LiteralPath "forward/slash/path"` — PowerShell accepts `/` on Windows
- `Get-ChildItem -Include *.uasset` only works with `-Path` + wildcard; with `-LiteralPath` use `-Filter "*.uasset"` instead

### UE Python Remote Execution（从 Mac 直接 dispatch）

走这条路就能跳过"复制 Python 到 UE Output Log"的来回，直接从 Mac 把 `unreal.*` 代码远程跑到 lanPC 上的 UE Editor。

**一次性开关**（已设置好；新项目/新机器需要时再开）：
- UE Editor → **Edit → Project Settings → Plugins → Python** → 勾 **Enable Remote Execution** → 重启 Editor

**已就绪的资产**：
- bridge 脚本：lanPC 上 `C:/temp/ue-remote/run_ue.py`（接受文件路径参数）

**标准用法**：

```bash
# 1. Mac 上写诊断/补丁脚本（UTF-8，支持中文）
cat > /tmp/ue_diag.py <<'PY'
import unreal
print(unreal.SystemLibrary.get_engine_version())
PY

# 2. SCP 过去 + 远程跑
scp /tmp/ue_diag.py lanpc:C:/temp/ue-remote/diag.py
ssh lanpc '"D:\Program Files\Epic Games\UE_5.7\Engine\Binaries\ThirdParty\Python3\Win64\python.exe" C:/temp/ue-remote/run_ue.py C:/temp/ue-remote/diag.py'
```

**注意**：脚本必须 SCP 文件传，不要 `cat | ssh ... powershell stdin`——PowerShell 默认 UTF-16 会把中文搞坏。

<!-- DOCSMITH:KNOWLEDGE:BEGIN -->
## Knowledge Base (Managed by Docsmith)

- Knowledge entrypoint: `.claude/knowledge/_INDEX.md`
- Config file: `.claude/knowledge.json`

### Current Sources
- `developer-disguise-one` (8 files) → `.claude/knowledge/developer-disguise-one/`
- `disguise_api` (11 files) → `.claude/knowledge/disguise_api/`
- `disguise_python_api` (11 files) → `.claude/knowledge/disguise_python_api/`
- `help-disguise-one` (262 files) → `.claude/knowledge/help-disguise-one/`
- `ue50-docs` (292 files) → `.claude/knowledge/ue50-docs/`
- `ue51-docs` (284 files) → `.claude/knowledge/ue51-docs/`
- `ue52-docs` (333 files) → `.claude/knowledge/ue52-docs/`
- `ue53-docs` (29 files) → `.claude/knowledge/ue53-docs/`
- `ue54-docs` (321 files) → `.claude/knowledge/ue54-docs/`
- `ue55-docs` (324 files) → `.claude/knowledge/ue55-docs/`
- `ue56-docs` (389 files) → `.claude/knowledge/ue56-docs/`
- `ue57-docs` (2205 indexed docs, compact loader) → `.claude/knowledge/ue57-docs/`

### Query Protocol
1. Read `.claude/knowledge/_INDEX.md` to route to the relevant source.
2. Open `<source>/_INDEX.md` and shortlist target documents by `topic/summary/keywords`.
3. Read target file TL;DR first, then read full content when needed.
4. Before answering, prioritize evidence from `KnowledgeBase docs`; use external knowledge only when KB coverage is insufficient.
5. In every answer, include:
   - `Knowledge Sources`: exact KB document paths used.
   - `External Inputs`: non-KB knowledge used and why.
   - If no KB match: `No relevant KnowledgeBase docs found`.

### Refresh Command
```bash
.venv/bin/python -m cli --project-links --refresh-index .
```
<!-- DOCSMITH:KNOWLEDGE:END -->
