// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Evaluation/MovieSceneEvalTemplate.h"
#include "PostRenderCameraSample.h"
#include "PostRenderCameraSectionTemplate.generated.h"

class UPostRenderCameraSamples;
class UPostRenderCameraSection;

/**
 * Per-section evaluation template. Constructed by
 * UPostRenderCameraTrack::CreateTemplateForSection during sequence compile;
 * serialized into the FMovieSceneEvaluationTemplate alongside the rest of
 * the sequence's tracks.
 *
 * Holds a weak-style raw pointer to the sample DataAsset — UE serializes
 * the object reference into the compiled template (see
 * FMovieSceneEvalTemplatePtr for the pattern). Worker-thread safety:
 * Evaluate only reads from SampleAsset and writes to ExecutionTokens —
 * no UObject mutation here. Actual writes happen in
 * FPostRenderCameraExecutionToken::Execute on the game thread.
 */
USTRUCT()
struct FPostRenderCameraSectionTemplate : public FMovieSceneEvalTemplate
{
    GENERATED_BODY()

    FPostRenderCameraSectionTemplate() = default;
    FPostRenderCameraSectionTemplate(const UPostRenderCameraSection& InSection);

    virtual UScriptStruct& GetScriptStructImpl() const override
    {
        return *StaticStruct();
    }

    virtual void Evaluate(
        const FMovieSceneEvaluationOperand& Operand,
        const FMovieSceneContext& Context,
        const FPersistentEvaluationData& PersistentData,
        FMovieSceneExecutionTokens& ExecutionTokens) const override;

    UPROPERTY()
    TObjectPtr<UPostRenderCameraSamples> SampleAsset;

    UPROPERTY()
    FFrameNumber SectionStartFrame;
};
