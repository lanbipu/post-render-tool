// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "PostRenderToolBuildHelper.generated.h"

class UWidgetBlueprint;
class UWidget;

/**
 * Python bridge for one-shot BP_PostRenderToolWidget population.
 *
 * UE 5.7 does NOT expose ``UWidgetBlueprint::WidgetTree`` to Python (no
 * ``BlueprintReadOnly`` / ``EditAnywhere`` flags → hidden from reflection), so
 * a pure-Python build_widget_blueprint script cannot touch the tree at all.
 * This helper wraps the tree mutation in a ``BlueprintCallable`` UFUNCTION so
 * Python can drive it via ``unreal.PostRenderToolBuildHelper.ensure_bind_widget(...)``.
 */
UCLASS()
class POSTRENDERTOOL_API UPostRenderToolBuildHelper : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /**
     * Ensure the widget blueprint contains a widget with the given name and
     * class. If absent, constructs it under a VerticalBox root named
     * "RootPanel" (creating that root only when the tree is empty).
     *
     * Matching is recursive across the whole widget tree, so widgets the
     * user nested inside Border / SizeBox / sub-VerticalBox during visual
     * polish are correctly detected and not duplicated on rerun.
     *
     * Returns ``true`` if a new widget was added (blueprint marked dirty),
     * ``false`` if the name already existed, the root is non-PanelWidget,
     * or any input is invalid.
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool")
    static bool EnsureBindWidget(UWidgetBlueprint* Blueprint,
                                 FName WidgetName,
                                 TSubclassOf<UWidget> WidgetClass);
};
