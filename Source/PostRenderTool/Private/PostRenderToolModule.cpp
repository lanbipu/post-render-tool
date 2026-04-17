// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolModule.h"

#include "IPythonScriptPlugin.h"
#include "ToolMenus.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "Styling/AppStyle.h"

#define LOCTEXT_NAMESPACE "FPostRenderToolModule"

void FPostRenderToolModule::StartupModule()
{
    UE_LOG(LogTemp, Log, TEXT("[PostRenderTool] Plugin module started."));

    ToolMenusStartupHandle = UToolMenus::RegisterStartupCallback(
        FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FPostRenderToolModule::RegisterMenus));
}

void FPostRenderToolModule::ShutdownModule()
{
    if (ToolMenusStartupHandle.IsValid())
    {
        UToolMenus::UnRegisterStartupCallback(ToolMenusStartupHandle);
        ToolMenusStartupHandle.Reset();
    }
    UToolMenus::UnregisterOwner(this);
}

void FPostRenderToolModule::RegisterMenus()
{
    FToolMenuOwnerScoped OwnerScoped(this);

    const FName MenuName(TEXT("LevelEditor.LevelEditorToolBar.PlayToolBar"));

    UToolMenus* ToolMenus = UToolMenus::Get();
    UToolMenu* ToolbarMenu = ToolMenus->ExtendMenu(MenuName);
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

    Section.AddEntry(FToolMenuEntry::InitToolBarButton(
        TEXT("VPPostRenderToolButton"),
        FUIAction(FExecuteAction::CreateRaw(this, &FPostRenderToolModule::OpenToolWidget)),
        LOCTEXT("VPToolButtonLabel", "VPTool"),
        LOCTEXT("VPToolButtonTooltip",
            "Open the VP Post-Render Tool (Disguise CSV Dense → UE import)."),
        FSlateIcon(FAppStyle::GetAppStyleSetName(), TEXT("LevelEditor.OpenCinematic"))));

    // If the Level Editor toolbar was already built before this plugin loaded
    // (LoadingPhase=Default runs after editor UI init), the new entry sits in
    // the data layer but the live Slate snapshot ignores it. Force a targeted
    // rebuild of just this menu's widget; no-op if it hasn't been generated.
    ToolMenus->RefreshMenuWidget(MenuName);
}

void FPostRenderToolModule::OpenToolWidget()
{
    IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
    if (Python && Python->IsPythonAvailable())
    {
        Python->ExecPythonCommand(
            TEXT("from post_render_tool.widget_builder import open_widget; open_widget()"));
    }
    else
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderTool] Python plugin unavailable — toolbar button cannot open widget."));
    }
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FPostRenderToolModule, PostRenderTool)
