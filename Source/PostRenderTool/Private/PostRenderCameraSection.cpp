// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderCameraSection.h"

UPostRenderCameraSection::UPostRenderCameraSection()
{
    EvalOptions.CompletionMode = EMovieSceneCompletionMode::KeepState;
    bSupportsInfiniteRange = false;
}
