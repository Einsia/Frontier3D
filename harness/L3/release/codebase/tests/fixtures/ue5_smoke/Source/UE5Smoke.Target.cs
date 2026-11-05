using UnrealBuildTool;
using System.Collections.Generic;

public class UE5SmokeTarget : TargetRules
{
    public UE5SmokeTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.V7;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.Add("UE5Smoke");
    }
}
