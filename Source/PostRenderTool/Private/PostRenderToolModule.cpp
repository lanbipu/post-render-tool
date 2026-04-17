// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolModule.h"

#include "IPythonScriptPlugin.h"
#include "ToolMenus.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "Styling/AppStyle.h"

#define LOCTEXT_NAMESPACE "FPostRenderToolModule"

static const TCHAR* GOpenWidgetPython =
    TEXT("from post_render_tool.widget_builder import open_widget; open_widget()");

void FPostRenderToolModule::StartupModule()
{
    UE_LOG(LogTemp, Log, TEXT("[PostRenderTool] Plugin module started."));

    const bool bUIEnabled = UToolMenus::IsToolMenuUIEnabled();
    UToolMenus* ToolMenusPtr = UToolMenus::TryGet();
    UE_LOG(LogTemp, Log,
        TEXT("[PostRenderTool] UToolMenus state: IsToolMenuUIEnabled=%s, TryGet=%s"),
        bUIEnabled ? TEXT("true") : TEXT("false"),
        ToolMenusPtr ? TEXT("non-null") : TEXT("null"));

    if (bUIEnabled && ToolMenusPtr)
    {
        UE_LOG(LogTemp, Log, TEXT("[PostRenderTool] Calling RegisterMenus() synchronously."));
        RegisterMenus();
    }
    else
    {
        UE_LOG(LogTemp, Log, TEXT("[PostRenderTool] Deferring RegisterMenus() via RegisterStartupCallback."));
        ToolMenusStartupHandle = UToolMenus::RegisterStartupCallback(
            FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FPostRenderToolModule::RegisterMenus));
    }
}

void FPostRenderToolModule::ShutdownModule()
{
    UToolMenus::UnRegisterStartupCallback(ToolMenusStartupHandle);
    UToolMenus::UnregisterOwner(this);

    UE_LOG(LogTemp, Log, TEXT("[PostRenderTool] Plugin module shut down."));
}

void FPostRenderToolModule::RegisterMenus()
{
    FToolMenuOwnerScoped OwnerScoped(this);

    static const FName MenuName(TEXT("LevelEditor.LevelEditorToolBar.PlayToolBar"));

    UToolMenu* ToolbarMenu = UToolMenus::Get()->ExtendMenu(MenuName);
    if (!ToolbarMenu)
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderTool] Failed to extend %s — toolbar button will not appear."),
            *MenuName.ToString());
        return;
    }

    FToolMenuSection& Section = ToolbarMenu->FindOrAddSection(
        TEXT("VPPostRenderTool"),
        LOCTEXT("VPSectionLabel", "VP Post-Render Tool"));

    FToolMenuEntry Entry = FToolMenuEntry::InitToolBarButton(
        TEXT("VPPostRenderToolButton"),
        FUIAction(FExecuteAction::CreateRaw(this, &FPostRenderToolModule::OpenToolWidget)),
        LOCTEXT("VPToolButtonLabel", "VPTool"),
        LOCTEXT("VPToolButtonTooltip",
            "Open the VP Post-Render Tool (Disguise CSV Dense → UE import)."),
        FSlateIcon(FAppStyle::GetAppStyleSetName(), TEXT("LevelEditor.OpenCinematic")));

    Section.AddEntry(Entry);

    // Force a rebuild of any already-displayed toolbar widgets, otherwise the
    // new entry is stored but invisible because Slate snapshots the widget
    // tree when it first builds the toolbar.
    UToolMenus::Get()->RefreshAllWidgets();

    UE_LOG(LogTemp, Log,
        TEXT("[PostRenderTool] Toolbar button registered at %s / section 'VPPostRenderTool' (widgets refreshed)."),
        *MenuName.ToString());
}

void FPostRenderToolModule::OpenToolWidget()
{
    IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
    if (Python && Python->IsPythonAvailable())
    {
        Python->ExecPythonCommand(GOpenWidgetPython);
    }
    else
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderTool] Python plugin unavailable — toolbar button cannot open widget."));
    }
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FPostRenderToolModule, PostRenderTool)
