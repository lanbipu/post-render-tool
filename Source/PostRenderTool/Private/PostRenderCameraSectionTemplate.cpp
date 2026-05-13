// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderCameraSectionTemplate.h"

#include "CineCameraActor.h"
#include "CineCameraComponent.h"
#include "Evaluation/MovieSceneEvaluation.h"
#include "Evaluation/MovieSceneExecutionTokens.h"
#include "IMovieScenePlayer.h"
#include "MovieSceneCommonHelpers.h"
#include "PostRenderCameraSamples.h"
#include "PostRenderCameraSection.h"
#include "PostRenderDistortionControllerComponent.h"

namespace
{
    /**
     * Game-thread token that applies one interpolated FPostRenderCameraSample
     * to the bound CineCameraActor's transform + CineCameraComponent
     * properties + PostRenderDistortionControllerComponent parameters.
     *
     * Explicitly calls RefreshMaterialParameters() to bypass TickComponent
     * tick-ordering dependency (DistortionMID gets written before the next
     * scene render, regardless of component tick group).
     */
    struct FPostRenderCameraExecutionToken : IMovieSceneExecutionToken
    {
        FPostRenderCameraExecutionToken(const FPostRenderCameraSample& InSample)
            : Sample(InSample)
        {}

        virtual void Execute(
            const FMovieSceneContext& Context,
            const FMovieSceneEvaluationOperand& Operand,
            FPersistentEvaluationData& PersistentData,
            IMovieScenePlayer& Player) override
        {
            for (TWeakObjectPtr<> WeakObj : Player.FindBoundObjects(Operand))
            {
                UObject* Bound = WeakObj.Get();
                if (!Bound)
                {
                    continue;
                }

                ACineCameraActor* CameraActor = Cast<ACineCameraActor>(Bound);
                if (!CameraActor)
                {
                    continue;
                }

                // ----- Actor transform -----
                FTransform NewTransform;
                NewTransform.SetLocation(FVector(Sample.LocationX, Sample.LocationY, Sample.LocationZ));
                NewTransform.SetRotation(FRotator(
                    Sample.RotationPitch,
                    Sample.RotationYaw,
                    Sample.RotationRoll
                ).Quaternion());
                NewTransform.SetScale3D(FVector::OneVector);
                CameraActor->SetActorTransform(NewTransform);

                // ----- CineCameraComponent -----
                UCineCameraComponent* CineComp = CameraActor->GetCineCameraComponent();
                if (CineComp)
                {
                    CineComp->CurrentFocalLength = Sample.FocalLengthMM;
                    CineComp->CurrentAperture    = Sample.Aperture;
                    CineComp->FocusSettings.ManualFocusDistance = Sample.FocusDistanceCM;

                    FCameraFilmbackSettings Film = CineComp->Filmback;
                    Film.SensorHorizontalOffset = Sample.SensorHorizontalOffsetMM;
                    Film.SensorVerticalOffset   = Sample.SensorVerticalOffsetMM;
                    CineComp->Filmback = Film;

                    CineComp->Overscan = Sample.Overscan;
                }

                // ----- Distortion controller -----
                TArray<UActorComponent*> Found;
                CameraActor->GetComponents(UPostRenderDistortionControllerComponent::StaticClass(), Found);
                for (UActorComponent* Comp : Found)
                {
                    UPostRenderDistortionControllerComponent* Ctl =
                        Cast<UPostRenderDistortionControllerComponent>(Comp);
                    if (!Ctl) continue;

                    Ctl->K1               = Sample.K1;
                    Ctl->K2               = Sample.K2;
                    Ctl->K3               = Sample.K3;
                    Ctl->Aspect           = Sample.Aspect;
                    Ctl->Overscan         = Sample.Overscan;
                    // CenterU/V/DistortionWeight are constants set at component
                    // construction (0.5, 0.5, 1.0); not driven per-sample.
                    Ctl->RefreshMaterialParameters();
                }
            }
        }

        FPostRenderCameraSample Sample;
    };
}

FPostRenderCameraSectionTemplate::FPostRenderCameraSectionTemplate(
    const UPostRenderCameraSection& InSection)
    : SampleAsset(InSection.SampleAsset)
    , SectionStartFrame(InSection.HasStartFrame() ? InSection.GetInclusiveStartFrame() : FFrameNumber(0))
{
}

void FPostRenderCameraSectionTemplate::Evaluate(
    const FMovieSceneEvaluationOperand& Operand,
    const FMovieSceneContext& Context,
    const FPersistentEvaluationData& PersistentData,
    FMovieSceneExecutionTokens& ExecutionTokens) const
{
    if (!SampleAsset || SampleAsset->Samples.Num() == 0)
    {
        return;
    }

    // ----- Convert tick-resolution time to display-rate frame + sub-frame -----
    const FFrameRate TickResolution = Context.GetFrameRate();
    const FFrameRate DisplayRate(SampleAsset->FrameRateNumerator,
                                 SampleAsset->FrameRateDenominator);

    const FFrameTime TicksTime = Context.GetTime();
    const FFrameTime DisplayTime = FFrameRate::TransformTime(TicksTime, TickResolution, DisplayRate);

    // Section starts at SectionStartFrame (tick space); offset into the asset
    // is measured from there. Convert section start to display rate too.
    const FFrameTime SectionStartDisplay = FFrameRate::TransformTime(
        FFrameTime(SectionStartFrame), TickResolution, DisplayRate);

    // Asset frame numbers are stored in CSV space (absolute, e.g. 1000..68199).
    // The section's "first asset frame" is whatever SampleAsset->GetFirstFrame()
    // returns; section-local display offset 0 maps to it.
    //
    // Use FloorToFrame (NOT RoundToInt32) for the base frame. RoundToInt32 on
    // local time 10.75 returns 11, so the bounding pair becomes 11→12 with
    // subframe 0.75 — one frame ahead of the correct 10→11. MRQ temporal
    // samples / motion blur / subframe scrub all hit non-integer times,
    // making this a silent render-corruption bug under rounding semantics.
    const FFrameTime LocalDisplayTime = DisplayTime - SectionStartDisplay;
    const int32 AssetFrameOffset =
        LocalDisplayTime.FloorToFrame().Value
        + SampleAsset->GetFirstFrame();
    const float SubFrame = LocalDisplayTime.GetSubFrame();

    int32 LowerIdx, UpperIdx;
    float Alpha;
    SampleAsset->FindBoundingIndices(FFrameNumber(AssetFrameOffset), SubFrame,
                                     LowerIdx, UpperIdx, Alpha);

    if (LowerIdx == INDEX_NONE)
    {
        return;
    }

    const FPostRenderCameraSample Interpolated = FPostRenderCameraSample::Lerp(
        SampleAsset->Samples[LowerIdx],
        SampleAsset->Samples[UpperIdx],
        Alpha);

    ExecutionTokens.Add(FPostRenderCameraExecutionToken(Interpolated));
}
