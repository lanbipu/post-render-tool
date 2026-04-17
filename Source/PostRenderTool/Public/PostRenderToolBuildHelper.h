// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "PostRenderToolBuildHelper.generated.h"

class UWidgetBlueprint;
class UWidget;

UENUM(BlueprintType)
enum class EPostRenderToolEnsureResult : uint8
{
    /** A new widget was constructed and appended to the root panel. */
    Added,
    /** A widget with this name already existed anywhere in the tree. */
    AlreadyExists,
    /** One of the inputs (blueprint / name / class / tree) was invalid. */
    InvalidInput,
    /** The blueprint's root widget exists and is not a PanelWidget — refused to overwrite. */
    InvalidRoot,
    /** ConstructWidget failed (engine-level error). */
    ConstructFailed,
};

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
     * Matching is recursive across the whole widget tree (PanelWidget children
     * + ContentWidget content), so widgets the user nested inside Border /
     * SizeBox / sub-VerticalBox during visual polish are detected and not
     * duplicated on rerun.
     *
     * Returns a discriminated result: Added marks a blueprint mutation,
     * AlreadyExists is the normal idempotent no-op on rerun, and the remaining
     * values are hard failures that callers should propagate instead of
     * treating like "already exists".
     */
    UFUNCTION(BlueprintCallable, Category = "VP Post-Render Tool")
    static EPostRenderToolEnsureResult EnsureBindWidget(UWidgetBlueprint* Blueprint,
                                                        FName WidgetName,
                                                        TSubclassOf<UWidget> WidgetClass);
};
