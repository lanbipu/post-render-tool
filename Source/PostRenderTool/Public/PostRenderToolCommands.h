// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Framework/Commands/Commands.h"

class FPostRenderToolCommands : public TCommands<FPostRenderToolCommands>
{
public:
    FPostRenderToolCommands();

    virtual void RegisterCommands() override;

    TSharedPtr<FUICommandInfo> OpenToolWidget;
};
