// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolCommands.h"

#include "Styling/AppStyle.h"

#define LOCTEXT_NAMESPACE "FPostRenderToolModule"

FPostRenderToolCommands::FPostRenderToolCommands()
    : TCommands<FPostRenderToolCommands>(
        TEXT("PostRenderTool"),
        LOCTEXT("PostRenderToolContext", "VP Post-Render Tool"),
        NAME_None,
        FAppStyle::GetAppStyleSetName())
{
}

void FPostRenderToolCommands::RegisterCommands()
{
    UI_COMMAND(OpenToolWidget,
        "VPTool",
        "Open the VP Post-Render Tool (Disguise CSV Dense → UE import).",
        EUserInterfaceActionType::Button,
        FInputChord());
}

#undef LOCTEXT_NAMESPACE
