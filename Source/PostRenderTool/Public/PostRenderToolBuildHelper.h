// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "PostRenderToolBuildHelper.generated.h"

class UWidgetBlueprint;
class UWidget;
class UPanelWidget;
class UPanelSlot;

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
};
