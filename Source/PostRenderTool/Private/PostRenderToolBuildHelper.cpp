// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolBuildHelper.h"

#include "WidgetBlueprint.h"
#include "Blueprint/WidgetTree.h"
#include "Components/Widget.h"
#include "Components/PanelWidget.h"
#include "Components/VerticalBox.h"
#include "Components/ContentWidget.h"

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

EPostRenderToolEnsureResult UPostRenderToolBuildHelper::EnsureBindWidget(UWidgetBlueprint* Blueprint,
                                                                         FName WidgetName,
                                                                         TSubclassOf<UWidget> WidgetClass)
{
    if (!Blueprint || !WidgetClass || WidgetName.IsNone())
    {
        return EPostRenderToolEnsureResult::InvalidInput;
    }

    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return EPostRenderToolEnsureResult::InvalidInput;
    }

    if (FindWidgetByNameRecursive(Tree->RootWidget, WidgetName))
    {
        return EPostRenderToolEnsureResult::AlreadyExists;
    }

    UPanelWidget* RootPanel = Cast<UPanelWidget>(Tree->RootWidget);
    if (!RootPanel)
    {
        if (Tree->RootWidget != nullptr)
        {
            UE_LOG(LogTemp, Warning,
                TEXT("[PostRenderToolBuildHelper] Root widget '%s' is %s (not a PanelWidget). "
                     "Wrap it in a VerticalBox/HorizontalBox/Overlay before re-running."),
                *Tree->RootWidget->GetName(),
                *Tree->RootWidget->GetClass()->GetName());
            return EPostRenderToolEnsureResult::InvalidRoot;
        }
        UVerticalBox* NewRoot = Tree->ConstructWidget<UVerticalBox>(
            UVerticalBox::StaticClass(), TEXT("RootPanel"));
        Tree->RootWidget = NewRoot;
        RootPanel = NewRoot;
    }

    UWidget* NewWidget = Tree->ConstructWidget<UWidget>(WidgetClass, WidgetName);
    if (!NewWidget)
    {
        return EPostRenderToolEnsureResult::ConstructFailed;
    }

    RootPanel->AddChild(NewWidget);
    Blueprint->Modify();
    return EPostRenderToolEnsureResult::Added;
}
