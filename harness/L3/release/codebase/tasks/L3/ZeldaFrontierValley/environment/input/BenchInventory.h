#pragma once
#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "BenchInventory.generated.h"

// Public inventory primitive. The evaluator rebuilds this implementation and
// observes its counters; gameplay is responsible for action preconditions.
UCLASS(ClassGroup=(Bench), meta=(BlueprintSpawnableComponent))
class BENCHRUNTIME_API UBenchInventory : public UActorComponent {
    GENERATED_BODY()
public:
    UFUNCTION(BlueprintCallable, Category="Bench") int32 Count(FName Item) const;
    UFUNCTION(BlueprintCallable, Category="Bench") bool Grant(FName Item, int32 Amount=1);
    UFUNCTION(BlueprintCallable, Category="Bench") bool Consume(FName Item, int32 Amount=1);
    const TMap<FName,int32>& ReadCounts() const { return Counts; }
private:
    UPROPERTY() TMap<FName,int32> Counts;
};
