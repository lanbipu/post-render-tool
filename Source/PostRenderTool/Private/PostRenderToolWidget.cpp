// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolWidget.h"

#include "Components/Button.h"
#include "Components/ComboBoxString.h"
#include "Components/MultiLineEditableText.h"
#include "Components/ScrollBox.h"
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

FReply UPostRenderToolWidget::NativeOnMouseWheel(
    const FGeometry& InGeometry,
    const FPointerEvent& InMouseEvent
)
{
    (void)InGeometry;

    if (lbl_root_scroll != nullptr)
    {
        const float WheelDelta = InMouseEvent.GetWheelDelta();
        if (!FMath::IsNearlyZero(WheelDelta))
        {
            const float CurrentOffset = lbl_root_scroll->GetScrollOffset();
            const float Step = lbl_root_scroll->GetWheelScrollMultiplier() * 96.0f;
            const float NextOffset = FMath::Clamp(
                CurrentOffset - (WheelDelta * Step),
                0.0f,
                lbl_root_scroll->GetScrollOffsetOfEnd()
            );
            lbl_root_scroll->SetScrollOffset(NextOffset);
            return FReply::Handled();
        }
    }

    return Super::NativeOnMouseWheel(InGeometry, InMouseEvent);
}
