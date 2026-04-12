// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolWidget.h"

#include "Components/Button.h"
#include "Components/ComboBoxString.h"
#include "Components/MultiLineEditableText.h"
#include "Components/SpinBox.h"
#include "Components/TextBlock.h"

void UPostRenderToolWidget::NativeConstruct()
{
    Super::NativeConstruct();

    // All widget pointers are bound by the UMG compiler via meta=(BindWidget).
    // Python side (widget.py) is responsible for wiring business logic
    // callbacks; this C++ class intentionally stays thin.

    UE_LOG(LogTemp, Log, TEXT("[PostRenderTool] NativeConstruct: widget bindings resolved."));
}
