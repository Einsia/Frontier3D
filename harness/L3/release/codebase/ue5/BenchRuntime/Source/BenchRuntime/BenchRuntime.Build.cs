using UnrealBuildTool;
public class BenchRuntime : ModuleRules {
    public BenchRuntime(ReadOnlyTargetRules Target) : base(Target) {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "Json" });
        PrivateDependencyModuleNames.AddRange(new string[] { "InputCore", "RenderCore", "RHI", "ProceduralMeshComponent" });
    }
}
