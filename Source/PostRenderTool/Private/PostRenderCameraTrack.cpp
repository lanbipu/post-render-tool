// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderCameraTrack.h"
#include "PostRenderCameraSection.h"
#include "PostRenderCameraSectionTemplate.h"

UPostRenderCameraTrack::UPostRenderCameraTrack(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer)
{
#if WITH_EDITORONLY_DATA
    TrackTint = FColor(70, 130, 180);  // steel blue — distinguishable in Sequencer
#endif
}

UMovieSceneSection* UPostRenderCameraTrack::CreateNewSection()
{
    return NewObject<UPostRenderCameraSection>(this, NAME_None, RF_Transactional);
}

void UPostRenderCameraTrack::AddSection(UMovieSceneSection& Section)
{
    Sections.Add(&Section);
}

bool UPostRenderCameraTrack::HasSection(const UMovieSceneSection& Section) const
{
    return Sections.Contains(&Section);
}

bool UPostRenderCameraTrack::IsEmpty() const
{
    return Sections.Num() == 0;
}

void UPostRenderCameraTrack::RemoveAllAnimationData()
{
    Sections.Empty();
}

void UPostRenderCameraTrack::RemoveSection(UMovieSceneSection& Section)
{
    Sections.Remove(&Section);
}

void UPostRenderCameraTrack::RemoveSectionAt(int32 SectionIndex)
{
    if (Sections.IsValidIndex(SectionIndex))
    {
        Sections.RemoveAt(SectionIndex);
    }
}

const TArray<UMovieSceneSection*>& UPostRenderCameraTrack::GetAllSections() const
{
    return Sections;
}

bool UPostRenderCameraTrack::SupportsType(TSubclassOf<UMovieSceneSection> SectionClass) const
{
    return SectionClass == UPostRenderCameraSection::StaticClass();
}

FMovieSceneEvalTemplatePtr UPostRenderCameraTrack::CreateTemplateForSection(
    const UMovieSceneSection& InSection) const
{
    const UPostRenderCameraSection* TypedSection = Cast<UPostRenderCameraSection>(&InSection);
    if (!TypedSection)
    {
        return FMovieSceneEvalTemplatePtr();
    }
    return FMovieSceneEvalTemplatePtr(FPostRenderCameraSectionTemplate(*TypedSection));
}
