// Evaluator-owned instrumentation for the frozen PlainsVillage pilot only.
// Read gameplay counters directly, never the candidate's SemanticState or HUD.
// Copy into an instrumented project; do not include in a generation workspace.
#include "Village.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/FileHelper.h"
#include "HAL/FileManager.h"

namespace {
void RecordPilotInventory(UWorld* World, ELevelTick TickType, float DeltaSeconds) {
    if(!World || !World->IsGameWorld())return;
    auto PC=World->GetFirstPlayerController();
    auto Player=PC?Cast<AVillageCharacter>(PC->GetPawn()):nullptr;
    if(!Player)return;
    FString Output;if(!FParse::Value(FCommandLine::Get(),TEXT("BenchOutput="),Output))return;
    static FString Last;
    const FString State=FString::Printf(TEXT("%d,%d,%d,%d"),Player->Seeds,Player->Crops,Player->Processed,Player->Tools);
    if(State==Last)return;Last=State;
    // Fixed schema and numeric fields avoid adding dependencies to candidate Build.cs.
    const FString Text=FString::Printf(TEXT("{\"source\":\"direct_gameplay_fields\",\"time\":%.9f,\"seeds\":%d,\"crops\":%d,\"processed\":%d,\"tools\":%d}\n"),
        World->GetTimeSeconds(),Player->Seeds,Player->Crops,Player->Processed,Player->Tools);
    IFileManager::Get().MakeDirectory(*Output,true);
    FFileHelper::SaveStringToFile(Text,*(Output/TEXT("inventory-audit.jsonl")),
        FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append);
}
struct FPilotInventoryRegistration {
    FDelegateHandle Handle;
    FPilotInventoryRegistration(){Handle=FWorldDelegates::OnWorldTickEnd.AddStatic(&RecordPilotInventory);}
    ~FPilotInventoryRegistration(){FWorldDelegates::OnWorldTickEnd.Remove(Handle);}
};
FPilotInventoryRegistration Registration;
}
