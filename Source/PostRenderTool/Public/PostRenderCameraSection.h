// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "MovieSceneSection.h"
#include "PostRenderCameraSection.generated.h"

class UPostRenderCameraSamples;

/**
 * One section per LevelSequence that drives the bound CineCameraActor from a
 * UPostRenderCameraSamples DataAsset. Section range maps display-rate frames
 * [0, SampleCount) to ticks via the sequence's tick resolution.
 *
 * The section itself is tiny — just a soft+hard ref to the asset. All heavy
 * data lives in the DataAsset, so the LevelSequence .uasset stays compact.
 */
UCLASS(MinimalAPI)
class UPostRenderCameraSection : public UMovieSceneSection
{
    GENERATED_BODY()

public:
    UPostRenderCameraSection();

    /** The sample DataAsset this section evaluates. Hard reference because
     *  evaluation runs every frame in MRQ — soft refs would force a load
     *  spike on first eval. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="PostRender")
    TObjectPtr<UPostRenderCameraSamples> SampleAsset;
};
