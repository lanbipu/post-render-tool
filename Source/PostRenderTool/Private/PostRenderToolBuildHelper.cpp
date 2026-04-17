// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolBuildHelper.h"

#include "WidgetBlueprint.h"
#include "Blueprint/WidgetTree.h"
#include "Components/Widget.h"
#include "Components/PanelWidget.h"
#include "Components/ContentWidget.h"
#include "Kismet2/BlueprintEditorUtils.h"

namespace
{
    UWidget* FindWidgetByNameRecursive(UWidget* Root, FName TargetName)
    {
        if (!Root)
        {
            return nullptr;
        }
        if (Root->GetFName() == TargetName)
        {
            return Root;
        }
        if (UPanelWidget* Panel = Cast<UPanelWidget>(Root))
        {
            for (int32 Index = 0; Index < Panel->GetChildrenCount(); ++Index)
            {
                if (UWidget* Found = FindWidgetByNameRecursive(Panel->GetChildAt(Index), TargetName))
                {
                    return Found;
                }
            }
        }
        else if (UContentWidget* ContentW = Cast<UContentWidget>(Root))
        {
            return FindWidgetByNameRecursive(ContentW->GetContent(), TargetName);
        }
        return nullptr;
    }
}

UPanelWidget* UPostRenderToolBuildHelper::EnsureRootPanel(UWidgetBlueprint* Blueprint,
                                                          FName RootName,
                                                          TSubclassOf<UPanelWidget> RootClass)
{
    if (!Blueprint || !RootClass || RootName.IsNone())
    {
        return nullptr;
    }

    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return nullptr;
    }

    if (UPanelWidget* Existing = Cast<UPanelWidget>(Tree->RootWidget))
    {
        return Existing;
    }

    if (Tree->RootWidget != nullptr)
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderToolBuildHelper] Root widget '%s' is %s (not a PanelWidget). "
                 "Refusing to overwrite — wrap or replace manually in Designer."),
            *Tree->RootWidget->GetName(),
            *Tree->RootWidget->GetClass()->GetName());
        return nullptr;
    }

    UPanelWidget* NewRoot = Cast<UPanelWidget>(Tree->ConstructWidget<UWidget>(RootClass, RootName));
    if (!NewRoot)
    {
        return nullptr;
    }
    Tree->RootWidget = NewRoot;
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    return NewRoot;
}

UWidget* UPostRenderToolBuildHelper::FindWidgetByName(UWidgetBlueprint* Blueprint,
                                                      FName TargetName)
{
    if (!Blueprint || TargetName.IsNone())
    {
        return nullptr;
    }
    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return nullptr;
    }
    return FindWidgetByNameRecursive(Tree->RootWidget, TargetName);
}

EEnsureWidgetResult UPostRenderToolBuildHelper::EnsureWidgetUnderParent(
    UWidgetBlueprint* Blueprint,
    FName WidgetName,
    TSubclassOf<UWidget> WidgetClass,
    UWidget* ParentWidget,
    UWidget*& OutWidget,
    UPanelSlot*& OutSlot)
{
    OutWidget = nullptr;
    OutSlot = nullptr;
    if (!Blueprint || !WidgetClass || WidgetName.IsNone() || !ParentWidget)
    {
        return EEnsureWidgetResult::InvalidInput;
    }
    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return EEnsureWidgetResult::InvalidInput;
    }

    // Already-exists check across the whole tree (idempotency contract).
    if (UWidget* Existing = FindWidgetByNameRecursive(Tree->RootWidget, WidgetName))
    {
        if (Existing->IsA(WidgetClass))
        {
            OutWidget = Existing;
            // OutSlot stays null: the caller MUST NOT re-apply slot props, by contract.
            return EEnsureWidgetResult::AlreadyExisted;
        }
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderToolBuildHelper] Widget '%s' exists as %s, spec wants %s — type mismatch."),
            *WidgetName.ToString(),
            *Existing->GetClass()->GetName(),
            *WidgetClass->GetName());
        return EEnsureWidgetResult::TypeMismatch;
    }

    UWidget* NewWidget = Tree->ConstructWidget<UWidget>(WidgetClass, WidgetName);
    if (!NewWidget)
    {
        return EEnsureWidgetResult::InvalidInput;
    }

    // AddChild / SetContent both return UPanelSlot* (verified PanelWidget.h:58-59,
    // ContentWidget.h:18-27) — hand it back to Python so it can set slot props
    // without a second UFUNCTION round-trip.
    if (UPanelWidget* ParentPanel = Cast<UPanelWidget>(ParentWidget))
    {
        OutSlot = ParentPanel->AddChild(NewWidget);
    }
    else if (UContentWidget* ParentContent = Cast<UContentWidget>(ParentWidget))
    {
        OutSlot = ParentContent->SetContent(NewWidget);
    }
    else
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderToolBuildHelper] Parent '%s' (%s) cannot hold children."),
            *ParentWidget->GetName(),
            *ParentWidget->GetClass()->GetName());
        return EEnsureWidgetResult::ParentCannotHoldChildren;
    }

    // Structural change → must use MarkBlueprintAsStructurallyModified, not Modify():
    // widget tree topology changes invalidate the generated class layout, so the BP
    // needs to be flagged for full recompile on next CompileBlueprint call.
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    OutWidget = NewWidget;

    // Note on bIsVariable: UWidget::bIsVariable (Widget.h:318) is a private bitfield,
    // no public setter. Widget.cpp:195 constructor initializes to TRUE by default, so
    // every widget we just constructed is automatically a Variable — exactly what
    // BindWidget / BindWidgetOptional contract widgets need for reflection. Decorative
    // widgets inherit the same default (minor overhead on generated class, harmless).
    return EEnsureWidgetResult::Created;
}
