// Copyright VP Post-Render Tool contributors. All Rights Reserved.

using UnrealBuildTool;

public class PostRenderTool : ModuleRules
{
    public PostRenderTool(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(
            new string[]
            {
                "Core",
                "CoreUObject",
                "Engine",
                "UMG",
                "Blutility",
            }
        );

        PrivateDependencyModuleNames.AddRange(
            new string[]
            {
                "Slate",
                "SlateCore",
                "InputCore",
                "UnrealEd",
                "UMGEditor",
                "EditorSubsystem",
                "ToolMenus",
                "PythonScriptPlugin",
            }
        );
    }
}
