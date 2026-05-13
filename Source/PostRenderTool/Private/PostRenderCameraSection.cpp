// Copyright VP Post-Render Tool contributors. All Rights Reserved.

#include "PostRenderCameraSection.h"

UPostRenderCameraSection::UPostRenderCameraSection()
{
    EvalOptions.EnableSize = true;
    EvalOptions.CompletionMode = EMovieSceneCompletionMode::KeepState;
    bSupportsInfiniteRange = false;
}
