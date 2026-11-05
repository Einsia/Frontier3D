#pragma once
#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "Dom/JsonObject.h"
#include "BenchObserver.generated.h"

UCLASS()
class BENCHRUNTIME_API UBenchObserver : public UTickableWorldSubsystem {
    GENERATED_BODY()
public:
    virtual bool DoesSupportWorldType(EWorldType::Type Type) const override;
    virtual TStatId GetStatId() const override;
    virtual void Tick(float DeltaTime) override;
private:
    bool Started=false, Finished=false;
    int32 Index=0, TickIndex=0, SampleIndex=0;
    double Age=0, Remaining=0;
    FString Output;
    TArray<TSharedPtr<FJsonValue>> Steps;
    TSharedPtr<FJsonObject> Active;
    void Start();
    void Execute(const TSharedPtr<FJsonObject>& Step);
    void Snapshot(const FString& Name);
    void Save(const FString& Name, const TSharedPtr<FJsonObject>& Value);
};
