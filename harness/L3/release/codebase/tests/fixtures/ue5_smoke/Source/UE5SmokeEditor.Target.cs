using UnrealBuildTool;
using System.Collections.Generic;

public class UE5SmokeEditorTarget : TargetRules
{
    public UE5SmokeEditorTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.V7;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.Add("UE5Smoke");
    }
}
