// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderCameraTrackEditor.h"

#include "ISequencer.h"
#include "PostRenderCameraSection.h"
#include "PostRenderCameraTrack.h"

#define LOCTEXT_NAMESPACE "PostRenderCameraTrackEditor"

FPostRenderCameraTrackEditor::FPostRenderCameraTrackEditor(TSharedRef<ISequencer> InSequencer)
    : FMovieSceneTrackEditor(InSequencer)
{
}

TSharedRef<ISequencerTrackEditor> FPostRenderCameraTrackEditor::CreateTrackEditor(TSharedRef<ISequencer> InSequencer)
{
    return MakeShared<FPostRenderCameraTrackEditor>(InSequencer);
}

FText FPostRenderCameraTrackEditor::GetDisplayName() const
{
    return LOCTEXT("DisplayName", "Post-Render Camera Track");
}

bool FPostRenderCameraTrackEditor::SupportsType(TSubclassOf<UMovieSceneTrack> Type) const
{
    return Type == UPostRenderCameraTrack::StaticClass();
}

TSharedRef<ISequencerSection> FPostRenderCameraTrackEditor::MakeSectionInterface(
    UMovieSceneSection& SectionObject,
    UMovieSceneTrack& /*Track*/,
    FGuid /*ObjectBinding*/)
{
    return MakeShared<FPostRenderCameraSection>(SectionObject);
}

// ----- Section -----

FPostRenderCameraSection::FPostRenderCameraSection(UMovieSceneSection& InSection)
    : WeakSection(&InSection)
{
}

UMovieSceneSection* FPostRenderCameraSection::GetSectionObject()
{
    return WeakSection.Get();
}

FText FPostRenderCameraSection::GetSectionTitle() const
{
    return LOCTEXT("SectionTitle", "Post-Render Camera Samples");
}

#undef LOCTEXT_NAMESPACE
