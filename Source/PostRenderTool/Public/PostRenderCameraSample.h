// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "PostRenderCameraSample.generated.h"

/**
 * One frame of dense camera measurement, packed for direct array storage in
 * UPostRenderCameraSamples. 16 floats = 64 bytes per sample; a 68k-frame
 * take is ~4.4 MB of contiguous memory (cache-friendly for evaluator).
 *
 * Field order matches `Content/Python/post_render_tool/sample_packer.py`
 * SAMPLE_FIELDS. Linear interpolation is applied component-wise — Euler
 * rotations follow the legacy Sequencer Float Track behavior (no quaternion
 * slerp; matches what the 19-track path produced).
 *
 * Layout intentionally flat (no nested USTRUCTs) so the whole buffer
 * serializes as a single TArray block.
 */
USTRUCT(BlueprintType)
struct POSTRENDERTOOL_API FPostRenderCameraSample
{
    GENERATED_BODY()

    // ----- Transform (CineCameraActor) -----
    UPROPERTY(BlueprintReadWrite) float LocationX = 0.f;
    UPROPERTY(BlueprintReadWrite) float LocationY = 0.f;
    UPROPERTY(BlueprintReadWrite) float LocationZ = 0.f;
    UPROPERTY(BlueprintReadWrite) float RotationPitch = 0.f;
    UPROPERTY(BlueprintReadWrite) float RotationYaw = 0.f;
    UPROPERTY(BlueprintReadWrite) float RotationRoll = 0.f;

    // ----- CineCameraComponent -----
    UPROPERTY(BlueprintReadWrite) float FocalLengthMM = 35.f;
    UPROPERTY(BlueprintReadWrite) float Aperture = 8.f;
    UPROPERTY(BlueprintReadWrite) float FocusDistanceCM = 10000.f;
    /** mm — mirrors UE FCameraFilmbackSettings.SensorHorizontalOffset units. */
    UPROPERTY(BlueprintReadWrite) float SensorHorizontalOffsetMM = 0.f;
    UPROPERTY(BlueprintReadWrite) float SensorVerticalOffsetMM = 0.f;
    UPROPERTY(BlueprintReadWrite) float Overscan = 0.f;

    // ----- PostRenderDistortionControllerComponent -----
    UPROPERTY(BlueprintReadWrite) float K1 = 0.f;
    UPROPERTY(BlueprintReadWrite) float K2 = 0.f;
    UPROPERTY(BlueprintReadWrite) float K3 = 0.f;
    UPROPERTY(BlueprintReadWrite) float Aspect = 1.7778f;

    /** Component-wise linear interpolation between A and B at Alpha ∈ [0,1]. */
    static FPostRenderCameraSample Lerp(
        const FPostRenderCameraSample& A,
        const FPostRenderCameraSample& B,
        float Alpha);
};

FORCEINLINE FPostRenderCameraSample FPostRenderCameraSample::Lerp(
    const FPostRenderCameraSample& A,
    const FPostRenderCameraSample& B,
    float Alpha)
{
    FPostRenderCameraSample R;
    R.LocationX                = FMath::Lerp(A.LocationX, B.LocationX, Alpha);
    R.LocationY                = FMath::Lerp(A.LocationY, B.LocationY, Alpha);
    R.LocationZ                = FMath::Lerp(A.LocationZ, B.LocationZ, Alpha);
    R.RotationPitch            = FMath::Lerp(A.RotationPitch, B.RotationPitch, Alpha);
    R.RotationYaw              = FMath::Lerp(A.RotationYaw, B.RotationYaw, Alpha);
    R.RotationRoll             = FMath::Lerp(A.RotationRoll, B.RotationRoll, Alpha);
    R.FocalLengthMM            = FMath::Lerp(A.FocalLengthMM, B.FocalLengthMM, Alpha);
    R.Aperture                 = FMath::Lerp(A.Aperture, B.Aperture, Alpha);
    R.FocusDistanceCM          = FMath::Lerp(A.FocusDistanceCM, B.FocusDistanceCM, Alpha);
    R.SensorHorizontalOffsetMM = FMath::Lerp(A.SensorHorizontalOffsetMM, B.SensorHorizontalOffsetMM, Alpha);
    R.SensorVerticalOffsetMM   = FMath::Lerp(A.SensorVerticalOffsetMM, B.SensorVerticalOffsetMM, Alpha);
    R.Overscan                 = FMath::Lerp(A.Overscan, B.Overscan, Alpha);
    R.K1                       = FMath::Lerp(A.K1, B.K1, Alpha);
    R.K2                       = FMath::Lerp(A.K2, B.K2, Alpha);
    R.K3                       = FMath::Lerp(A.K3, B.K3, Alpha);
    R.Aspect                   = FMath::Lerp(A.Aspect, B.Aspect, Alpha);
    return R;
}
