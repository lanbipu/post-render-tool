// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolWidget.h"

#include "Components/Button.h"
#include "Components/ComboBoxString.h"
#include "Components/MultiLineEditableText.h"
#include "Components/ScrollBox.h"
#include "Components/SpinBox.h"
#include "Components/TextBlock.h"
#include "Runtime/Launch/Resources/Version.h"

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
#if ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 2
            const float Step = lbl_root_scroll->GetWheelScrollMultiplier() * 96.0f;
#else
            // UE 5.1 无 GetWheelScrollMultiplier getter, 直接读 public 成员
            const float Step = lbl_root_scroll->WheelScrollMultiplier * 96.0f;
#endif
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
