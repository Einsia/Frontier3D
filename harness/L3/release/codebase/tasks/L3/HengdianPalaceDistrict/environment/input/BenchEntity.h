#pragma once
#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "BenchEntity.generated.h"

class APawn;

// Identity and semantic state are candidate hints, NOT verified geometry.
// The observer independently reads render components, collisions and movement.
UCLASS(ClassGroup=(Bench), meta=(BlueprintSpawnableComponent))
class BENCHRUNTIME_API UBenchEntity : public UActorComponent {
    GENERATED_BODY()
public:
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bench") FString EntityId;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bench") FString Role;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bench") TMap<FString,FString> SemanticState;
    UFUNCTION(BlueprintNativeEvent, Category="Bench")
    void Interact(APawn* InstigatorPawn, const FString& Action, const FString& Argument);
    virtual void Interact_Implementation(APawn*, const FString&, const FString&) {}
};
