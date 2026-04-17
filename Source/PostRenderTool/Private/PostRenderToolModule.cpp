// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolModule.h"

#include "PostRenderToolCommands.h"
#include "IPythonScriptPlugin.h"
#include "ToolMenus.h"
#include "Framework/Commands/UICommandList.h"

#define LOCTEXT_NAMESPACE "FPostRenderToolModule"

void FPostRenderToolModule::StartupModule()
{
    UE_LOG(LogTemp, Log, TEXT("[PostRenderTool] Plugin module started."));

    FPostRenderToolCommands::Register();

    PluginCommands = MakeShared<FUICommandList>();
    PluginCommands->MapAction(
        FPostRenderToolCommands::Get().OpenToolWidget,
        FExecuteAction::CreateRaw(this, &FPostRenderToolModule::OpenToolWidget),
        FCanExecuteAction());

    // SlimHorizontalToolBar (PlayToolBar's multi-box type) only renders buttons
    // that flow through the command system. Direct FUIAction entries were
    // observed to silently no-op — stick to the FUICommandInfo + FUICommandList
    // pattern used by official UE plugins (InEditorDocumentation, PCG, etc.).
    if (UToolMenus::IsToolMenuUIEnabled() && UToolMenus::TryGet())
    {
        RegisterMenus();
    }
    else
    {
        ToolMenusStartupHandle = UToolMenus::RegisterStartupCallback(
            FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FPostRenderToolModule::RegisterMenus));
    }
}

void FPostRenderToolModule::ShutdownModule()
{
    if (ToolMenusStartupHandle.IsValid())
    {
        UToolMenus::UnRegisterStartupCallback(ToolMenusStartupHandle);
        ToolMenusStartupHandle.Reset();
    }
    UToolMenus::UnregisterOwner(this);

    if (FPostRenderToolCommands::IsRegistered())
    {
        FPostRenderToolCommands::Unregister();
    }
    PluginCommands.Reset();
}

void FPostRenderToolModule::RegisterMenus()
{
    FToolMenuOwnerScoped OwnerScoped(this);

    UToolMenu* ToolbarMenu = UToolMenus::Get()->ExtendMenu(
        TEXT("LevelEditor.LevelEditorToolBar.PlayToolBar"));
    if (!ToolbarMenu)
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderTool] Failed to extend LevelEditor.LevelEditorToolBar.PlayToolBar."));
        return;
    }

    FToolMenuSection& Section = ToolbarMenu->FindOrAddSection(TEXT("PluginTools"));
    FToolMenuEntry& Entry = Section.AddEntry(
        FToolMenuEntry::InitToolBarButton(FPostRenderToolCommands::Get().OpenToolWidget));
    Entry.SetCommandList(PluginCommands);

    UE_LOG(LogTemp, Log,
        TEXT("[PostRenderTool] Toolbar button registered via FUICommandInfo at PlayToolBar / section 'PluginTools'."));
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
