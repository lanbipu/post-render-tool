// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "PostRenderDistortionControllerComponent.generated.h"

class UMaterialInterface;
class UMaterialInstanceDynamic;

/**
 * Post-Render Distortion Controller Component.
 *
 * Drives M_PRT_OfficialSensorInverse (post-process material) parameters
 * per frame. Sequencer keyframes the seven Interp UPROPERTYs below;
 * TickComponent pushes them to the cached MaterialInstanceDynamic.
 *
 * Pipeline (sequence_builder.py) attaches this component to the
 * CineCameraActor it spawns and writes float tracks for K1/K2/K3/CenterU/
 * CenterV/Aspect/DistortionWeight. The centerShiftMM principal-point
 * projection path runs in parallel through UCineCameraComponent
 * Filmback.SensorHorizontalOffset and Filmback.SensorVerticalOffset tracks
 * (sign-flipped on both axes; formula in distortion_math.map_center_shift_projection,
 * 2026-05-07 K=0 closed-loop validated to < 0.2 px residual). CenterUV only
 * drives the radial distortion center.
 * Material parameter names must match exactly:
 *   - K1, K2, K3, Aspect, DistortionWeight  → Scalar parameters
 *   - CenterUV                                → Vector parameter (R=U, G=V)
 *
 * Math contract is in `Content/Python/post_render_tool/distortion_math.py`
 * (`official_sensor_inverse_uv`). HLSL shader graph in the material asset
 * must match that Python reference one-to-one. See
 * `docs/custom-postprocess-distortion-final-plan.md` §2.4 / §4.2.
 *
 * The seven driven UPROPERTYs use:
 *   - `Interp` — required for Sequencer keyframable float tracks.
 *   - `BlueprintReadWrite` — required for Python (`set_editor_property`)
 *     and Sequencer track creation; without it the property has no
 *     CPF_BlueprintVisible flag.
 *   - `EditAnywhere` — manual tweaking from the Details panel.
 *
 * Adding/removing/renaming any UPROPERTY here requires a full Editor
 * restart + UBT rebuild — Live Coding does NOT support reflection
 * metadata changes (see CLAUDE.md gotchas).
 */
UCLASS(ClassGroup=(VPPostRender), meta=(BlueprintSpawnableComponent))
class POSTRENDERTOOL_API UPostRenderDistortionControllerComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UPostRenderDistortionControllerComponent();

    // ======================================================================
    // Material reference
    // ======================================================================

    /** Post-process material asset (M_PRT_OfficialSensorInverse). MID is
     *  created from this at BeginPlay and pushed into the owner camera's
     *  PostProcessSettings.WeightedBlendables. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Distortion")
    UMaterialInterface* BaseMaterial;

    // ======================================================================
    // Per-frame distortion parameters (Sequencer keyframable)
    // ======================================================================

    /** Disguise CSV K1 — radial r² coefficient. Pass-through, no sign flip. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category="Distortion")
    float K1;

    /** Disguise CSV K2 — radial r⁴ coefficient (OpenCV standard form;
     *  Gate 6 reference-frame analysis may revise the order/sign). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category="Distortion")
    float K2;

    /** Disguise CSV K3 — radial r⁶ coefficient (OpenCV standard form;
     *  Gate 6 reference-frame analysis may revise the order/sign). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category="Distortion")
    float K3;

    /** Radial distortion-center U coordinate (UV space, [0, 1]). Computed by
     *  pipeline as `0.5 + centerShiftMM.x / sensorWidthMM`. The projection
     *  part of centerShiftMM is handled on the CineCamera Filmback track. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category="Distortion")
    float CenterU;

    /** Radial distortion-center V coordinate. Computed by pipeline as
     *  `0.5 + centerShiftMM.y / (sensorWidthMM / aspect)`. The projection
     *  part of centerShiftMM is handled on the CineCamera Filmback track. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category="Distortion")
    float CenterV;

    /** Frame aspect ratio W/H. Per-frame because zoom takes can have
     *  varying overscan; pipeline pulls it from CSV. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category="Distortion")
    float Aspect;

    /** Distortion strength multiplier. 1.0 = full effect, 0.0 = identity
     *  (no warp). Useful for fade-in / debugging. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category="Distortion")
    float DistortionWeight;

    // ======================================================================
    // Manually push current parameter state to the MID. Pipeline does not
    // need to call this — TickComponent does it every frame. Exposed for
    // editor-time debugging.
    // ======================================================================

    UFUNCTION(BlueprintCallable, Category="Distortion")
    void RefreshMaterialParameters();

    // ======================================================================
    // UActorComponent overrides
    // ======================================================================

    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void TickComponent(
        float DeltaTime,
        ELevelTick TickType,
        FActorComponentTickFunction* ThisTickFunction) override;

protected:
    /** Cached MID instance. Created in BeginPlay from BaseMaterial.
     *  Marked Transient — never serialized. */
    UPROPERTY(Transient)
    UMaterialInstanceDynamic* DistortionMID;
};
