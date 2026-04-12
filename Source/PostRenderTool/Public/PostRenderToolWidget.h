// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "EditorUtilityWidget.h"
#include "PostRenderToolWidget.generated.h"

class UButton;
class USpinBox;
class UComboBoxString;
class UTextBlock;
class UMultiLineEditableText;

/**
 * Editor Utility Widget for the VP Post-Render Tool.
 *
 * All widget pointers below are bound at Blueprint compile time via
 * meta=(BindWidget). A child Blueprint (BP_PostRenderToolWidget) must
 * contain widgets with matching names and types, or compilation fails.
 *
 * BlueprintReadOnly is required in addition to BindWidget so that Python
 * can access these pointers via get_editor_property() after the widget
 * is spawned. Without BlueprintReadOnly the UPROPERTY has no
 * CPF_BlueprintVisible flag and Python reflection cannot see it.
 */
UCLASS()
class POSTRENDERTOOL_API UPostRenderToolWidget : public UEditorUtilityWidget
{
    GENERATED_BODY()

public:
    // ======================================================================
    // Section 1: Prerequisites
    // ======================================================================

    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional))
    UTextBlock* prereq_label_0;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional))
    UTextBlock* prereq_label_1;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional))
    UTextBlock* prereq_label_2;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional))
    UTextBlock* prereq_label_3;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional))
    UTextBlock* prereq_label_4;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional))
    UTextBlock* prereq_label_5;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional))
    UTextBlock* prereq_summary;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UButton* btn_recheck;

    // ======================================================================
    // Section 2: CSV File
    // ======================================================================

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UButton* btn_browse;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UTextBlock* txt_file_path;

    // ======================================================================
    // Section 3: CSV Preview
    // ======================================================================

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UTextBlock* txt_frame_count;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UTextBlock* txt_focal_range;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UTextBlock* txt_timecode;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UTextBlock* txt_sensor_width;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    USpinBox* spn_fps;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UTextBlock* txt_detected_fps;

    // ======================================================================
    // Section 4: Coordinate Verification
    // ======================================================================

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    USpinBox* spn_frame;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional))
    UTextBlock* txt_frame_hint;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UTextBlock* txt_designer_pos;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UTextBlock* txt_designer_rot;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UTextBlock* txt_ue_pos;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UTextBlock* txt_ue_rot;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UButton* btn_spawn_cam;

    // ======================================================================
    // Section 5a: Axis Mapping — Position
    // ======================================================================

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UComboBoxString* cmb_pos_x_src;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    USpinBox* spn_pos_x_scale;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UComboBoxString* cmb_pos_y_src;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    USpinBox* spn_pos_y_scale;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UComboBoxString* cmb_pos_z_src;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    USpinBox* spn_pos_z_scale;

    // ======================================================================
    // Section 5b: Axis Mapping — Rotation
    // ======================================================================

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UComboBoxString* cmb_rot_pitch_src;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    USpinBox* spn_rot_pitch_scale;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UComboBoxString* cmb_rot_yaw_src;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    USpinBox* spn_rot_yaw_scale;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UComboBoxString* cmb_rot_roll_src;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    USpinBox* spn_rot_roll_scale;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UButton* btn_apply_mapping;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UButton* btn_save_mapping;

    // ======================================================================
    // Section 6: Actions + Results
    // ======================================================================

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UButton* btn_import;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UButton* btn_open_seq;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UButton* btn_open_mrq;

    UPROPERTY(BlueprintReadOnly, meta=(BindWidget))
    UMultiLineEditableText* txt_results;

protected:
    virtual void NativeConstruct() override;
};
