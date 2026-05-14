// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "Misc/Timecode.h"
#include "PostRenderCameraSample.h"
#include "PostRenderCameraSamples.generated.h"

/**
 * Sample DataAsset for one CSV take. Stored separately from the LevelSequence
 * so the same take can be referenced by multiple sequences and so sequence
 * asset serialization stays small.
 *
 * Schema invariants (validated in WriteCameraSamples bridge):
 *   - SourceFrameNumbers.Num() == Samples.Num()
 *   - SourceFrameNumbers strictly ascending (no duplicates, allows gaps)
 *   - FrameRate > 0
 *
 * bIsContiguous is recomputed on every write; downstream evaluator branches
 * on it (O(1) direct index vs. O(log N) binary search).
 */
UCLASS(BlueprintType)
class POSTRENDERTOOL_API UPostRenderCameraSamples : public UDataAsset
{
    GENERATED_BODY()

public:
    /** CSV source frame numbers (strictly ascending, may have gaps).
     *  Same length as Samples. Stored as int32 because UE FFrameNumber
     *  internally is int32 and Sequencer's display-rate frame indices fit. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Samples")
    TArray<int32> SourceFrameNumbers;

    /** Per-frame measurements, one entry per SourceFrameNumbers entry. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Samples")
    TArray<FPostRenderCameraSample> Samples;

    /** Cached at write time: true iff SourceFrameNumbers is a strictly +1
     *  ascending run (no gaps). Lets evaluator do O(1) direct index. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Samples")
    bool bIsContiguous = true;

    // ----- Metadata (for debugging / future migration) -----

    /** Display rate numerator (e.g. 24000 for 23.976). */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Metadata")
    int32 FrameRateNumerator = 24;

    /** Display rate denominator (e.g. 1001 for 23.976). */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Metadata")
    int32 FrameRateDenominator = 1;

    /** Originating CSV path (for traceability — not used at runtime). */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Metadata")
    FString SourceCsvPath;

    /** Bumped manually when sample schema changes incompatibly.
     *  v2 (timecode-sync) — added StartTimecode + bHasStartTimecode.
     *  v3 (sequencer-timecode-alignment) — SourceFrameNumbers semantics
     *      switched from CSV `frame` column (Disguise free-running counter)
     *      to `timecode.to_frames()` (SMPTE wall-clock since 00:00:00:00).
     *      Old v2 assets won't pass v3's `_REQUIRED_DATAASSET_SCHEMA` gate
     *      in pipeline.py — user must rerun run_import. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Metadata")
    int32 SchemaVersion = 3;

    // ----- Canonical start timecode (P0 timecode-sync) -----
    // Persisted at write time so P1 EXR patcher / OTIO exporter can read SMPTE
    // start tc directly from this DataAsset, without reflecting through
    // Section.TimecodeSource. FTimecode is BlueprintType + Python-exposed
    // (verified by scripts/probe_ue_timecode_roundtrip.py).

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Timecode")
    FTimecode StartTimecode;

    /** False on legacy DataAssets written before timecode-sync deploy or when
     *  csv_parser was invoked without fps. P1 patcher / exporter check this
     *  flag and bail with a clear error rather than emitting 00:00:00:00. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender|Timecode")
    bool bHasStartTimecode = false;

    /** First / last source frame number for quick range checks. */
    int32 GetFirstFrame() const
    {
        return SourceFrameNumbers.Num() > 0 ? SourceFrameNumbers[0] : 0;
    }
    int32 GetLastFrame() const
    {
        return SourceFrameNumbers.Num() > 0
            ? SourceFrameNumbers.Last()
            : 0;
    }

    /** Find the bounding samples for a given display-rate frame time.
     *  Returns indices [LowerIdx, UpperIdx] into Samples (clamped to range).
     *  Alpha is in [0, 1] for the fractional position between them.
     *  Empty Samples → both indices are INDEX_NONE. */
    void FindBoundingIndices(
        FFrameNumber DisplayFrameNumber,
        float SubFrame,
        int32& OutLowerIdx,
        int32& OutUpperIdx,
        float& OutAlpha) const;

    /** Recompute bIsContiguous from SourceFrameNumbers. Call after any write. */
    void RecomputeContiguity();

    // ----- UObject -----
    // Refresh bIsContiguous on load. Old saved assets (or anyone editing
    // SourceFrameNumbers outside WriteCameraSamples) could have stale
    // contiguity flag; recomputing on PostLoad makes the cache self-healing.
    virtual void PostLoad() override;
};
