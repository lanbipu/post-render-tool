// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderCameraSamples.h"

#include "Algo/BinarySearch.h"

void UPostRenderCameraSamples::RecomputeContiguity()
{
    if (SourceFrameNumbers.Num() < 2)
    {
        bIsContiguous = true;
        return;
    }
    int32 Expected = SourceFrameNumbers[0] + 1;
    for (int32 i = 1; i < SourceFrameNumbers.Num(); ++i)
    {
        if (SourceFrameNumbers[i] != Expected)
        {
            bIsContiguous = false;
            return;
        }
        ++Expected;
    }
    bIsContiguous = true;
}

void UPostRenderCameraSamples::FindBoundingIndices(
    FFrameNumber DisplayFrameNumber,
    float SubFrame,
    int32& OutLowerIdx,
    int32& OutUpperIdx,
    float& OutAlpha) const
{
    const int32 Count = SourceFrameNumbers.Num();
    if (Count == 0)
    {
        OutLowerIdx = INDEX_NONE;
        OutUpperIdx = INDEX_NONE;
        OutAlpha = 0.f;
        return;
    }

    const int32 RequestedFrame = DisplayFrameNumber.Value;
    const int32 FirstFrame = SourceFrameNumbers[0];
    const int32 LastFrame = SourceFrameNumbers.Last();

    // ----- Clamp to range — hold ends if scrub goes outside the section -----
    if (RequestedFrame <= FirstFrame)
    {
        OutLowerIdx = 0;
        OutUpperIdx = 0;
        OutAlpha = 0.f;
        return;
    }
    if (RequestedFrame >= LastFrame)
    {
        OutLowerIdx = Count - 1;
        OutUpperIdx = Count - 1;
        OutAlpha = 0.f;
        return;
    }

    int32 LowerIdx;
    if (bIsContiguous)
    {
        // O(1) direct index — frame K stored at index (K - FirstFrame).
        LowerIdx = RequestedFrame - FirstFrame;
    }
    else
    {
        // O(log N) — find the largest index whose frame number <= RequestedFrame.
        // Algo::UpperBound returns first index with value > target, so subtract 1.
        const int32 UB = Algo::UpperBound(SourceFrameNumbers, RequestedFrame);
        LowerIdx = FMath::Clamp(UB - 1, 0, Count - 1);
    }
    const int32 UpperIdx = FMath::Min(LowerIdx + 1, Count - 1);

    // ----- Compute lerp alpha including sub-frame -----
    // Whole-frame fraction (LowerFrame .. UpperFrame may not be 1 apart in gap case).
    const int32 LowerFrame = SourceFrameNumbers[LowerIdx];
    const int32 UpperFrame = SourceFrameNumbers[UpperIdx];
    const int32 FrameSpan = UpperFrame - LowerFrame;

    float Alpha;
    if (FrameSpan <= 0)
    {
        Alpha = 0.f;
    }
    else
    {
        const float WholePart = static_cast<float>(RequestedFrame - LowerFrame);
        Alpha = (WholePart + SubFrame) / static_cast<float>(FrameSpan);
        Alpha = FMath::Clamp(Alpha, 0.f, 1.f);
    }

    OutLowerIdx = LowerIdx;
    OutUpperIdx = UpperIdx;
    OutAlpha = Alpha;
}
