// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderDistortionControllerComponent.h"

#include "CineCameraComponent.h"
#include "Engine/Scene.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"

UPostRenderDistortionControllerComponent::UPostRenderDistortionControllerComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
    PrimaryComponentTick.bStartWithTickEnabled = true;

    // bTickInEditor enables Tick outside PIE so Sequencer scrubbing in the
    // editor animates material parameters live. MRQ render hits the normal
    // PIE-like flow and ticks regardless.
    bTickInEditor = true;
    bAutoActivate = true;

    // Defaults match the OpenCV-standard formula in
    // distortion_math.official_sensor_inverse_uv. Pipeline overrides per frame
    // via Sequencer keyframes; these defaults only matter for unattached
    // components placed manually in the editor.
    BaseMaterial = nullptr;
    K1 = 0.0f;
    K2 = 0.0f;
    K3 = 0.0f;
    CenterU = 0.5f;
    CenterV = 0.5f;
    Aspect = 16.0f / 9.0f;
    DistortionWeight = 1.0f;
    Overscan = 0.0f;

    DistortionMID = nullptr;
}

void UPostRenderDistortionControllerComponent::BeginPlay()
{
    Super::BeginPlay();

    if (!BaseMaterial)
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderTool/DistortionController] BaseMaterial unset — "
                 "component on actor '%s' has no material to drive."),
            *GetNameSafe(GetOwner()));
        return;
    }

    AActor* Owner = GetOwner();
    if (!Owner)
    {
        return;
    }

    // CineCameraActor's root is UCineCameraComponent; FindComponentByClass also
    // catches the case where someone wired up a custom actor with one nested.
    UCineCameraComponent* Camera = Owner->FindComponentByClass<UCineCameraComponent>();
    if (!Camera)
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderTool/DistortionController] Owner '%s' has no "
                 "UCineCameraComponent — distortion material cannot bind."),
            *GetNameSafe(Owner));
        return;
    }

    DistortionMID = UMaterialInstanceDynamic::Create(BaseMaterial, this);
    if (!DistortionMID)
    {
        UE_LOG(LogTemp, Error,
            TEXT("[PostRenderTool/DistortionController] MID creation failed for "
                 "BaseMaterial '%s'."),
            *GetNameSafe(BaseMaterial));
        return;
    }

    Camera->PostProcessSettings.AddBlendable(DistortionMID, /*Weight*/ 1.0f);

    RefreshMaterialParameters();

    UE_LOG(LogTemp, Log,
        TEXT("[PostRenderTool/DistortionController] Bound MID '%s' to camera "
             "'%s' on actor '%s'."),
        *GetNameSafe(DistortionMID),
        *GetNameSafe(Camera),
        *GetNameSafe(Owner));
}

void UPostRenderDistortionControllerComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    if (DistortionMID)
    {
        if (AActor* Owner = GetOwner())
        {
            if (UCineCameraComponent* Camera = Owner->FindComponentByClass<UCineCameraComponent>())
            {
                // No FPostProcessSettings::RemoveBlendable helper exists; manipulate
                // the underlying array directly. WeightedBlendables.Array stores
                // FWeightedBlendable {Weight, Object}; we match by Object pointer.
                TArray<FWeightedBlendable>& Blendables =
                    Camera->PostProcessSettings.WeightedBlendables.Array;
                Blendables.RemoveAll([this](const FWeightedBlendable& Entry)
                {
                    return Entry.Object == DistortionMID;
                });
            }
        }
        DistortionMID = nullptr;
    }

    Super::EndPlay(EndPlayReason);
}

void UPostRenderDistortionControllerComponent::TickComponent(
    float DeltaTime,
    ELevelTick TickType,
    FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
    RefreshMaterialParameters();
}

void UPostRenderDistortionControllerComponent::RefreshMaterialParameters()
{
    if (!DistortionMID)
    {
        return;
    }

    // Scalar parameter names must match the M_PRT_OfficialSensorInverse material
    // graph 1:1. Material asset is built manually in lanPC UE Editor (Material
    // editor has no usable Python automation API); see
    // docs/custom-postprocess-distortion-final-plan.md §4.3.
    DistortionMID->SetScalarParameterValue(TEXT("K1"), K1);
    DistortionMID->SetScalarParameterValue(TEXT("K2"), K2);
    DistortionMID->SetScalarParameterValue(TEXT("K3"), K3);
    DistortionMID->SetScalarParameterValue(TEXT("Aspect"), Aspect);
    DistortionMID->SetScalarParameterValue(TEXT("DistortionWeight"), DistortionWeight);
    DistortionMID->SetScalarParameterValue(TEXT("Overscan"), Overscan);

    // CenterUV is a Vector parameter (Vector4 / FLinearColor). Material reads
    // R for U, G for V; B and A unused. Two scalar UPROPERTYs (CenterU,
    // CenterV) instead of one FVector2D so Sequencer float tracks work natively.
    DistortionMID->SetVectorParameterValue(
        TEXT("CenterUV"),
        FLinearColor(CenterU, CenterV, 0.0f, 0.0f));
}
