#include "BenchObserver.h"
#include "BenchEntity.h"
#include "BenchInventory.h"
#include "EngineUtils.h"
#include "Engine/World.h"
#include "Engine/GameViewportClient.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/Material.h"
#include "Engine/Texture.h"
#include "Camera/CameraComponent.h"
#include "GameFramework/HUD.h"
#include "StaticMeshResources.h"
#include "Components/StaticMeshComponent.h"
#include "Components/MeshComponent.h"
#include "Components/TextRenderComponent.h"
#include "ProceduralMeshComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/LightComponent.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/Character.h"
#include "Camera/PlayerCameraManager.h"
#include "Camera/CameraActor.h"
#include "Engine/OverlapResult.h"
#include "CollisionQueryParams.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformMisc.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UnrealClient.h"
#include "RenderingThread.h"
#if WITH_EDITOR
#include "AssetCompilingManager.h"
#include "ShaderCompiler.h"
#endif

namespace {
void FinishRenderAssets() {
#if WITH_EDITOR
    FAssetCompilingManager::Get().FinishAllCompilation();
    if(GShaderCompilingManager)GShaderCompilingManager->FinishAllCompilation();
#endif
    FlushRenderingCommands();
}
TArray<TSharedPtr<FJsonValue>> Vec(FVector V) {
    return {MakeShared<FJsonValueNumber>(V.X),MakeShared<FJsonValueNumber>(V.Y),MakeShared<FJsonValueNumber>(V.Z)};
}
FVector ReadVec(const TSharedPtr<FJsonObject>& O, const TCHAR* Key) {
    const auto& A=O->GetArrayField(Key);
    return FVector(A[0]->AsNumber(),A[1]->AsNumber(),A[2]->AsNumber());
}
FString Str(const TSharedPtr<FJsonObject>& O,const TCHAR* K,const FString& D=TEXT("")) {
    FString S; return O->TryGetStringField(K,S)?S:D;
}
double Num(const TSharedPtr<FJsonObject>& O,const TCHAR* K,double D=0) {
    double N; return O->TryGetNumberField(K,N)?N:D;
}
UBenchEntity* Find(UWorld* W,const FString& Id) {
    for(TActorIterator<AActor> It(W);It;++It) {
        auto E=It->FindComponentByClass<UBenchEntity>();
        if(E && E->EntityId==Id)return E;
    } return nullptr;
}
FString Identity(AActor* A) {
    if(!A)return TEXT(""); auto E=A->FindComponentByClass<UBenchEntity>();
    return E?E->EntityId:A->GetName();
}
}
bool UBenchObserver::DoesSupportWorldType(EWorldType::Type T) const {
    return T==EWorldType::Game || T==EWorldType::PIE;
}
TStatId UBenchObserver::GetStatId() const { RETURN_QUICK_DECLARE_CYCLE_STAT(UBenchObserver,STATGROUP_Tickables); }
void UBenchObserver::Save(const FString& Name,const TSharedPtr<FJsonObject>& V) {
    FString Text; auto Writer=TJsonWriterFactory<>::Create(&Text);
    FJsonSerializer::Serialize(V.ToSharedRef(),Writer);
    FFileHelper::SaveStringToFile(Text,*(Output/(Name+TEXT(".json"))));
}
void UBenchObserver::Start() {
    FString Plan;
    if(!FParse::Value(FCommandLine::Get(),TEXT("BenchPlan="),Plan)) {Finished=true;return;}
    if(!FParse::Value(FCommandLine::Get(),TEXT("BenchOutput="),Output)){Finished=true;return;}
    IFileManager::Get().MakeDirectory(*Output,true);
    FString Text; TSharedPtr<FJsonObject> Root;
    if(!FFileHelper::LoadFileToString(Text,*Plan) ||
       !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Root) || !Root.IsValid()) {
        auto Error=MakeShared<FJsonObject>();Error->SetStringField(TEXT("error"),TEXT("invalid_plan"));Save(TEXT("error"),Error);
        Finished=true;FPlatformMisc::RequestExit(false);return;
    }
    FinishRenderAssets();
    Steps=Root->GetArrayField(TEXT("steps"));
    Snapshot(TEXT("initial"));
}
void UBenchObserver::Snapshot(const FString& Name) {
    auto Root=MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("protocol"),TEXT("ue5-observer-v1"));
    Root->SetNumberField(TEXT("time"),GetWorld()->GetTimeSeconds());
    Root->SetNumberField(TEXT("tick"),TickIndex);
    Root->SetStringField(TEXT("active_step"),Active.IsValid()?Str(Active,TEXT("name")):TEXT("startup"));
    TArray<TSharedPtr<FJsonValue>> Entities;
    for(TActorIterator<AActor> It(GetWorld());It;++It) {
        auto E=It->FindComponentByClass<UBenchEntity>();if(!E)continue;
        auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("id"),E->EntityId);J->SetStringField(TEXT("role"),E->Role);
        J->SetArrayField(TEXT("position_cm"),Vec(It->GetActorLocation()));
        J->SetArrayField(TEXT("rotation_deg"),Vec(It->GetActorRotation().Euler()));
        auto State=MakeShared<FJsonObject>();for(const auto& P:E->SemanticState)State->SetStringField(P.Key,P.Value);
        J->SetObjectField(TEXT("candidate_state"),State);
        TArray<UPrimitiveComponent*> Parts;It->GetComponents<UPrimitiveComponent>(Parts);
        TArray<TSharedPtr<FJsonValue>> Components;
        for(auto C:Parts) {
            if(!C->IsRegistered())continue;
            auto P=MakeShared<FJsonObject>();P->SetStringField(TEXT("name"),C->GetName());
            P->SetArrayField(TEXT("position_cm"),Vec(C->GetComponentLocation()));
            P->SetArrayField(TEXT("rotation_deg"),Vec(C->GetComponentRotation().Euler()));
            const FTransform CT=C->GetComponentTransform();
            P->SetArrayField(TEXT("axis_x"),Vec(CT.TransformVector(FVector(1,0,0))));
            P->SetArrayField(TEXT("axis_y"),Vec(CT.TransformVector(FVector(0,1,0))));
            P->SetArrayField(TEXT("axis_z"),Vec(CT.TransformVector(FVector(0,0,1))));
            P->SetArrayField(TEXT("bounds_center_cm"),Vec(C->Bounds.Origin));
            P->SetArrayField(TEXT("bounds_extent_cm"),Vec(C->Bounds.BoxExtent));
            P->SetBoolField(TEXT("visible"),C->IsVisible() && !It->IsHidden());
            P->SetBoolField(TEXT("collision"),C->IsCollisionEnabled());
            P->SetBoolField(TEXT("blocks_pawn"),C->GetCollisionResponseToChannel(ECC_Pawn)==ECR_Block);
            P->SetBoolField(TEXT("simulating"),C->IsSimulatingPhysics());
            P->SetArrayField(TEXT("velocity_cm_s"),Vec(C->GetComponentVelocity()));
            if(auto M=Cast<UStaticMeshComponent>(C)) {
                P->SetStringField(TEXT("mesh"),M->GetStaticMesh()?M->GetStaticMesh()->GetPathName():TEXT(""));
                P->SetNumberField(TEXT("instances"),Cast<UInstancedStaticMeshComponent>(M)?Cast<UInstancedStaticMeshComponent>(M)->GetInstanceCount():1);
            }
            if((E->Role==TEXT("door") || E->Role==TEXT("gate") || E->Role==TEXT("chest")) && C->IsCollisionEnabled()) {
                TArray<FOverlapResult> Overlaps; FComponentQueryParams Params(SCENE_QUERY_STAT(BenchContact),It.operator*());
                C->ComponentOverlapMulti(Overlaps,GetWorld(),C->GetComponentLocation(),C->GetComponentQuat(),ECC_Pawn,Params,FCollisionObjectQueryParams::DefaultObjectQueryParam);
                TArray<TSharedPtr<FJsonValue>> Contacts;
                for(const auto& O:Overlaps)if(O.bBlockingHit && O.GetActor()!=It.operator*()) {
                    auto Contact=MakeShared<FJsonObject>();Contact->SetStringField(TEXT("actor"),Identity(O.GetActor()));
                    Contact->SetStringField(TEXT("component"),O.GetComponent()?O.GetComponent()->GetName():TEXT(""));
                    Contacts.Add(MakeShared<FJsonValueObject>(Contact));
                }
                P->SetArrayField(TEXT("blocking_contacts"),Contacts);
            }
            Components.Add(MakeShared<FJsonValueObject>(P));
        }
        TArray<ULightComponent*> Lights;It->GetComponents<ULightComponent>(Lights);
        TArray<TSharedPtr<FJsonValue>> LightData;
        for(auto L:Lights) {auto V=MakeShared<FJsonObject>();V->SetStringField(TEXT("name"),L->GetName());
            V->SetNumberField(TEXT("intensity"),L->Intensity);V->SetBoolField(TEXT("visible"),L->IsVisible());LightData.Add(MakeShared<FJsonValueObject>(V));}
        J->SetArrayField(TEXT("lights"),LightData);
        J->SetArrayField(TEXT("components"),Components);Entities.Add(MakeShared<FJsonValueObject>(J));
    }
    Root->SetArrayField(TEXT("entities"),Entities);
    TArray<TSharedPtr<FJsonValue>> Inventories;
    for(TActorIterator<AActor> It(GetWorld());It;++It) {
        if(auto Inv=It->FindComponentByClass<UBenchInventory>()) {
            auto Entry=MakeShared<FJsonObject>();Entry->SetStringField(TEXT("actor"),Identity(It.operator*()));
            auto Counts=MakeShared<FJsonObject>();
            for(const auto& Pair:Inv->ReadCounts())Counts->SetNumberField(Pair.Key.ToString(),Pair.Value);
            Entry->SetObjectField(TEXT("counts"),Counts);Inventories.Add(MakeShared<FJsonValueObject>(Entry));
        }
    }
    Root->SetArrayField(TEXT("trusted_inventory"),Inventories);
    auto PC=GetWorld()->GetFirstPlayerController();
    if(PC && PC->GetPawn()) {
        Root->SetArrayField(TEXT("pawn_position_cm"),Vec(PC->GetPawn()->GetActorLocation()));
        Root->SetArrayField(TEXT("pawn_velocity_cm_s"),Vec(PC->GetPawn()->GetVelocity()));
    }
    if(PC) {
        FVector Position;FRotator Rotation;PC->GetPlayerViewPoint(Position,Rotation);
        auto Camera=MakeShared<FJsonObject>();Camera->SetArrayField(TEXT("position_cm"),Vec(Position));
        Camera->SetArrayField(TEXT("rotation_deg"),Vec(Rotation.Euler()));
        if(PC->PlayerCameraManager)Camera->SetNumberField(TEXT("horizontal_fov_deg"),PC->PlayerCameraManager->GetFOVAngle());
        Root->SetObjectField(TEXT("camera"),Camera);
    }
    Save(Name,Root);
}
void UBenchObserver::ExportGeometry(const FString& Name) {
    auto Root=MakeShared<FJsonObject>();
    auto Meshes=MakeShared<FJsonObject>();
    auto MaterialCatalog=MakeShared<FJsonObject>();
    TArray<TSharedPtr<FJsonValue>> Instances;
    TArray<TSharedPtr<FJsonValue>> Unsupported;
    for(TActorIterator<AActor> It(GetWorld());It;++It) {
        if(!Cast<APawn>(It.operator*())) {
            TArray<UPrimitiveComponent*> All;It->GetComponents<UPrimitiveComponent>(All);
            for(auto C:All)if(C->IsRegistered() && !Cast<UStaticMeshComponent>(C) && !Cast<UProceduralMeshComponent>(C) &&
                ((C->IsVisible() && !C->bHiddenInGame && !It->IsHidden()) || C->IsCollisionEnabled())) {
                auto Entry=MakeShared<FJsonObject>();Entry->SetStringField(TEXT("actor"),Identity(It.operator*()));
                Entry->SetStringField(TEXT("component"),C->GetName());Entry->SetStringField(TEXT("class"),C->GetClass()->GetName());
                Unsupported.Add(MakeShared<FJsonValueObject>(Entry));
            }
        }
        TArray<UProceduralMeshComponent*> ProceduralParts;It->GetComponents<UProceduralMeshComponent>(ProceduralParts);
        for(auto C:ProceduralParts) {
            const bool Visible=C->IsVisible() && !C->bHiddenInGame && !It->IsHidden();
            if(!C->IsRegistered() || (!Visible && !C->IsCollisionEnabled()))continue;
            for(int32 SectionIndex=0;SectionIndex<C->GetNumSections();++SectionIndex) {
                auto Section=C->GetProcMeshSection(SectionIndex);
                if(!Section || Section->ProcVertexBuffer.Num()==0 || Section->ProcIndexBuffer.Num()==0)continue;
                const FString Key=C->GetPathName()+TEXT("::section_")+FString::FromInt(SectionIndex);
                auto M=MakeShared<FJsonObject>();TArray<TSharedPtr<FJsonValue>> Verts,Indices;
                for(const auto& V:Section->ProcVertexBuffer)Verts.Add(MakeShared<FJsonValueArray>(Vec(V.Position)));
                for(const auto I:Section->ProcIndexBuffer)Indices.Add(MakeShared<FJsonValueNumber>(I));
                M->SetArrayField(TEXT("vertices_cm"),Verts);M->SetArrayField(TEXT("indices"),Indices);Meshes->SetObjectField(Key,M);
                FTransform T=C->GetComponentTransform();auto J=MakeShared<FJsonObject>();
                J->SetStringField(TEXT("actor"),Identity(It.operator*()));J->SetStringField(TEXT("component"),C->GetName());
                J->SetNumberField(TEXT("instance"),SectionIndex);J->SetStringField(TEXT("mesh"),Key);
                J->SetBoolField(TEXT("visible"),Visible && Section->bSectionVisible);
                J->SetBoolField(TEXT("collision_enabled"),C->IsCollisionEnabled() && Section->bEnableCollision);
                J->SetNumberField(TEXT("collision_enabled_mode"),int(C->GetCollisionEnabled()));
                if(auto Entity=It->FindComponentByClass<UBenchEntity>())J->SetStringField(TEXT("role"),Entity->Role);
                TArray<TSharedPtr<FJsonValue>> Materials;auto Material=C->GetMaterial(SectionIndex);
                Materials.Add(MakeShared<FJsonValueString>(Material?Material->GetPathName():TEXT("")));
                J->SetArrayField(TEXT("materials"),Materials);
                J->SetArrayField(TEXT("origin_cm"),Vec(T.GetTranslation()));
                J->SetArrayField(TEXT("axis_x"),Vec(T.TransformVector(FVector(1,0,0))));
                J->SetArrayField(TEXT("axis_y"),Vec(T.TransformVector(FVector(0,1,0))));
                J->SetArrayField(TEXT("axis_z"),Vec(T.TransformVector(FVector(0,0,1))));
                J->SetBoolField(TEXT("blocks_pawn"),C->IsCollisionEnabled() && Section->bEnableCollision && C->GetCollisionResponseToChannel(ECC_Pawn)==ECR_Block);
                Instances.Add(MakeShared<FJsonValueObject>(J));
            }
        }
        TArray<UStaticMeshComponent*> Parts;It->GetComponents<UStaticMeshComponent>(Parts);
        for(auto C:Parts) {
            auto Mesh=C->GetStaticMesh();
            const bool Visible=C->IsVisible() && !C->bHiddenInGame && !It->IsHidden();
            if(!C->IsRegistered() || (!Visible && !C->IsCollisionEnabled()) || !Mesh)continue;
            auto Data=Mesh->GetRenderData();if(!Data || Data->LODResources.Num()==0)continue;
            const FString Key=Mesh->GetPathName();
            const auto& LOD=Data->LODResources[0];
            if(!Meshes->HasField(Key)) {
                auto M=MakeShared<FJsonObject>();TArray<TSharedPtr<FJsonValue>> Verts,Indices;
                for(uint32 V=0;V<LOD.VertexBuffers.PositionVertexBuffer.GetNumVertices();++V)
                    Verts.Add(MakeShared<FJsonValueArray>(Vec(FVector(LOD.VertexBuffers.PositionVertexBuffer.VertexPosition(V)))));
                for(int32 I=0;I<LOD.IndexBuffer.GetNumIndices();++I)
                    Indices.Add(MakeShared<FJsonValueNumber>(LOD.IndexBuffer.GetIndex(I)));
                M->SetArrayField(TEXT("vertices_cm"),Verts);M->SetArrayField(TEXT("indices"),Indices);
                Meshes->SetObjectField(Key,M);
            }
            auto Instanced=Cast<UInstancedStaticMeshComponent>(C);
            const int32 Count=Instanced?Instanced->GetInstanceCount():1;
            for(int32 I=0;I<Count;++I) {
                FTransform T=C->GetComponentTransform();
                if(Instanced && !Instanced->GetInstanceTransform(I,T,true))continue;
                auto J=MakeShared<FJsonObject>();
                J->SetStringField(TEXT("actor"),Identity(It.operator*()));
                J->SetStringField(TEXT("component"),C->GetName());J->SetNumberField(TEXT("instance"),I);
                J->SetStringField(TEXT("mesh"),Key);
                J->SetBoolField(TEXT("visible"),Visible);
                J->SetBoolField(TEXT("collision_enabled"),C->IsCollisionEnabled());
                J->SetNumberField(TEXT("collision_enabled_mode"),int(C->GetCollisionEnabled()));
                if(auto Entity=It->FindComponentByClass<UBenchEntity>())J->SetStringField(TEXT("role"),Entity->Role);
                TArray<TSharedPtr<FJsonValue>> Materials;
                for(int32 Slot=0;Slot<C->GetNumMaterials();++Slot) {
                    auto Material=C->GetMaterial(Slot);
                    Materials.Add(MakeShared<FJsonValueString>(Material?Material->GetPathName():TEXT("")));
                    if(Material && !MaterialCatalog->HasField(Material->GetPathName())) {
                        auto Evidence=MakeShared<FJsonObject>();
                        auto BaseMaterial=Material->GetBaseMaterial();
                        Evidence->SetStringField(TEXT("base_material"),BaseMaterial?BaseMaterial->GetPathName():TEXT(""));
                        TArray<UTexture*> Textures;Material->GetUsedTextures(Textures);
                        TArray<TSharedPtr<FJsonValue>> Paths;
                        for(auto Texture:Textures)if(Texture)Paths.Add(MakeShared<FJsonValueString>(Texture->GetPathName()));
                        Evidence->SetArrayField(TEXT("texture_assets"),Paths);
                        MaterialCatalog->SetObjectField(Material->GetPathName(),Evidence);
                    }
                }
                J->SetArrayField(TEXT("materials"),Materials);
                J->SetArrayField(TEXT("origin_cm"),Vec(T.GetTranslation()));
                J->SetArrayField(TEXT("axis_x"),Vec(T.TransformVector(FVector(1,0,0))));
                J->SetArrayField(TEXT("axis_y"),Vec(T.TransformVector(FVector(0,1,0))));
                J->SetArrayField(TEXT("axis_z"),Vec(T.TransformVector(FVector(0,0,1))));
                J->SetBoolField(TEXT("blocks_pawn"),C->IsCollisionEnabled() && C->GetCollisionResponseToChannel(ECC_Pawn)==ECR_Block);
                Instances.Add(MakeShared<FJsonValueObject>(J));
            }
        }
    }
    Root->SetStringField(TEXT("protocol"),TEXT("ue5-full-mesh-v1"));Root->SetStringField(TEXT("unit"),TEXT("cm"));
    Root->SetObjectField(TEXT("meshes"),Meshes);Root->SetArrayField(TEXT("instances"),Instances);
    Root->SetObjectField(TEXT("material_catalog"),MaterialCatalog);
    Root->SetArrayField(TEXT("unexported_components"),Unsupported);Save(Name,Root);
}
void UBenchObserver::Execute(const TSharedPtr<FJsonObject>& S) {
    const FString Op=Str(S,TEXT("op")), Name=Str(S,TEXT("name"),FString::Printf(TEXT("step_%04d"),Index));
    auto PC=GetWorld()->GetFirstPlayerController();auto Pawn=PC?PC->GetPawn():nullptr;
    auto Result=MakeShared<FJsonObject>();Result->SetStringField(TEXT("op"),Op);Result->SetBoolField(TEXT("accepted"),false);
    if(Op==TEXT("snapshot")) {Snapshot(Name);return;}
    if(Op==TEXT("export_geometry")) {ExportGeometry(Name);return;}
    if(Op==TEXT("instance_masks")) {
        auto Master=LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/L3Verifier/M_InstanceMask.M_InstanceMask"));
        if(!Master) {Result->SetStringField(TEXT("error"),TEXT("missing_trusted_mask_material"));Save(Name+TEXT("_event"),Result);return;}
        TMap<FString,FLinearColor> Colors;
        for(auto Value:S->GetArrayField(TEXT("groups"))) {
            const auto Group=Value->AsObject();const auto RGB=ReadVec(Group,TEXT("rgb"));
            const FLinearColor Color(FColor(uint8(RGB.X),uint8(RGB.Y),uint8(RGB.Z)));
            for(auto Actor:Group->GetArrayField(TEXT("actors")))Colors.Add(Actor->AsString(),Color);
        }
        TArray<TSharedPtr<FJsonValue>> NonOpaque, ExcludedTextOverlays;
        for(TActorIterator<AActor> It(GetWorld());It;++It) {
            // World-space annotation glyphs are not instance geometry. Hide
            // them only for the ID pass; the preceding RGB render retains them.
            TArray<UTextRenderComponent*> TextOverlays;It->GetComponents<UTextRenderComponent>(TextOverlays);
            for(auto Text:TextOverlays) {
                if(Text->IsVisible()) {
                    ExcludedTextOverlays.Add(MakeShared<FJsonValueString>(Identity(It.operator*())+TEXT("/")+Text->GetName()));
                    Text->SetVisibility(false);
                }
            }
            TArray<UMeshComponent*> Parts;It->GetComponents<UMeshComponent>(Parts);
            for(auto C:Parts) {
                const FLinearColor* Color=Colors.Find(Identity(It.operator*()));
                auto Material=UMaterialInstanceDynamic::Create(Master,C);
                Material->SetVectorParameterValue(TEXT("IdColor"),Color?*Color:FLinearColor::Black);
                for(int32 Slot=0;Slot<C->GetNumMaterials();++Slot) {
                    if(C->GetMaterial(Slot) && C->GetMaterial(Slot)->GetBlendMode()!=BLEND_Opaque)
                        NonOpaque.Add(MakeShared<FJsonValueString>(Identity(It.operator*())+TEXT("/")+C->GetName()));
                    C->SetMaterial(Slot,Material);
                }
            }
        }
        if(PC) {
            if(PC->GetHUD())PC->GetHUD()->bShowHUD=false;
            for(const TCHAR* Command:{TEXT("r.EyeAdaptation.PreExposureOverride 1"),TEXT("ShowFlag.EyeAdaptation 0"),TEXT("ShowFlag.Tonemapper 0"),TEXT("ShowFlag.Fog 0"),TEXT("ShowFlag.Atmosphere 0"),TEXT("r.AntiAliasingMethod 0"),TEXT("r.ScreenPercentage 100")})PC->ConsoleCommand(Command,false);
        }
        Result->SetNumberField(TEXT("mask_pre_exposure_override"),1.0);
        Result->SetBoolField(TEXT("mask_eye_adaptation_disabled"),true);
        Result->SetArrayField(TEXT("nonopaque_components"),NonOpaque);
        Result->SetArrayField(TEXT("excluded_text_overlays"),ExcludedTextOverlays);
        Result->SetBoolField(TEXT("accepted"),true);Save(Name+TEXT("_event"),Result);return;
    }
    if(Op==TEXT("ray")) {
        FHitResult Hit;FCollisionQueryParams Params(SCENE_QUERY_STAT(BenchSurfaceRay),true,Pawn);
        const bool Contact=GetWorld()->LineTraceSingleByChannel(Hit,ReadVec(S,TEXT("from_cm")),ReadVec(S,TEXT("to_cm")),ECC_Visibility,Params);
        Result->SetBoolField(TEXT("blocked"),Contact);Result->SetStringField(TEXT("hit"),Identity(Hit.GetActor()));
        if(Contact) {Result->SetArrayField(TEXT("point_cm"),Vec(Hit.ImpactPoint));Result->SetArrayField(TEXT("normal"),Vec(Hit.ImpactNormal));}
        Result->SetBoolField(TEXT("accepted"),true);Save(Name+TEXT("_event"),Result);return;
    }
    if(Op==TEXT("inspect")) {
        auto E=Find(GetWorld(),Str(S,TEXT("target")));
        if(E && PC) {
            FVector Centre,Extent;E->GetOwner()->GetActorBounds(false,Centre,Extent);
            auto Camera=GetWorld()->SpawnActor<ACameraActor>();
            if(Str(S,TEXT("view"))==TEXT("exterior")) {
                FVector Position=Centre+FVector(-FMath::Max(Extent.X,200.)*2.,-FMath::Max(Extent.Y,200.)*2.,FMath::Max(Extent.Z,200.)*1.5);
                Camera->SetActorLocation(Position);Camera->SetActorRotation((Centre-Position).Rotation());
            } else {
                Camera->SetActorLocation(FVector(Centre.X,Centre.Y,Centre.Z-Extent.Z+160.));
                Camera->SetActorRotation(FRotator(-15,Num(S,TEXT("yaw")),0));
            }
            Result->SetArrayField(TEXT("camera_position_cm"),Vec(Camera->GetActorLocation()));
            Result->SetNumberField(TEXT("camera_pitch_degrees"),Camera->GetActorRotation().Pitch);
            Result->SetNumberField(TEXT("camera_yaw_degrees"),Camera->GetActorRotation().Yaw);
            PC->SetViewTarget(Camera);Remaining=0.5;Result->SetBoolField(TEXT("accepted"),true);
        }
    } else if(Op==TEXT("camera")) {
        auto Camera=GetWorld()->SpawnActor<ACameraActor>();
        Camera->SetActorLocation(ReadVec(S,TEXT("position_cm")));
        Camera->SetActorRotation((ReadVec(S,TEXT("target_cm"))-Camera->GetActorLocation()).Rotation());
        Camera->GetCameraComponent()->SetFieldOfView(Num(S,TEXT("horizontal_fov_deg"),90));
        if(PC && PC->GetHUD())PC->GetHUD()->bShowHUD=false;
        if(PC)PC->SetViewTarget(Camera);Remaining=0.5;Result->SetBoolField(TEXT("accepted"),PC!=nullptr);
    } else if(Op==TEXT("capture")) {
        const double AssetWaitStart=FPlatformTime::Seconds();
        FinishRenderAssets();
        Result->SetNumberField(TEXT("asset_readiness_wait_seconds"),FPlatformTime::Seconds()-AssetWaitStart);
        FScreenshotRequest::RequestScreenshot(Output/(Name+TEXT(".png")),false,false);
        Remaining=0.25;Result->SetBoolField(TEXT("accepted"),true);
    } else if(Op==TEXT("fixture") && Pawn && Str(S,TEXT("purpose"))==TEXT("local_test_setup")) {
        Pawn->SetActorLocation(ReadVec(S,TEXT("position_cm")),false,nullptr,ETeleportType::TeleportPhysics);
        Pawn->SetActorRotation(FRotator::ZeroRotator);PC->SetViewTarget(Pawn);Result->SetBoolField(TEXT("accepted"),true);
    } else if(Op==TEXT("look") && PC && Pawn) {
        FVector Origin;FRotator Rotation;PC->GetPlayerViewPoint(Origin,Rotation);
        PC->SetControlRotation((ReadVec(S,TEXT("target_cm"))-Origin).Rotation());Result->SetBoolField(TEXT("accepted"),true);
    } else if(Op==TEXT("look_entity") && Pawn && PC) {
        auto E=Find(GetWorld(),Str(S,TEXT("target")));
        if(E) {FVector Origin;FRotator Rotation;PC->GetPlayerViewPoint(Origin,Rotation);
            FVector Centre,Extent;E->GetOwner()->GetActorBounds(false,Centre,Extent);
            PC->SetControlRotation((Centre-Origin).Rotation());Result->SetBoolField(TEXT("accepted"),true);}
    } else if(Op==TEXT("interact") && Pawn && PC) {
        auto E=Find(GetWorld(),Str(S,TEXT("target")));FVector Origin;FRotator Rotation;PC->GetPlayerViewPoint(Origin,Rotation);
        FHitResult Hit;FCollisionQueryParams Params(SCENE_QUERY_STAT(BenchInteraction),true,Pawn);
        const bool Contact=GetWorld()->LineTraceSingleByChannel(Hit,Origin,Origin+Rotation.Vector()*300.,ECC_Visibility,Params);
        Result->SetStringField(TEXT("hit"),Identity(Hit.GetActor()));
        if(Contact && E && Hit.GetActor()==E->GetOwner()) {
            E->Interact(Pawn,Str(S,TEXT("action"),TEXT("use")),Str(S,TEXT("argument")));
            Result->SetBoolField(TEXT("accepted"),true);
        }
    } else if(Op==TEXT("invoke") && Pawn) {
        // Negative test: bypass the observer guard so the candidate must reject
        // an invalid caller position inside its own gameplay interaction path.
        auto E=Find(GetWorld(),Str(S,TEXT("target")));
        Result->SetBoolField(TEXT("dispatched"),E!=nullptr);
        if(E)E->Interact(Pawn,Str(S,TEXT("action"),TEXT("use")),Str(S,TEXT("argument")));
    } else if(Op==TEXT("probe")) {
        FHitResult Hit;FCollisionQueryParams Params(SCENE_QUERY_STAT(BenchProbe),false,Pawn);
        bool Blocked=GetWorld()->SweepSingleByChannel(Hit,ReadVec(S,TEXT("from_cm")),ReadVec(S,TEXT("to_cm")),
            FQuat::Identity,ECC_Pawn,FCollisionShape::MakeCapsule(30,85),Params);
        Result->SetBoolField(TEXT("blocked"),Blocked);Result->SetStringField(TEXT("hit"),Identity(Hit.GetActor()));
        Result->SetBoolField(TEXT("accepted"),true);
    } else if(Op==TEXT("move") || Op==TEXT("wait") || Op==TEXT("walk_to")) {
        Remaining=FMath::Clamp(Num(S,TEXT("seconds"),0.5),0.,30.);Result->SetBoolField(TEXT("accepted"),true);
    }
    Save(Name+TEXT("_event"),Result);
}
void UBenchObserver::Tick(float Dt) {
    if(Finished)return;Age+=Dt;++TickIndex;
    if(!Started) {if(Age<1.)return;Started=true;Start();if(Finished)return;}
    if(Remaining>0 && Active.IsValid()) {
        if(Str(Active,TEXT("op"))==TEXT("walk_to")) {
            auto PC=GetWorld()->GetFirstPlayerController();auto P=PC?PC->GetPawn():nullptr;
            if(P) {FVector Delta=ReadVec(Active,TEXT("target_cm"))-P->GetActorLocation();Delta.Z=0;
                if(Delta.Size()<25)Remaining=0;else P->AddMovementInput(Delta.GetSafeNormal(),1.0);}
        }
        if(Str(Active,TEXT("op"))==TEXT("move")) {
            auto PC=GetWorld()->GetFirstPlayerController();auto P=PC?PC->GetPawn():nullptr;
            if(P)P->AddMovementInput(ReadVec(Active,TEXT("direction")).GetSafeNormal(),1.0);
        }
        Remaining-=Dt;
        if(TickIndex%2==0)Snapshot(FString::Printf(TEXT("trajectory_%05d"),SampleIndex++));
        return;
    }
    if(Index>=Steps.Num()) {
        Snapshot(TEXT("final"));auto Done=MakeShared<FJsonObject>();Done->SetNumberField(TEXT("steps"),Index);
        Done->SetBoolField(TEXT("completed"),true);Save(TEXT("completed"),Done);
        Finished=true;FPlatformMisc::RequestExit(false);return;
    }
    Active=Steps[Index++]->AsObject();Execute(Active);
}
