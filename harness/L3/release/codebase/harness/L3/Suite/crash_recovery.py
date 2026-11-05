"""Attribute candidate assertion failures without inventing post-crash observations."""
import json
from .policy import read
from harness.L3.MinecraftVillage.protocol import digest

def crashing_invoke(episode,plan):
    log=episode/"editor.log"
    text=log.read_text(errors="replace") if log.exists() else ""
    if "Assertion failed:" not in text or "libUnrealEditor-L3Environment.so!" not in text:
        return None
    names=[step.get("name") for step in plan["steps"]]
    if None in names or len(names)!=len(set(names)):return None
    for step in plan["steps"]:
        name=step.get("name")
        if not name:return None
        suffix=".json" if step["op"] in {"snapshot","export_geometry"} else "_event.json"
        if not (episode/(name+suffix)).exists():
            if step["op"] not in {"invoke","interact"}:return None
            return dict(step)
    return None

def checked_crashes(folder):
    p=folder/"crash-probes.json"
    if not p.exists():return {}
    data=read(p)
    if data["source_sha256"]!=read(folder/"source.json")["source_sha256"]:
        raise ValueError("Crash evidence belongs to a different candidate")
    if "original_plan_sha256" in data:
        original=folder/"workspace/plans/local-original.json"
        if digest(original)!=data["original_plan_sha256"]:raise ValueError("Original probe plan changed")
        expected=[step for step in read(original)["steps"] if step.get("name") not in data["probes"]]
        if read(folder/"workspace/plans/local.json")["steps"]!=expected:
            raise ValueError("Local replay omitted unaccounted probes")
    for row in data["probes"].values():
        log=folder/row["log"]
        if not log.resolve().is_relative_to(folder.resolve()) or digest(log)!=row["log_sha256"]:
            raise ValueError("Crash log provenance mismatch")
    return data["probes"]
