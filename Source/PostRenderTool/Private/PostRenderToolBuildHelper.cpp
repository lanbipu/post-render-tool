// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderToolBuildHelper.h"

#include "WidgetBlueprint.h"
#include "Blueprint/WidgetTree.h"
#include "Components/Widget.h"
#include "Components/PanelWidget.h"
#include "Components/ContentWidget.h"
#include "Components/NamedSlotInterface.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "MovieScene.h"
#include "MovieSceneSequence.h"
#include "PostRenderCameraSample.h"
#include "PostRenderCameraSamples.h"
#include "PostRenderCameraSection.h"
#include "PostRenderCameraTrack.h"
#include "UObject/Package.h"

namespace
{
    UWidget* FindWidgetByNameRecursive(UWidget* Root, FName TargetName)
    {
        if (!Root)
        {
            return nullptr;
        }
        if (Root->GetFName() == TargetName)
        {
            return Root;
        }
        if (UPanelWidget* Panel = Cast<UPanelWidget>(Root))
        {
            for (int32 Index = 0; Index < Panel->GetChildrenCount(); ++Index)
            {
                if (UWidget* Found = FindWidgetByNameRecursive(Panel->GetChildAt(Index), TargetName))
                {
                    return Found;
                }
            }
        }
        else if (UContentWidget* ContentW = Cast<UContentWidget>(Root))
        {
            return FindWidgetByNameRecursive(ContentW->GetContent(), TargetName);
        }
        // INamedSlotInterface (ExpandableArea, NamedSlot): descend into each named slot.
        // Without this, widgets placed in ExpandableArea.HeaderContent/BodyContent slots
        // become invisible to idempotency checks, so rerun() recreates them every time.
        if (INamedSlotInterface* NamedSlot = Cast<INamedSlotInterface>(Root))
        {
            TArray<FName> SlotNames;
            NamedSlot->GetSlotNames(SlotNames);
            for (FName SlotName : SlotNames)
            {
                if (UWidget* Found = FindWidgetByNameRecursive(NamedSlot->GetContentForSlot(SlotName), TargetName))
                {
                    return Found;
                }
            }
        }
        return nullptr;
    }

    // Detach a widget from whatever parent currently holds it, so it can be
    // re-parented into a new slot. Covers three cases:
    //  - UPanelWidget parent → RemoveChild(widget)
    //  - INamedSlotInterface parent → FindSlotForContent + SetContentForSlot(nullptr)
    //  - UContentWidget parent → SetContent(nullptr)
    // UWidget::GetParent only returns UPanelWidget parents, so the other two
    // require a tree walk to find the holder.
    bool DetachFromAnyParent(UWidget* Root, UWidget* Target)
    {
        if (!Root || !Target || Root == Target)
        {
            return false;
        }
        if (UPanelWidget* Panel = Cast<UPanelWidget>(Root))
        {
            for (int32 Index = 0; Index < Panel->GetChildrenCount(); ++Index)
            {
                UWidget* Child = Panel->GetChildAt(Index);
                if (Child == Target)
                {
                    Panel->RemoveChildAt(Index);
                    return true;
                }
                if (DetachFromAnyParent(Child, Target))
                {
                    return true;
                }
            }
        }
        else if (UContentWidget* ContentW = Cast<UContentWidget>(Root))
        {
            UWidget* Inner = ContentW->GetContent();
            if (Inner == Target)
            {
                ContentW->SetContent(nullptr);
                return true;
            }
            return DetachFromAnyParent(Inner, Target);
        }
        if (INamedSlotInterface* NamedSlot = Cast<INamedSlotInterface>(Root))
        {
            TArray<FName> SlotNames;
            NamedSlot->GetSlotNames(SlotNames);
            for (FName SlotName : SlotNames)
            {
                UWidget* Inner = NamedSlot->GetContentForSlot(SlotName);
                if (Inner == Target)
                {
                    NamedSlot->SetContentForSlot(SlotName, nullptr);
                    return true;
                }
                if (DetachFromAnyParent(Inner, Target))
                {
                    return true;
                }
            }
        }
        return false;
    }
}

UPanelWidget* UPostRenderToolBuildHelper::EnsureRootPanel(UWidgetBlueprint* Blueprint,
                                                          FName RootName,
                                                          TSubclassOf<UPanelWidget> RootClass)
{
    if (!Blueprint || !RootClass || RootName.IsNone())
    {
        return nullptr;
    }

    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return nullptr;
    }

    if (UPanelWidget* Existing = Cast<UPanelWidget>(Tree->RootWidget))
    {
        return Existing;
    }

    if (Tree->RootWidget != nullptr)
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderToolBuildHelper] Root widget '%s' is %s (not a PanelWidget). "
                 "Refusing to overwrite — wrap or replace manually in Designer."),
            *Tree->RootWidget->GetName(),
            *Tree->RootWidget->GetClass()->GetName());
        return nullptr;
    }

    UPanelWidget* NewRoot = Cast<UPanelWidget>(Tree->ConstructWidget<UWidget>(RootClass, RootName));
    if (!NewRoot)
    {
        return nullptr;
    }
    Tree->RootWidget = NewRoot;
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    return NewRoot;
}

UWidget* UPostRenderToolBuildHelper::FindWidgetByName(UWidgetBlueprint* Blueprint,
                                                      FName TargetName)
{
    if (!Blueprint || TargetName.IsNone())
    {
        return nullptr;
    }
    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return nullptr;
    }
    return FindWidgetByNameRecursive(Tree->RootWidget, TargetName);
}

EEnsureWidgetResult UPostRenderToolBuildHelper::EnsureWidgetUnderParent(
    UWidgetBlueprint* Blueprint,
    FName WidgetName,
    TSubclassOf<UWidget> WidgetClass,
    UWidget* ParentWidget,
    UWidget*& OutWidget,
    UPanelSlot*& OutSlot)
{
    OutWidget = nullptr;
    OutSlot = nullptr;
    if (!Blueprint || !WidgetClass || WidgetName.IsNone() || !ParentWidget)
    {
        return EEnsureWidgetResult::InvalidInput;
    }
    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return EEnsureWidgetResult::InvalidInput;
    }

    // Already-exists check across the whole tree (idempotency contract).
    if (UWidget* Existing = FindWidgetByNameRecursive(Tree->RootWidget, WidgetName))
    {
        if (Existing->IsA(WidgetClass))
        {
            OutWidget = Existing;
            // OutSlot stays null: the caller MUST NOT re-apply slot props, by contract.
            return EEnsureWidgetResult::AlreadyExisted;
        }
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderToolBuildHelper] Widget '%s' exists as %s, spec wants %s — type mismatch."),
            *WidgetName.ToString(),
            *Existing->GetClass()->GetName(),
            *WidgetClass->GetName());
        return EEnsureWidgetResult::TypeMismatch;
    }

    UWidget* NewWidget = Tree->ConstructWidget<UWidget>(WidgetClass, WidgetName);
    if (!NewWidget)
    {
        return EEnsureWidgetResult::InvalidInput;
    }

    // AddChild / SetContent both return UPanelSlot* (verified PanelWidget.h:58-59,
    // ContentWidget.h:18-27) — hand it back to Python so it can set slot props
    // without a second UFUNCTION round-trip.
    if (UPanelWidget* ParentPanel = Cast<UPanelWidget>(ParentWidget))
    {
        OutSlot = ParentPanel->AddChild(NewWidget);
    }
    else if (UContentWidget* ParentContent = Cast<UContentWidget>(ParentWidget))
    {
        OutSlot = ParentContent->SetContent(NewWidget);
    }
    else
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderToolBuildHelper] Parent '%s' (%s) cannot hold children."),
            *ParentWidget->GetName(),
            *ParentWidget->GetClass()->GetName());
        return EEnsureWidgetResult::ParentCannotHoldChildren;
    }

    // Structural change → must use MarkBlueprintAsStructurallyModified, not Modify():
    // widget tree topology changes invalidate the generated class layout, so the BP
    // needs to be flagged for full recompile on next CompileBlueprint call.
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    OutWidget = NewWidget;

    // Note on bIsVariable: UWidget::bIsVariable (Widget.h:318) is a private bitfield,
    // no public setter. Widget.cpp:195 constructor initializes to TRUE by default, so
    // every widget we just constructed is automatically a Variable — exactly what
    // BindWidget / BindWidgetOptional contract widgets need for reflection. Decorative
    // widgets inherit the same default (minor overhead on generated class, harmless).
    return EEnsureWidgetResult::Created;
}

EEnsureWidgetResult UPostRenderToolBuildHelper::EnsureWidgetInNamedSlot(
    UWidgetBlueprint* Blueprint,
    FName WidgetName,
    TSubclassOf<UWidget> WidgetClass,
    UWidget* NamedSlotParent,
    FName SlotName,
    UWidget*& OutWidget)
{
    OutWidget = nullptr;
    if (!Blueprint || !WidgetClass || WidgetName.IsNone() || !NamedSlotParent || SlotName.IsNone())
    {
        return EEnsureWidgetResult::InvalidInput;
    }
    UWidgetTree* Tree = Blueprint->WidgetTree;
    if (!Tree)
    {
        return EEnsureWidgetResult::InvalidInput;
    }
    INamedSlotInterface* NamedSlot = Cast<INamedSlotInterface>(NamedSlotParent);
    if (!NamedSlot)
    {
        UE_LOG(LogTemp, Warning,
            TEXT("[PostRenderToolBuildHelper] Parent '%s' (%s) does not implement INamedSlotInterface."),
            *NamedSlotParent->GetName(),
            *NamedSlotParent->GetClass()->GetName());
        return EEnsureWidgetResult::ParentCannotHoldChildren;
    }

    // Idempotency across the whole tree — FindWidgetByNameRecursive now descends into
    // named slots, so a widget already placed in Header/Body is detected.
    if (UWidget* Existing = FindWidgetByNameRecursive(Tree->RootWidget, WidgetName))
    {
        if (!Existing->IsA(WidgetClass))
        {
            UE_LOG(LogTemp, Warning,
                TEXT("[PostRenderToolBuildHelper] Widget '%s' exists as %s, spec wants %s — type mismatch."),
                *WidgetName.ToString(),
                *Existing->GetClass()->GetName(),
                *WidgetClass->GetName());
            return EEnsureWidgetResult::TypeMismatch;
        }
        // Already in the expected slot? No-op (idempotency preserves user tweaks).
        if (NamedSlot->GetContentForSlot(SlotName) == Existing)
        {
            OutWidget = Existing;
            return EEnsureWidgetResult::AlreadyExisted;
        }
        // Exists elsewhere in the tree → migration path: detach from old parent,
        // move into the requested named slot. Covers "old spec had header/body as
        // direct VerticalBox children, new spec wraps them in ExpandableArea."
        DetachFromAnyParent(Tree->RootWidget, Existing);
        NamedSlot->SetContentForSlot(SlotName, Existing);
        FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
        OutWidget = Existing;
        return EEnsureWidgetResult::AlreadyExisted;
    }

    UWidget* NewWidget = Tree->ConstructWidget<UWidget>(WidgetClass, WidgetName);
    if (!NewWidget)
    {
        return EEnsureWidgetResult::InvalidInput;
    }
    NamedSlot->SetContentForSlot(SlotName, NewWidget);
    FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
    OutWidget = NewWidget;
    return EEnsureWidgetResult::Created;
}

// ============================================================================
// Custom MovieScene Track bridges
// ============================================================================

bool UPostRenderToolBuildHelper::WriteCameraSamples(
    UPostRenderCameraSamples* SampleAsset,
    const TArray<int32>& FrameNumbers,
    const TArray<FPostRenderCameraSample>& Samples,
    int32 FrameRateNumerator,
    int32 FrameRateDenominator,
    const FString& SourceCsvPath,
    const FTimecode& StartTimecode,
    bool bHasStartTimecode)
{
    if (!SampleAsset)
    {
        UE_LOG(LogTemp, Error, TEXT("[BuildHelper] WriteCameraSamples: SampleAsset is null"));
        return false;
    }
    if (FrameNumbers.Num() != Samples.Num())
    {
        UE_LOG(LogTemp, Error,
            TEXT("[BuildHelper] WriteCameraSamples: length mismatch (frames=%d, samples=%d)"),
            FrameNumbers.Num(), Samples.Num());
        return false;
    }
    if (FrameRateNumerator <= 0 || FrameRateDenominator <= 0)
    {
        UE_LOG(LogTemp, Error,
            TEXT("[BuildHelper] WriteCameraSamples: invalid frame rate %d/%d"),
            FrameRateNumerator, FrameRateDenominator);
        return false;
    }
    if (FrameNumbers.Num() == 0)
    {
        UE_LOG(LogTemp, Error,
            TEXT("[BuildHelper] WriteCameraSamples: FrameNumbers empty"));
        return false;
    }
    // ----- Strict-ascending invariant for evaluator's Algo::UpperBound -----
    // csv_parser preserves CSV row order and has no duplicate / out-of-order
    // guard; without this check, a malformed CSV would save a "valid" asset
    // and produce silent render corruption (interpolating between wrong
    // sample indices). Fail-fast with offending index for diagnosis.
    for (int32 i = 1; i < FrameNumbers.Num(); ++i)
    {
        if (FrameNumbers[i] <= FrameNumbers[i - 1])
        {
            UE_LOG(LogTemp, Error,
                TEXT("[BuildHelper] WriteCameraSamples: FrameNumbers must be strictly "
                     "ascending; index %d frame=%d not > index %d frame=%d"),
                i, FrameNumbers[i], i - 1, FrameNumbers[i - 1]);
            return false;
        }
    }

    SampleAsset->Modify();
    SampleAsset->SourceFrameNumbers = FrameNumbers;
    SampleAsset->Samples            = Samples;
    SampleAsset->FrameRateNumerator = FrameRateNumerator;
    SampleAsset->FrameRateDenominator = FrameRateDenominator;
    SampleAsset->SourceCsvPath      = SourceCsvPath;
    // Upgrade serialized schema on every write so v2 assets re-imported
    // after the v3 cutover get bumped. The C++ default initializer
    // (PostRenderCameraSamples.h SchemaVersion = 3) only takes effect for
    // newly-constructed assets; existing serialized assets keep their old
    // value through CreateOrLoadCameraSamplesAsset → Load. Without this
    // explicit set, `run_import` on a v2 asset would leave SchemaVersion=2
    // and the pipeline-side v3 gate (_REQUIRED_DATAASSET_SCHEMA) would
    // permanently reject it. Keep in sync with header default.
    SampleAsset->SchemaVersion      = 3;
    // Canonical SMPTE start timecode (P0 timecode-sync). When the caller
    // signals the timecode is unknown (csv_parser invoked without fps),
    // reset the field to a zeroed FTimecode rather than honoring the
    // stale value the caller passed in.
    if (bHasStartTimecode)
    {
        SampleAsset->StartTimecode = StartTimecode;
    }
    else
    {
        SampleAsset->StartTimecode = FTimecode();
    }
    SampleAsset->bHasStartTimecode = bHasStartTimecode;
    SampleAsset->RecomputeContiguity();
    SampleAsset->MarkPackageDirty();
    return true;
}

UPostRenderCameraSection* UPostRenderToolBuildHelper::EnsurePostRenderCameraTrackOnBinding(
    UMovieSceneSequence* Sequence,
    const FGuid& BindingGuid,
    int32 SectionStartFrame,
    int32 SectionEndFrame)
{
    if (!Sequence) return nullptr;
    UMovieScene* MovieScene = Sequence->GetMovieScene();
    if (!MovieScene) return nullptr;

    // ----- Find or create the track -----
    UPostRenderCameraTrack* Track = nullptr;
    for (UMovieSceneTrack* ExistingTrack : MovieScene->FindTracks(UPostRenderCameraTrack::StaticClass(), BindingGuid))
    {
        Track = Cast<UPostRenderCameraTrack>(ExistingTrack);
        if (Track) break;
    }
    if (!Track)
    {
        Track = MovieScene->AddTrack<UPostRenderCameraTrack>(BindingGuid);
        if (!Track) return nullptr;
    }
    else
    {
        Track->Modify();
        Track->RemoveAllAnimationData();
    }

    // ----- Create the single section -----
    UMovieSceneSection* NewSection = Track->CreateNewSection();
    UPostRenderCameraSection* TypedSection = Cast<UPostRenderCameraSection>(NewSection);
    if (!TypedSection) return nullptr;

    // Convert display-rate frame numbers to tick-resolution range.
    const FFrameRate DisplayRate = MovieScene->GetDisplayRate();
    const FFrameRate TickResolution = MovieScene->GetTickResolution();
    const FFrameNumber StartTicks = FFrameRate::TransformTime(
        FFrameTime(FFrameNumber(SectionStartFrame)), DisplayRate, TickResolution).FrameNumber;
    const FFrameNumber EndTicks = FFrameRate::TransformTime(
        FFrameTime(FFrameNumber(SectionEndFrame)), DisplayRate, TickResolution).FrameNumber;

    TypedSection->SetRange(TRange<FFrameNumber>(StartTicks, EndTicks));
    Track->AddSection(*TypedSection);
    return TypedSection;
}

UPostRenderCameraSamples* UPostRenderToolBuildHelper::CreateOrLoadCameraSamplesAsset(
    const FString& PackagePath,
    const FString& AssetName)
{
    const FString FullPath = PackagePath / AssetName;

    // Try load first (idempotent re-import).
    UObject* Existing = StaticLoadObject(UPostRenderCameraSamples::StaticClass(),
                                        nullptr, *FullPath);
    if (Existing)
    {
        return Cast<UPostRenderCameraSamples>(Existing);
    }

    // Create a new package + DataAsset.
    UPackage* NewPackage = CreatePackage(*FullPath);
    if (!NewPackage)
    {
        UE_LOG(LogTemp, Error, TEXT("[BuildHelper] CreatePackage failed: %s"), *FullPath);
        return nullptr;
    }
    NewPackage->FullyLoad();

    UPostRenderCameraSamples* NewAsset = NewObject<UPostRenderCameraSamples>(
        NewPackage, *AssetName, RF_Public | RF_Standalone | RF_Transactional);
    if (!NewAsset)
    {
        UE_LOG(LogTemp, Error, TEXT("[BuildHelper] NewObject<UPostRenderCameraSamples> failed"));
        return nullptr;
    }
    FAssetRegistryModule::AssetCreated(NewAsset);
    NewAsset->MarkPackageDirty();
    return NewAsset;
}
