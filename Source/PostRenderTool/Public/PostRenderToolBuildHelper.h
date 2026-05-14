// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "Misc/Timecode.h"
#include "PostRenderToolBuildHelper.generated.h"

class UWidgetBlueprint;
class UWidget;
class UPanelWidget;
class UPanelSlot;
class UPostRenderCameraSamples;
class UPostRenderCameraSection;
class UMovieSceneSequence;
struct FPostRenderCameraSample;

UENUM(BlueprintType)
enum class EEnsureWidgetResult : uint8
{
    // Widget was created and added to the parent.
    Created,
    // Widget with that name already existed; left untouched.
    AlreadyExisted,
    // A widget with that name existed but its class mismatched — aborted.
    TypeMismatch,
    // Input was invalid (null blueprint, empty name, bad parent, etc.).
    InvalidInput,
    // Parent is not a panel / content widget — cannot add children.
    ParentCannotHoldChildren,
};

/**
 * Python bridge for scripted population of a UWidgetBlueprint's widget tree.
 *
 * UE 5.7 does NOT expose UWidgetBlueprint::WidgetTree to Python (BaseWidgetBlueprint.h:16-17
 * uses bare UPROPERTY() without BlueprintVisible — invisible to reflection per PyGenUtil.cpp
 * IsScriptExposedProperty rules). This helper wraps the minimum set of tree-mutation ops in
 * BlueprintCallable UFUNCTIONs so Python can drive them via unreal.PostRenderToolBuildHelper.*.
 *
 * Note on UWidget::bIsVariable: private bitfield (Widget.h:318), no public setter. Widget.cpp:195
 * constructor initializes to true by default, which matches what contract widgets need; the
 * side-effect that decorative widgets also get Variable is accepted as harmless.
 *
 * Usage from Python:
 *   root = unreal.PostRenderToolBuildHelper.ensure_root_panel(wbp, "RootPanel", unreal.VerticalBox)
 *   result, widget, slot = unreal.PostRenderToolBuildHelper.ensure_widget_under_parent(
 *       wbp, "btn_browse", unreal.Button, root)
 *   # slot is non-null when widget was newly created; apply slot properties via reflection.
 */
UCLASS()
class POSTRENDERTOOL_API UPostRenderToolBuildHelper : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /**
     * If the blueprint's WidgetTree is empty, create a root panel of the given
     * class and name. If a root already exists, leave it alone (no clobber).
     * Returns the root panel (either freshly created or pre-existing).
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static UPanelWidget* EnsureRootPanel(UWidgetBlueprint* Blueprint,
                                         FName RootName,
                                         TSubclassOf<UPanelWidget> RootClass);

    /**
     * Recursive search by FName across the whole WidgetTree (PanelWidget
     * children + ContentWidget content). Returns nullptr if not found.
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static UWidget* FindWidgetByName(UWidgetBlueprint* Blueprint,
                                     FName TargetName);

    /**
     * Ensure a widget with the given Name + Class exists as a child of the
     * provided ParentWidget. Returns the final widget (new or existing) via
     * OutWidget, its parent slot via OutSlot (nullptr when the widget pre-
     * existed — idempotency: caller must not re-apply slot properties), and
     * a status enum as the return value.
     *
     * - If a widget with that name already exists anywhere in the tree:
     *   - Same class → return AlreadyExisted, OutWidget = existing one, OutSlot = nullptr.
     *     (Caller must NOT re-apply properties — idempotency contract preserves user tweaks.)
     *   - Different class → return TypeMismatch, OutWidget/OutSlot = nullptr.
     * - If not found → construct under ParentWidget, mark blueprint structurally modified,
     *   return Created with OutWidget + OutSlot (from AddChild or SetContent).
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static EEnsureWidgetResult EnsureWidgetUnderParent(UWidgetBlueprint* Blueprint,
                                                      FName WidgetName,
                                                      TSubclassOf<UWidget> WidgetClass,
                                                      UWidget* ParentWidget,
                                                      UWidget*& OutWidget,
                                                      UPanelSlot*& OutSlot);

    /**
     * Variant of EnsureWidgetUnderParent for parents that implement INamedSlotInterface
     * (UExpandableArea, UNamedSlot, …). Those do NOT expose their slot widgets via
     * UPanelWidget::AddChild or UContentWidget::SetContent — the only way to fill them
     * in C++ is INamedSlotInterface::SetContentForSlot(FName, UWidget*), which is a
     * plain virtual (not UFUNCTION) and therefore unreachable from Python.
     *
     * Slot-name convention (from each widget's GetSlotNames):
     *   - UExpandableArea → "Header", "Body"
     *   - UNamedSlot      → the single name authored in Designer
     *
     * Returns the same enum set as EnsureWidgetUnderParent. Idempotency: FindWidgetByName
     * now descends into named slots too, so a widget already placed in some named slot
     * is correctly detected as AlreadyExisted. If the widget exists elsewhere in the
     * tree (migration scenario), it is re-parented into the requested slot.
     *
     * No UPanelSlot is returned — named-slot content widgets don't have one; their
     * layout is governed by the parent's Header/AreaPadding, not a per-child slot.
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static EEnsureWidgetResult EnsureWidgetInNamedSlot(UWidgetBlueprint* Blueprint,
                                                      FName WidgetName,
                                                      TSubclassOf<UWidget> WidgetClass,
                                                      UWidget* NamedSlotParent,
                                                      FName SlotName,
                                                      UWidget*& OutWidget);

    // ====================================================================
    // Custom MovieScene Track bridges
    // ====================================================================

    /**
     * One-shot write of all dense per-frame measurements into a
     * UPostRenderCameraSamples DataAsset. Replaces 130 万 Python add_key
     * calls with a single C++-side TArray assignment.
     *
     * Validates: FrameNumbers.Num() == Samples.Num() (raises log error +
     * returns false otherwise). Calls SampleAsset->Modify() once and
     * RecomputeContiguity() before saving.
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static bool WriteCameraSamples(
        UPostRenderCameraSamples* SampleAsset,
        const TArray<int32>& FrameNumbers,
        const TArray<FPostRenderCameraSample>& Samples,
        int32 FrameRateNumerator,
        int32 FrameRateDenominator,
        const FString& SourceCsvPath,
        // P0 timecode-sync: canonical start timecode persisted on the asset.
        // bHasStartTimecode=false → impl resets StartTimecode to zeroed
        // FTimecode (used when csv_parser was called without `fps`).
        const FTimecode& StartTimecode,
        bool bHasStartTimecode);

    /**
     * Find-or-create a UPostRenderCameraTrack on the given binding, with one
     * UPostRenderCameraSection covering [0, FrameCount) (display rate).
     * Returns the section so caller can attach the SampleAsset.
     *
     * Idempotent: if a track of this type already exists on the binding,
     * removes its sections and reuses the track (matches the existing
     * "clear bindings + recreate" pattern in sequence_builder.py).
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static UPostRenderCameraSection* EnsurePostRenderCameraTrackOnBinding(
        UMovieSceneSequence* Sequence,
        const FGuid& BindingGuid,
        int32 SectionStartFrame,
        int32 SectionEndFrame);

    /**
     * Find-or-create a UPostRenderCameraSamples DataAsset at the given
     * package path. Bypasses the Python-side missing-factory problem
     * (UDataAsset has no default UFactory exposed to AssetTools).
     *
     * If asset exists at PackagePath/AssetName, loads and returns it.
     * Otherwise creates a new UPostRenderCameraSamples package, names it,
     * MarkPackageDirty + saves. Caller is responsible for subsequent
     * WriteCameraSamples + EditorAssetLibrary.save_asset.
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool|Build")
    static UPostRenderCameraSamples* CreateOrLoadCameraSamplesAsset(
        const FString& PackagePath,
        const FString& AssetName);
};
