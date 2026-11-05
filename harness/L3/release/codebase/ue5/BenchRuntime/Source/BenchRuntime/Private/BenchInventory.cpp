#include "BenchInventory.h"

int32 UBenchInventory::Count(FName Item) const {
    const int32* Value=Counts.Find(Item); return Value?*Value:0;
}
bool UBenchInventory::Grant(FName Item,int32 Amount) {
    if(Item.IsNone() || Amount<=0 || Amount>1000000 || Count(Item)>1000000-Amount)return false;
    Counts.FindOrAdd(Item)+=Amount; return true;
}
bool UBenchInventory::Consume(FName Item,int32 Amount) {
    if(Item.IsNone() || Amount<=0 || Count(Item)<Amount)return false;
    Counts.FindOrAdd(Item)-=Amount; return true;
}
