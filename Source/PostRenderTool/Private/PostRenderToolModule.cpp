// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolModule.h"

#define LOCTEXT_NAMESPACE "FPostRenderToolModule"

void FPostRenderToolModule::StartupModule()
{
    UE_LOG(LogTemp, Log, TEXT("[PostRenderTool] Plugin module started."));
}

void FPostRenderToolModule::ShutdownModule()
{
    UE_LOG(LogTemp, Log, TEXT("[PostRenderTool] Plugin module shut down."));
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FPostRenderToolModule, PostRenderTool)
