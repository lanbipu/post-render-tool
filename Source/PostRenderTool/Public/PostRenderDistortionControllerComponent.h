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
 * CenterV/Aspect/DistortionWeight. Material parameter names must match
 * exactly:
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

    /** Distortion-center U coordinate (UV space, [0, 1]). Computed by
     *  pipeline as `0.5 + centerShiftMM.x / sensorWidthMM`. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category="Distortion")
    float CenterU;

    /** Distortion-center V coordinate. Computed by pipeline as
     *  `0.5 + centerShiftMM.y / (sensorWidthMM / aspect)`. */
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

    /** Overscan amount [0, 1] (UE convention; CSV ratio - 1.0). When camera
     *  has Overscan > 0 + bScaleResolutionWithOverscan + bCropOverscan,
     *  PP material renders on the overscanned SceneTexture (e.g. 2560x1440
     *  for 0.3334), but K1/K2/K3 are calibrated against the original 1920x1080
     *  frustum. Shader uses this to remap viewport UV → original frustum UV
     *  before applying the radial formula, then unmaps back to viewport for
     *  SceneTexture sampling. Overscan = 0 → identity remap (preserves the
     *  pre-overscan algorithm 1:1, take_5/6 unchanged). Pipeline writes this
     *  per-frame, mirrored from the CineCameraComponent.Overscan keyframe. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Interp, Category="Distortion")
    float Overscan;

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
