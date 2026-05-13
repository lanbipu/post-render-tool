// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "MovieSceneTrack.h"
#include "Compilation/IMovieSceneTrackTemplateProducer.h"
#include "PostRenderCameraTrack.generated.h"

class UMovieSceneSection;
class FMovieSceneEvalTemplate;

/**
 * Single-section track bound to a CineCameraActor possessable. Replaces the
 * 19 Float Tracks + 1 Transform Track the old sequence_builder used to write.
 *
 * Implements IMovieSceneTrackTemplateProducer so the compiled
 * FMovieSceneEvaluationTemplate gets one FPostRenderCameraSectionTemplate
 * per section (we expect exactly one section per binding).
 */
UCLASS(MinimalAPI)
class UPostRenderCameraTrack
    : public UMovieSceneTrack
    , public IMovieSceneTrackTemplateProducer
{
    GENERATED_BODY()

public:
    UPostRenderCameraTrack();

    // ----- UMovieSceneTrack -----
    virtual UMovieSceneSection* CreateNewSection() override;
    virtual void AddSection(UMovieSceneSection& Section) override;
    virtual bool HasSection(const UMovieSceneSection& Section) const override;
    virtual bool IsEmpty() const override;
    virtual void RemoveAllAnimationData() override;
    virtual void RemoveSection(UMovieSceneSection& Section) override;
    virtual void RemoveSectionAt(int32 SectionIndex) override;
    virtual const TArray<UMovieSceneSection*>& GetAllSections() const override;
    virtual bool SupportsType(TSubclassOf<UMovieSceneSection> SectionClass) const override;
    virtual bool SupportsMultipleRows() const override { return false; }

    // ----- IMovieSceneTrackTemplateProducer -----
    virtual FMovieSceneEvalTemplatePtr CreateTemplateForSection(
        const UMovieSceneSection& InSection) const override;

private:
    UPROPERTY()
    TArray<TObjectPtr<UMovieSceneSection>> Sections;
};
