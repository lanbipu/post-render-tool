# BindWidget 契约参考

C++ 类 `UPostRenderToolWidget`（`Source/PostRenderTool/Public/PostRenderToolWidget.h`）通过 `UPROPERTY(BlueprintReadOnly, meta=(BindWidget))` 声明 widget 指针；子蓝图 `BP_PostRenderToolWidget`（`Content/Blueprints/`）**必须**包含名称和类型都匹配的 widget，否则蓝图编译失败：

> `A required widget binding "<name>" of type <type> was not found.`

Python（`Content/Python/post_render_tool/widget.py`）通过 `host.get_editor_property("<name>")` 读回同样的名称。**C++、Blueprint、Python 三方必须在名称和类型上完全一致。**

## 目录

1. [绑定机制（三层架构）](#1-绑定机制三层架构)
2. [类型命名约定](#2-类型命名约定)
3. [契约清单](#3-契约清单)
4. [装饰元素](#4-装饰元素)
5. [Designer 填写手册（按 Section 顺序）](#5-designer-填写手册按-section-顺序)
6. [Designer 操作流程](#6-designer-操作流程)
7. [折叠头 vs `btn_recheck`：常见混淆](#7-折叠头-vs-btn_recheck常见混淆)
8. [新增 / 移除绑定](#8-新增--移除绑定)
9. [故障排除](#9-故障排除)

---

## 1. 绑定机制（三层架构）

控件"功能连通"由三层机制自动完成，Designer 里**不需要拖任何事件连线**，名字对上即生效：

1. **C++ 契约层** ([PostRenderToolWidget.h](../Source/PostRenderTool/Public/PostRenderToolWidget.h))
   ```cpp
   UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
   UButton* btn_browse;
   ```
   - `meta=(BindWidget)` —— 告诉 UMG 编译器"子 BP 必须有个同名同类型的控件"
   - `BlueprintReadOnly` —— 设置 `CPF_BlueprintVisible` flag，让 Python 反射能看见（否则 `get_editor_property` 返回 `None`）

2. **UMG 自动绑定层**（BP 编译时）
   - BP 编译时按 **控件 Name + Type** 自动填充 C++ 指针，**无需人工操作**
   - 缺少必需控件 → 编译失败 `A required widget binding "X" of type Y was not found`
   - 类型不符 → 同样报错（例如把 `btn_import` 拖成 `Border` 而非 `Button`）
   - **不要取消 "Is Variable" 勾选** —— 取消后 UMG 不生成该控件的 UPROPERTY backing field，绑定失败

3. **Python 取引用 + 挂回调层** ([widget.py:99–113](../Content/Python/post_render_tool/widget.py#L99-L113))
   ```python
   ref = host.get_editor_property("btn_browse")   # 拿到已绑好的指针
   ref.on_clicked.add_callable(self._on_browse)   # 挂 Python 回调
   ```
   所有事件绑定集中在 `widget.py` 的 `_bind_events()` 方法里，改行为只改 Python，无需重新构建 C++。

---

## 2. 类型命名约定

C++ / Designer Palette / Python 三套命名指向同一个类，反射系统自动转换：

| C++ 类名 | Designer Palette 显示 | Python 类 |
|---|---|---|
| `UButton` | `Button` | `unreal.Button` |
| `UTextBlock` | `Text` / `Text Block` | `unreal.TextBlock` |
| `USpinBox` | `Spin Box` | `unreal.SpinBox` |
| `UComboBoxString` | `Combo Box (String)` | `unreal.ComboBoxString` |
| `UMultiLineEditableText` | `Editable Text (Multi-Line)` | `unreal.MultiLineEditableText` |

**`U` 前缀 = UObject 继承链**（有反射 / GC / 序列化）。UE 反射在生成元数据时会剥掉 C++ 前缀：

- 本文档契约表用 C++ 原名（`UButton`），与头文件 UPROPERTY 类型一致
- Designer 里搜控件用"人类名"（`Button`），搜 `UButton` 反而搜不到
- Python 调用用 `unreal.Button`，前缀同样被剥离

三者指向同一个类，不会产生歧义。其他常见 UE 前缀：`A` = AActor、`F` = struct、`I` = interface、`T` = 模板、`E` = enum。

---

## 3. 契约清单

### 3.1 必需控件（33 个）

使用 `meta=(BindWidget)` —— 缺失会让 BP 编译失败。

| 区块 | 名称 | 类型 |
|---|---|---|
| Prerequisites | `btn_recheck` | `UButton` |
| CSV File | `btn_browse` | `UButton` |
| CSV File | `txt_file_path` | `UTextBlock` |
| CSV Preview | `txt_frame_count` | `UTextBlock` |
| CSV Preview | `txt_focal_range` | `UTextBlock` |
| CSV Preview | `txt_timecode` | `UTextBlock` |
| CSV Preview | `txt_sensor_width` | `UTextBlock` |
| CSV Preview | `spn_fps` | `USpinBox` |
| CSV Preview | `txt_detected_fps` | `UTextBlock` |
| Coord Verification | `spn_frame` | `USpinBox` |
| Coord Verification | `txt_designer_pos` | `UTextBlock` |
| Coord Verification | `txt_designer_rot` | `UTextBlock` |
| Coord Verification | `txt_ue_pos` | `UTextBlock` |
| Coord Verification | `txt_ue_rot` | `UTextBlock` |
| Coord Verification | `btn_spawn_cam` | `UButton` |
| Axis Mapping — Pos | `cmb_pos_x_src` | `UComboBoxString` |
| Axis Mapping — Pos | `spn_pos_x_scale` | `USpinBox` |
| Axis Mapping — Pos | `cmb_pos_y_src` | `UComboBoxString` |
| Axis Mapping — Pos | `spn_pos_y_scale` | `USpinBox` |
| Axis Mapping — Pos | `cmb_pos_z_src` | `UComboBoxString` |
| Axis Mapping — Pos | `spn_pos_z_scale` | `USpinBox` |
| Axis Mapping — Rot | `cmb_rot_pitch_src` | `UComboBoxString` |
| Axis Mapping — Rot | `spn_rot_pitch_scale` | `USpinBox` |
| Axis Mapping — Rot | `cmb_rot_yaw_src` | `UComboBoxString` |
| Axis Mapping — Rot | `spn_rot_yaw_scale` | `USpinBox` |
| Axis Mapping — Rot | `cmb_rot_roll_src` | `UComboBoxString` |
| Axis Mapping — Rot | `spn_rot_roll_scale` | `USpinBox` |
| Axis Mapping | `btn_apply_mapping` | `UButton` |
| Axis Mapping | `btn_save_mapping` | `UButton` |
| Actions | `btn_import` | `UButton` |
| Actions | `btn_open_seq` | `UButton` |
| Actions | `btn_open_mrq` | `UButton` |
| Actions | `txt_results` | `UMultiLineEditableText` |

### 3.2 可选控件（8 个）

使用 `meta=(BindWidgetOptional)` —— 缺失不会导致 BP 编译失败，但对应 Python 功能**静默降级**。

| 名称 | 类型 | 所在 Section | 缺失时的降级表现 |
|---|---|---|---|
| `prereq_label_0` ~ `prereq_label_5` | `UTextBlock` | Section 1 内容区 | 6 条插件状态行不显示（汇总计数仍工作） |
| `prereq_summary` | `UTextBlock` | Section 1 折叠头 | "N / 6 OK" 徽章不显示 |
| `txt_frame_hint` | `UTextBlock` | Section 4 frame_row | SpinBox 旁"15 / 974"帧号提示不显示 |

### 3.3 Python 侧契约

`widget.py` 声明了两个 tuple，与 C++ 侧一一对应：

- `_REQUIRED_CONTROLS` —— 33 个条目，对应 [3.1](#31-必需控件33-个)
- `_OPTIONAL_CONTROLS` —— 8 个条目，对应 [3.2](#32-可选控件8-个)

如果 Python 侧的 tuple 与 C++ 声明漂移（drift），`get_editor_property()` 对缺失名称返回 `None`，binder 打印 warning 继续执行。**三方必须始终同步**。

---

## 4. 装饰元素

UI 里的 **section 标题、行内标签、分隔符号、卡片背景、Section Header 橙色竖条** 等元素**完全不属于 41 契约**，是纯装饰，UMG 编译器不会检查它们的存在。

### 4.1 装饰件 vs 功能件：判定标准

| 属性 | 41 契约控件（功能件） | 装饰件 |
|---|---|---|
| **作用** | Python 读值 / 监听事件 | 纯视觉，给人看 |
| **Name 必须精确** | ✅（如 `btn_browse`） | ❌ 不强制 |
| **Type 必须精确** | ✅ 与 C++ 声明一致 | ❌ 随意（TextBlock / Image / Border / SizeBox …） |
| **Is Variable** | ✅ 必须勾选 | ❌ 可取消（省 UPROPERTY） |
| **Python 会访问** | 是 | 否 |
| **少了会怎样** | BP 编译失败 或 Python 降级 | 只是丑，不影响运行 |

### 4.2 装饰件命名约定（非强制但推荐）

装饰件 Name 用 `lbl_` 前缀（如 `lbl_section_csv_file`、`lbl_fps`、`lbl_x_separator`），和功能件的 `btn_` / `txt_` / `spn_` / `cmb_` 前缀明确分开，便于在 Hierarchy 里一眼分辨。默认 `TextBlock_0` 这类名字能跑但不便维护。

### 4.3 Section Header 橙色竖条

Figma 所有 6 个 Section Header 左侧共用的视觉锚点：`#E8704D`、3×13、1px 圆角。

**UMG 实现**（`SizeBox` + `Image`，装饰件，不入契约）：

| 层级 | 控件 | 关键属性 |
|---|---|---|
| 外层 | `SizeBox` | `WidthOverride=3`、`HeightOverride=13`；HorizontalBox slot：`Size=Auto`、`VAlign=Center`、`Padding=0,0,8,0` |
| 内层 | `Image` | `Brush > Image=None`；`Brush > Tint Color=(R=0.909, G=0.439, B=0.302, A=1.0)`（≈`#E8704D`）；`Brush > Image Size=(X=3, Y=13)`；`Brush > Draw As=Box` |

UMG `Image` 不原生支持圆角，3×13 尺度下 1px 圆角肉眼几乎不可见，**直接忽略即可**。

**复用**：6 个 Section 共用一对 `SizeBox + Image` → 建议抽成独立 User Widget（`WBP_SectionAccent`）在 6 处 Header 里引用，改色只改一次。

### 4.4 卡片外壳

每个 Section 用 `Border` 作卡片外壳：`Brush Color=#242424`、`Padding=12,10,12,10`；外层 `ScrollBox > VerticalBox`，Section 间隔 8px。

---

## 5. Designer 填写手册（按 Section 顺序）

### 5.1 填写总则

每个子控件的 **Text / Value** 默认值按三类处理：

| 类别 | 做法 | 原因 |
|---|---|---|
| **A. 装饰件**（标题、标签、分隔符、橙条） | 按 Figma 设计字面值填 | Python 不访问，Designer 是唯一真相来源 |
| **B. 功能件·Button 子 TextBlock** | 按 Figma 字面值填（如 `"Browse..."`） | Python 不改 Button 文字，Designer 是真相来源 |
| **C. 功能件·Python 会覆盖**（大部分 `txt_*`、`spn_*`、`cmb_*`） | **留空 / 默认值** | widget.py `__init__` 会无条件覆盖；留空可在 binding 漂移时暴露故障 |

**特别警告 —— 绝不填"示意内容"伪造成功态**：

`prereq_label_0..5`、`txt_results` 等 **Python 覆盖的 TextBlock**，Designer 占位 **必须留空串**。若填 `"OK: LiveLinkCamera"`、`"[OK] Import finished"` 之类的"演示文本"，一旦 binding 漂移（控件返回 `None`、widget.py:242 短路跳过），用户会看到**伪造的绿灯**，误以为状态正常。

| 占位做法 | Binding 成立时 | Binding 漂移时 | 是否推荐 |
|---|---|---|---|
| **空串 `""`** | Python 覆盖成 `OK: ...` / `MISSING: ...` | 保留空白 → 立刻察觉未刷新 | ✅ 推荐 |
| 填 `"OK: XXX"` 示意字 | 被覆盖，看不到 | **伪装成功** → 用户受骗 | ❌ 危险 |
| 空格 `" "` | 被覆盖 | 和空串视觉一样 | ❌ 不推荐（diff 干扰） |
| 删掉整个 TextBlock | — | — | ❌ 禁止（BP 编译失败） |
| `Visibility = Collapsed` | 覆盖成功但看不到 | 永远看不到 | ❌ 禁止 |

**只改 Text / Value，不要动 widget 本身的存在性和 Visibility。**

### 5.2 层级图例

所有 Section 用统一的树形记法描述 UMG Hierarchy 面板的精确嵌套关系：

```
Widget                                 [标签] name                            关键属性
```

| 字段 | 说明 |
|---|---|
| **Widget** | UMG 控件类型（C++ 类名去前缀，与 [§3 契约表](#3-契约清单) / Python 名一致；Designer Palette 搜索时用人类名见 [§2](#2-类型命名约定)） |
| **[标签]** | `[契约]` = 必需契约（精确命名，勾 Is Variable）；`[可选]` = 可选契约（同上）；`[装饰]` = 装饰件（命名非强制，建议 `lbl_` 前缀） |
| **name** | 契约控件严格按表名；装饰件按层级语义起名 |
| **关键属性** | Text 值、Size、Brush Color、Padding 等 Designer 里需手填的值 |

### 5.3 根布局

```
CanvasPanel                            [装饰] (EditorUtilityWidget 默认根，保留不动)
└─ ScrollBox                           [装饰] lbl_root_scroll                  Anchors=Fill, Offsets=0,0,0,0
   └─ VerticalBox                      [装饰] lbl_sections                     Padding=12,12,12,12
      ├─ Border                        [装饰] lbl_card_prereq                  (Section 1)
      ├─ Border                        [装饰] lbl_card_csv_file                (Section 2)
      ├─ Border                        [装饰] lbl_card_csv_preview             (Section 3)
      ├─ Border                        [装饰] lbl_card_coord                   (Section 4)
      ├─ Border                        [装饰] lbl_card_axis                    (Section 5)
      └─ Border                        [装饰] lbl_card_actions                 (Section 6)
```

每个 Section Border 共用属性：`BrushColor=#242424`、`Padding=12,10,12,10`；所在 VerticalBox slot 的 `Padding=0,0,0,8`（下边距 8px，最后一张不加）。

### 5.4 Section 1 — Prerequisites（折叠头 + 内容区）

```
Border                                 [装饰] lbl_card_prereq                  BrushColor=#242424, Padding=12,10,12,10
└─ VerticalBox                         [装饰] lbl_prereq_vbox
   ├─ HorizontalBox                    [装饰] lbl_prereq_header                (折叠头；OnClicked 切换 body Visibility；见 §7 方案 2)
   │  ├─ TextBlock                     [装饰] lbl_prereq_arrow                 Text="▶" (展开后 BP 里切成 "▼")
   │  ├─ SizeBox                       [装饰] lbl_prereq_accent                WidthOverride=3, HeightOverride=13, VAlign=Center, Padding=8,0,8,0
   │  │  └─ Image                      [装饰] lbl_prereq_accent_img            Brush: Tint=#E8704D, ImageSize=(3,13), DrawAs=Box
   │  ├─ TextBlock                     [装饰] lbl_prereq_title                 Text="Prerequisites"
   │  ├─ Spacer                        [装饰] lbl_prereq_header_spacer         Slot.FillSize=1.0 (推下一项右对齐)
   │  └─ TextBlock                     [可选] prereq_summary                   Text="" (Python 写 "N / 6 OK")
   └─ VerticalBox                      [装饰] lbl_prereq_body                  Visibility=Visible (BP OnClicked 切换；初始态按需)
      ├─ HorizontalBox                 [装饰] lbl_prereq_row_0
      │  ├─ SizeBox                    [装饰] lbl_prereq_dot_0                 WidthOverride=8, HeightOverride=8, VAlign=Center, Padding=0,0,8,0
      │  │  └─ Image                   [装饰] lbl_prereq_dot_0_img             Brush: Tint=#CCCCCC, ImageSize=(8,8) (圆点可用 circle brush 或默认方块)
      │  └─ TextBlock                  [可选] prereq_label_0                   Text="" (绝不填"OK: XXX"，见 §5.1 警告)
      ├─ HorizontalBox                 [装饰] lbl_prereq_row_1                 (同构：SizeBox lbl_prereq_dot_1 + TextBlock prereq_label_1)
      ├─ HorizontalBox                 [装饰] lbl_prereq_row_2                 (同构：lbl_prereq_dot_2 + prereq_label_2)
      ├─ HorizontalBox                 [装饰] lbl_prereq_row_3                 (同构：lbl_prereq_dot_3 + prereq_label_3)
      ├─ HorizontalBox                 [装饰] lbl_prereq_row_4                 (同构：lbl_prereq_dot_4 + prereq_label_4)
      ├─ HorizontalBox                 [装饰] lbl_prereq_row_5                 (同构：lbl_prereq_dot_5 + prereq_label_5)
      └─ HorizontalBox                 [装饰] lbl_prereq_bottom_row            Padding=0,8,0,0
         └─ Button                     [契约] btn_recheck                      (Is Variable=✓)
            └─ TextBlock               [装饰] lbl_btn_recheck_text             Text="Recheck", Slot.Padding=14,6,14,6
```

**Python 覆盖后的 `prereq_label_*` 实际文本**（widget.py:246–251 + ui_interface.py:188–201）：

- OK：`OK: <plugin display name>`（例：`OK: Camera Calibration`）
- MISSING（有 hint）：`MISSING: <name> → <hint>`
- MISSING（无 hint，仅 `CineCameraActor` / `EditorUtilitySubsystem`）：`MISSING: <name>`（无箭头后缀）

6 个插件顺序：`Python Editor Script Plugin` / `Editor Scripting Utilities` / `Camera Calibration` / `CineCameraActor` / `LevelSequence` / `EditorUtilitySubsystem`。

### 5.5 Section 2 — CSV File

```
Border                                 [装饰] lbl_card_csv_file
└─ VerticalBox                         [装饰] lbl_csv_file_vbox
   ├─ HorizontalBox                    [装饰] lbl_csv_file_header
   │  ├─ SizeBox                       [装饰] lbl_csv_file_accent              3×13 橙条 (§4.3)
   │  │  └─ Image                      [装饰] lbl_csv_file_accent_img          Tint=#E8704D
   │  └─ TextBlock                     [装饰] lbl_csv_file_title               Text="CSV File", Slot.Padding=8,0,0,0
   └─ HorizontalBox                    [装饰] lbl_csv_file_row                 Padding=0,8,0,0
      ├─ Button                        [契约] btn_browse                       (Is Variable=✓)
      │  └─ TextBlock                  [装饰] lbl_btn_browse_text              Text="Browse...", Slot.Padding=14,6,14,6
      └─ TextBlock                     [契约] txt_file_path                    Text="" (Python 写绝对路径), Slot.Padding=10,6,0,6, Slot.FillSize=1.0
```

### 5.6 Section 3 — CSV Preview

```
Border                                 [装饰] lbl_card_csv_preview
└─ VerticalBox                         [装饰] lbl_csv_preview_vbox
   ├─ HorizontalBox                    [装饰] lbl_csv_preview_header
   │  ├─ SizeBox                       [装饰] lbl_csv_preview_accent           3×13 橙条
   │  │  └─ Image                      [装饰] lbl_csv_preview_accent_img       Tint=#E8704D
   │  └─ TextBlock                     [装饰] lbl_csv_preview_title            Text="CSV Preview"
   ├─ VerticalBox                      [装饰] lbl_csv_preview_stat             Padding=0,8,0,0
   │  ├─ TextBlock                     [契约] txt_frame_count                  Text="" (例:"Frames: 974")
   │  ├─ TextBlock                     [契约] txt_focal_range                  Text="" (例:"Focal Length: 30.30 – 30.30 mm")
   │  ├─ TextBlock                     [契约] txt_timecode                     Text="" (例:"Timecode: 00:00:30.00 → 00:00:30.00")
   │  └─ TextBlock                     [契约] txt_sensor_width                 Text="" (例:"Sensor Width: 35.00 mm")
   └─ HorizontalBox                    [装饰] lbl_csv_preview_fps_row          Padding=0,8,0,0
      ├─ TextBlock                     [装饰] lbl_fps                          Text="FPS", Slot.Padding=0,6,10,6
      ├─ SpinBox                       [契约] spn_fps                          Value=0.0 (Python 重设 min=0.0 / max=120.0)
      └─ TextBlock                     [契约] txt_detected_fps                 Text="" (Python 写 "detected: 23.976"), Slot.Padding=10,6,0,6
```

### 5.7 Section 4 — Coordinate Verification

```
Border                                 [装饰] lbl_card_coord
└─ VerticalBox                         [装饰] lbl_coord_vbox
   ├─ HorizontalBox                    [装饰] lbl_coord_header
   │  ├─ SizeBox                       [装饰] lbl_coord_accent                 3×13 橙条
   │  │  └─ Image                      [装饰] lbl_coord_accent_img             Tint=#E8704D
   │  └─ TextBlock                     [装饰] lbl_coord_title                  Text="Coordinate Verification"
   ├─ HorizontalBox                    [装饰] lbl_coord_frame_row              Padding=0,8,0,0
   │  ├─ TextBlock                     [装饰] lbl_frame                        Text="Frame", Slot.Padding=0,6,10,6
   │  ├─ SpinBox                       [契约] spn_frame                        Value=0 (Python 重设 min=0 / max=0；CSV 加载后重设 max=frame_count-1)
   │  └─ TextBlock                     [可选] txt_frame_hint                   Text="" (Python 写 "15 / 974"), Slot.Padding=10,6,0,6
   ├─ VerticalBox                      [装饰] lbl_coord_pair                   Padding=0,8,0,0
   │  ├─ TextBlock                     [装饰] lbl_designer_header              Text="DESIGNER (source)" (小号字，灰色)
   │  ├─ TextBlock                     [契约] txt_designer_pos                 Text=""
   │  ├─ TextBlock                     [契约] txt_designer_rot                 Text=""
   │  ├─ Border                        [装饰] lbl_coord_separator              H=1, BrushColor=#3A3A3A, Padding=0,6,0,6 (分隔线)
   │  ├─ TextBlock                     [装饰] lbl_ue_header                    Text="→ UE (result)" (小号字，灰色)
   │  ├─ TextBlock                     [契约] txt_ue_pos                       Text=""
   │  └─ TextBlock                     [契约] txt_ue_rot                       Text=""
   └─ Button                           [契约] btn_spawn_cam                    Slot.HAlign=Left, Slot.Padding=0,8,0,0
      └─ TextBlock                     [装饰] lbl_btn_spawn_cam_text           Text="Spawn Test Camera", Slot.Padding=14,6,14,6
```

### 5.8 Section 5 — Axis Mapping

```
Border                                 [装饰] lbl_card_axis
└─ VerticalBox                         [装饰] lbl_axis_vbox
   ├─ HorizontalBox                    [装饰] lbl_axis_header
   │  ├─ SizeBox                       [装饰] lbl_axis_accent                  3×13 橙条
   │  │  └─ Image                      [装饰] lbl_axis_accent_img              Tint=#E8704D
   │  └─ TextBlock                     [装饰] lbl_axis_title                   Text="Axis Mapping"
   ├─ TextBlock                        [装饰] lbl_pos_subheader                Text="POSITION (m → cm)", Slot.Padding=0,8,0,4 (小号字)
   ├─ VerticalBox                      [装饰] lbl_pos_rows
   │  ├─ HorizontalBox                 [装饰] lbl_row_ue_x
   │  │  ├─ TextBlock                  [装饰] lbl_ue_x                         Text="UE.X", Slot.Padding=0,6,8,6
   │  │  ├─ TextBlock                  [装饰] lbl_ue_x_arrow                   Text="←", Slot.Padding=0,6,8,6
   │  │  ├─ ComboBoxString             [契约] cmb_pos_x_src                    Options=空 (Python 覆盖为 ["X (0)","Y (1)","Z (2)"])
   │  │  ├─ TextBlock                  [装饰] lbl_ue_x_mul                     Text="×", Slot.Padding=8,6,8,6
   │  │  └─ SpinBox                    [契约] spn_pos_x_scale                  Value=0.0 (Python 按 config.POSITION_MAPPING["x"] 覆盖)
   │  ├─ HorizontalBox                 [装饰] lbl_row_ue_y                     (同构: lbl_ue_y / cmb_pos_y_src / spn_pos_y_scale)
   │  └─ HorizontalBox                 [装饰] lbl_row_ue_z                     (同构: lbl_ue_z / cmb_pos_z_src / spn_pos_z_scale)
   ├─ TextBlock                        [装饰] lbl_rot_subheader                Text="ROTATION (deg)", Slot.Padding=0,12,0,4
   ├─ VerticalBox                      [装饰] lbl_rot_rows
   │  ├─ HorizontalBox                 [装饰] lbl_row_pitch                    (同构: lbl_pitch / cmb_rot_pitch_src / spn_rot_pitch_scale)
   │  ├─ HorizontalBox                 [装饰] lbl_row_yaw                      (同构: lbl_yaw / cmb_rot_yaw_src / spn_rot_yaw_scale)
   │  └─ HorizontalBox                 [装饰] lbl_row_roll                     (同构: lbl_roll / cmb_rot_roll_src / spn_rot_roll_scale)
   └─ HorizontalBox                    [装饰] lbl_axis_btn_row                 Padding=0,8,0,0
      ├─ Button                        [契约] btn_apply_mapping                Slot.Padding=0,0,8,0
      │  └─ TextBlock                  [装饰] lbl_btn_apply_mapping_text       Text="Apply Mapping", Slot.Padding=14,6,14,6
      └─ Button                        [契约] btn_save_mapping
         └─ TextBlock                  [装饰] lbl_btn_save_mapping_text        Text="Save to config.py", Slot.Padding=14,6,14,6
```

**Axis 行内子控件约定**：每行 HorizontalBox 内的控件顺序固定为 `label → ← → ComboBox → × → SpinBox`，共 6 行，契约控件命名按 [§3.1](#31-必需控件33-个) 对照填。

### 5.9 Section 6 — Actions

```
Border                                 [装饰] lbl_card_actions
└─ VerticalBox                         [装饰] lbl_actions_vbox
   ├─ HorizontalBox                    [装饰] lbl_actions_header
   │  ├─ SizeBox                       [装饰] lbl_actions_accent               3×13 橙条
   │  │  └─ Image                      [装饰] lbl_actions_accent_img           Tint=#E8704D
   │  └─ TextBlock                     [装饰] lbl_actions_title                Text="Actions"
   ├─ Button                           [契约] btn_import                       Slot.HAlign=Fill, Slot.Padding=0,8,0,0 (大号按钮, 36 高)
   │  └─ TextBlock                     [装饰] lbl_btn_import_text              Text="Import", Slot.Padding=14,10,14,10
   ├─ HorizontalBox                    [装饰] lbl_actions_btn_row              Padding=0,8,0,0
   │  ├─ Button                        [契约] btn_open_seq                     Slot.FillSize=1.0, Slot.Padding=0,0,4,0
   │  │  └─ TextBlock                  [装饰] lbl_btn_open_seq_text            Text="Open Sequencer", Slot.Padding=14,6,14,6
   │  └─ Button                        [契约] btn_open_mrq                     Slot.FillSize=1.0, Slot.Padding=4,0,0,0
   │     └─ TextBlock                  [装饰] lbl_btn_open_mrq_text            Text="Open MRQ", Slot.Padding=14,6,14,6
   ├─ TextBlock                        [装饰] lbl_results_header               Text="RESULTS", Slot.Padding=0,12,0,4 (小号字)
   └─ MultiLineEditableText            [契约] txt_results                      Text="", IsReadOnly=✓, Slot 高度≈144px (Python 追加 [OK]/[WARN] 日志行)
```

### 5.10 契约控件速查（33 必需 + 8 可选 按层级位置）

便于 Designer 拖控件时核对是否漏了哪个契约名：

| Section | 必需 | 可选 |
|---|---|---|
| 1 Prerequisites | `btn_recheck` | `prereq_summary`、`prereq_label_0..5` |
| 2 CSV File | `btn_browse`、`txt_file_path` | — |
| 3 CSV Preview | `txt_frame_count`、`txt_focal_range`、`txt_timecode`、`txt_sensor_width`、`spn_fps`、`txt_detected_fps` | — |
| 4 Coordinate Verification | `spn_frame`、`txt_designer_pos`、`txt_designer_rot`、`txt_ue_pos`、`txt_ue_rot`、`btn_spawn_cam` | `txt_frame_hint` |
| 5 Axis Mapping | `cmb_pos_x_src`、`spn_pos_x_scale`、`cmb_pos_y_src`、`spn_pos_y_scale`、`cmb_pos_z_src`、`spn_pos_z_scale`、`cmb_rot_pitch_src`、`spn_rot_pitch_scale`、`cmb_rot_yaw_src`、`spn_rot_yaw_scale`、`cmb_rot_roll_src`、`spn_rot_roll_scale`、`btn_apply_mapping`、`btn_save_mapping` | — |
| 6 Actions | `btn_import`、`btn_open_seq`、`btn_open_mrq`、`txt_results` | — |
| **合计** | **33** | **8** |

---

## 6. Designer 操作流程

### 6.1 阶段 1 —— 裸控件（先通过 BP 编译）

**必须一次性拖完 33 个必需控件才能通过 BP 编译。** 缺一个 `BindWidget` → BP 无法保存、无法 spawn、Python 也进不去。

1. 按 [§3.1](#31-必需控件33-个) 拖完 33 个"裸控件"，**先不管布局 / 样式 / 嵌套**（Button 用默认方块、TextBlock 留空、全部平铺在 Canvas 或 VerticalBox 里）。约 5–10 分钟可完成
2. **Compile + Save** —— 通过后 Python 侧 `open_widget()` 即可驱动全部业务逻辑
3. 按 Section 顺序验证业务逻辑：浏览 CSV → 预览 → 坐标校验 → 轴映射 → Import → 打开 Sequencer / MRQ

**避免的方案**：临时把 `BindWidget` 改成 `BindWidgetOptional` —— 每切一次必须 "关闭 Editor → 重建 plugin → 重开项目"，每轮 3–5 分钟，来回切不划算。

### 6.2 阶段 2 —— 按 [§5 填写手册](#5-designer-填写手册按-section-顺序) 填 Text / Value

装饰件填字面值，功能件按类别处理（A/B/C 见 [§5.1](#51-填写总则)）。这一阶段完成后 UI 在编辑器里就是"静态正确"的。

### 6.3 阶段 3 —— 布局和美化

调 Hierarchy / Border / Padding / 字号 / 颜色等视觉参数时：

- ❌ **不要**改 widget 的 **Name** —— 会断 binding
- ❌ **不要**取消 **Is Variable** 勾选 —— 会断 binding
- ❌ **不要**改 widget 的 **Type** —— 类型不符会让 BP 编译失败
- ✅ 可以自由调 Appearance / Slot / Padding / Color / Font / Visibility（初始态需为 Visible）

### 6.4 阶段 4 —— 加可选控件（Section 1 的 `prereq_label_0..5` 等）

当必需控件已稳定后再补 [§3.2](#32-可选控件8-个) 的 8 个可选控件。命名必须对上 `_OPTIONAL_CONTROLS`。

### 6.5 热重载

改 Python 后无需重启 Editor：

```python
import importlib
import post_render_tool.widget_builder as wb
import post_render_tool.widget as w
importlib.reload(wb); importlib.reload(w)
wb.rebuild_widget()
```

改 C++ UPROPERTY **必须**完全重启 Editor + 重建 plugin（Live Coding 不支持 UPROPERTY 变更）。

---

## 7. 折叠头 vs `btn_recheck`：常见混淆

Section 1 里 `btn_recheck` 和"折叠头"是**两个不同元素**，别混为一谈：

| 元素 | 契约内？ | 类型 | 作用 | 点击行为 |
|---|---|---|---|---|
| `btn_recheck` | ✅ 契约内 | `UButton` | Section 1 **内容区**里的"Recheck"按钮 | 触发 `_on_recheck_prereqs()`，重扫插件状态 |
| 折叠头 | ❌ 装饰件 | 见下方三方案 | `▶ Prerequisites  5/6 OK` 这一整行标题 | 展开 / 收起 Section 内容 |

**三种实现路径**：

| 方案 | 控件 | 契约 | 特点 | 是否匹配 Figma |
|---|---|---|---|---|
| **1. `UExpandableArea`** | 原生折叠控件 | 装饰 | 零 BP 连线；但展开箭头样式受控件限制 | ❌ Figma 用自定义 `▶`/`▼` |
| **2. `UButton` + `Visibility` 切换**（推荐） | 装饰 Button 或 `HorizontalBox` + `OnClicked` | 装饰 | BP 的 `OnClicked` 事件里把 Section 内容容器 `Visibility` 在 `Visible ↔ Collapsed` 间切换；完全不碰 C++ 契约 | ✅ 匹配 Figma State A / B |
| **3. 纳入 Python 契约** | 新增 `expander_prereqs` UPROPERTY `UExpandableArea` | ✅ 必需 / 可选 | 走完整流程：改 `PostRenderToolWidget.h` → 关 Editor → 重建插件 → 重开项目 → BP 里拖同名 `UExpandableArea` → `widget.py` 加一项；Python 可通过 `set_is_expanded(False)` 控制 | 仅在需要"前置全绿自动收起"之类业务逻辑时选 |

**判定标准**：纯视觉折叠 → 方案 2；需要 Python 按业务状态控制 → 方案 3。

---

## 8. 新增 / 移除绑定

### 8.1 新增

1. 在 `Source/PostRenderTool/Public/PostRenderToolWidget.h` 加 UPROPERTY：
   ```cpp
   UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
   UButton* btn_new_feature;
   ```
2. 完全关闭 UE Editor
3. 重新编译插件（UBT，通过 IDE 或 `xcodebuild`）—— **Live Coding 不支持 UPROPERTY 变更**
4. 重新打开宿主项目，打开 `BP_PostRenderToolWidget`
5. 将匹配类型的 widget 拖入层级结构，命名为 `btn_new_feature`
6. 编译蓝图（Ctrl+B）必须成功 → 保存（Ctrl+S）
7. 更新 `Content/Python/post_render_tool/widget.py`：
   - 把 `"btn_new_feature"` 加入 `_REQUIRED_CONTROLS`（或 `_OPTIONAL_CONTROLS`）
   - 在 `_bind_events` 中添加：`self._bind_click("btn_new_feature", self._on_new_feature)`
   - 实现 `_on_new_feature(self)` 承载业务逻辑
8. 热重载：`importlib.reload(widget); widget_builder.rebuild_widget()`
9. 更新本文档 —— 在 [§3](#3-契约清单) / [§5](#5-designer-填写手册按-section-顺序) 对应表里添加一行
10. 所有改动作为**一个逻辑单元**提交：C++ 头文件 + `.uasset` + `widget.py` + 本文档

### 8.2 移除

**必须先从 C++ 侧移除 UPROPERTY，再处理 BP 侧。** 顺序反了会立即打坏 BP compile：C++ 的 `meta=(BindWidget)` 是"必须存在于子 BP"的单向契约 —— 只要 C++ 还声明，BP 就必须有同名同类型 widget。

1. 从 `PostRenderToolWidget.h` **删除 UPROPERTY 声明**
2. 完全关闭 UE Editor
3. 重新编译插件（UBT）
4. 重新打开宿主项目，打开 `BP_PostRenderToolWidget`
5. BP 里对应 widget 已自动变成普通控件 —— 在 Hierarchy 里删除
6. 编译蓝图 → 保存
7. 更新 `widget.py`：从 `_REQUIRED_CONTROLS` / `_OPTIONAL_CONTROLS` 移除该名称，删 `_bind_events` 绑定 + 回调方法
8. 更新本文档 —— 在对应表里删除该行
9. 一起提交

**不要反过来做**（先删 BP widget 再删 UPROPERTY）—— BP compile 会在步骤之间失败，把工作流卡住。

---

## 9. 故障排除

### 9.1 类型不匹配

C++ 声明为：
```cpp
UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
UButton* btn_import;
```
但蓝图里 `btn_import` 是 `Border` 而不是 `Button`，编译失败：

> `A required widget binding "btn_import" of type UButton was not found.`

**修复方向永远在 Blueprint 侧**：把 widget 的类型改成与 C++ 声明匹配。**C++ 契约是真相来源（source of truth）。**

### 9.2 名称漂移（Python 侧）

widget 打开时 Output Log 出现：

```
[widget] 'prereq_label_N' UPROPERTY is None — widget missing in BP.
```

根因：

- BP 里控件名与 C++ 契约不一致（typo / 未重命名）
- BP 里控件没勾 **Is Variable**（UMG 不生成 UPROPERTY backing field）
- `widget.py` 的 `_REQUIRED_CONTROLS` / `_OPTIONAL_CONTROLS` 与 C++ / BP 漂移

**可视信号**：Section 1 的某条 `prereq_label` 保持空白（而不是 `OK: ...` 或 `MISSING: ...`）就说明这条 binding 断了。若占位曾被填成 `"OK: XXX"` 之类字样，故障会被伪装成绿灯 —— 这就是 [§5.1](#51-填写总则) 要求空串占位的原因。

### 9.3 Python 改动不生效

- 改 `widget.py` → 热重载（见 [§6.5](#65-热重载)），**无需重启 Editor**
- 改 `PostRenderToolWidget.h`（UPROPERTY）→ **必须**完全重启 Editor + 重建 plugin（Live Coding 不支持）
- 改 `.uasset`（BP 布局）→ Compile + Save 即可

---

## 11. 与自动化的关系

本文档（human-readable 契约 + 填写手册）和机器可读的 `docs/widget-tree-spec.json` 是两份**并行**资料，互为校验：

| 用途 | 本文档 | widget-tree-spec.json |
|---|---|---|
| 人读 / 教学 | ✅ 主 | ❌ |
| 机器处理 / 脚本消费 | ❌ | ✅ 主 |
| 契约名列表 | §3.1 / §3.2 表格 | 根据 `role` 字段遍历 |
| 装饰件建议命名 | §4.2 `lbl_` 前缀 | 与本文档一致 |
| 填写默认值 | §5.4–5.9 表格 | 各节点 `properties` 字段 |
| 层级关系 | §5.4–5.9 ASCII 树 | 嵌套 `children` 数组 |

**三方 drift 由测试把关**：`Content/Python/post_render_tool/tests/test_spec_drift.py` 对比 `PostRenderToolWidget.h` UPROPERTY 名、`widget.py` tuples、`widget-tree-spec.json` contract 名 —— 任何一处漂移都会让测试红。本文档作为人读文档不在自动 drift 校验范围，但**改动三方中任一**时**请也更新本文档 §3 / §5 对应条目**。

**如何用 JSON 自动生成 BP**：见 `docs/deployment-guide.md` §1.3 推荐路径，或直接在 UE Python 控制台运行：

```python
from post_render_tool import build_widget_blueprint
build_widget_blueprint.run_build()
```

脚本 idempotent —— rerun 不会回滚用户在 Designer 里的视觉美化，只会补上 spec 里新增的 widget。
