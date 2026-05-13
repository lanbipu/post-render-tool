// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "ISequencerSection.h"
#include "MovieSceneTrackEditor.h"
#include "Templates/SharedPointer.h"
#include "Templates/SubclassOf.h"

class ISequencer;
class ISequencerTrackEditor;
class UMovieSceneSection;
class UMovieSceneTrack;
struct FGuid;

/**
 * Minimal Sequencer Track Editor for UPostRenderCameraTrack.
 *
 * Registered in PostRenderToolModule::StartupModule via ISequencerModule.
 * Without this registration, opening a LevelSequence that contains our
 * custom track crashes Sequencer (TSharedPtr null assert on missing
 * track editor pointer).
 *
 * We do not expose "Add Post-Render Camera Track" via the Sequencer UI —
 * the track is always added programmatically by sequence_builder.py.
 * So GetDisplayName / BuildAddTrackMenu are unused in practice; they
 * still need a sensible value for Sequencer's reflection-driven UI.
 */
class FPostRenderCameraTrackEditor : public FMovieSceneTrackEditor
{
public:
    explicit FPostRenderCameraTrackEditor(TSharedRef<ISequencer> InSequencer);

    /** Factory entry registered with ISequencerModule. */
    static TSharedRef<ISequencerTrackEditor> CreateTrackEditor(TSharedRef<ISequencer> InSequencer);

    // ----- ISequencerTrackEditor (minimum override set) -----
    virtual FText GetDisplayName() const override;
    virtual bool SupportsType(TSubclassOf<UMovieSceneTrack> Type) const override;
    virtual TSharedRef<ISequencerSection> MakeSectionInterface(
        UMovieSceneSection& SectionObject,
        UMovieSceneTrack& Track,
        FGuid ObjectBinding) override;
};

/**
 * Section interface for UPostRenderCameraSection. Default-painting
 * horizontal bar (no per-frame keyframe markers — the dense data lives
 * in the linked DataAsset, not in the section itself).
 */
class FPostRenderCameraSection : public FSequencerSection
{
public:
    explicit FPostRenderCameraSection(UMovieSceneSection& InSection);

    // FSequencerSection provides default OnPaintSection / GetSectionObject /
    // IsReadOnly / DilateSection + holds WeakSection — override only what
    // diverges from the default horizontal-bar visualization.
    virtual FText GetSectionTitle() const override;
};
