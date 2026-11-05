"""Read exact submitted location hints without modifying frozen submissions.

Only representation aliases are accepted. Missing/ambiguous coordinates are
recorded and never synthesized; physical observations remain the evidence.
"""
import copy
import math

VERSION = "exact-binding-hints-v2"

def vector3(value):
    return (isinstance(value, list) and len(value) == 3 and
            all(type(x) in (int, float) and math.isfinite(x) for x in value))

def normalize_bindings(bindings):
    out = copy.deepcopy(bindings)
    audit = {"version": VERSION, "normalizations": [], "rejected": [],
             "policy": "exact submitted hints only; no coordinates, IDs or functionality inferred"}

    def mapping(value, field):
        if isinstance(value, dict):
            return value
        if not isinstance(value, list):
            audit["rejected"].append({"field": field, "reason": "expected mapping or uniquely named records"})
            return {}
        result = {}; duplicates = set()
        for index, item in enumerate(value):
            keys = [item[k] for k in ("id", "name", "entity_key") if isinstance(item, dict) and k in item]
            if not keys or not all(isinstance(k, str) and k and k == keys[0] for k in keys):
                audit["rejected"].append({"field": field, "index": index, "reason": "missing or conflicting record ID"})
                continue
            key = keys[0]
            if key in result or key in duplicates:
                result.pop(key, None); duplicates.add(key)
                audit["rejected"].append({"field": field, "id": key, "reason": "duplicate record ID"})
                continue
            result[key] = item
        audit["normalizations"].append({"field": field, "operation": "unique submitted ID records to mapping"})
        return result

    out["entities"] = mapping(out.get("entities", {}), "entities")
    for key, item in list(out["entities"].items()):
        if not isinstance(item, dict):
            out["entities"].pop(key)
            audit["rejected"].append({"field": "entities", "id": key, "reason": "non-object binding"})
        elif not vector3(item.get("approach_cm")):
            audit["rejected"].append({"field": "entities", "id": key, "reason": "invalid or missing 3D approach; local probe remains missing"})
    if not out.get("views") and out.get("overview_views"):
        out["views"] = copy.deepcopy(out["overview_views"])
        audit["normalizations"].append({"field": "views", "operation": "overview_views copied exactly to views"})
    for field in ("views", "reference_views"):
        result = {}
        for key, camera in mapping(out.get(field, {}), field).items():
            if not isinstance(camera, dict):
                audit["rejected"].append({"field": field, "id": key, "reason": "missing camera record"}); continue
            conflict = False
            for alias, canonical in (("camera_cm", "position_cm"), ("fov_deg", "horizontal_fov_deg")):
                if alias in camera:
                    if canonical in camera and camera[canonical] != camera[alias]:
                        audit["rejected"].append({"field": field, "id": key, "reason": "conflicting "+alias+" and "+canonical})
                        conflict = True
                        break
                    if canonical not in camera:
                        camera[canonical] = copy.deepcopy(camera[alias])
                        audit["normalizations"].append({"field": field, "id": key, "operation": alias+" copied exactly to "+canonical})
            if conflict:
                continue
            if "target_cm" in camera:
                if "look_cm" in camera and camera["look_cm"] != camera["target_cm"]:
                    audit["rejected"].append({"field": field, "id": key, "reason": "conflicting target_cm and look_cm"}); continue
                if "look_cm" not in camera:
                    camera["look_cm"] = copy.deepcopy(camera["target_cm"])
                    audit["normalizations"].append({"field": field, "id": key, "operation": "target_cm copied exactly to look_cm"})
            if not vector3(camera.get("position_cm")) or not vector3(camera.get("look_cm")):
                audit["rejected"].append({"field": field, "id": key, "reason": "invalid or missing 3D camera vectors"}); continue
            fov = camera.get("horizontal_fov_deg", 60)
            if type(fov) not in (int, float) or not math.isfinite(fov) or not 0 < fov < 180:
                audit["rejected"].append({"field": field, "id": key, "reason": "invalid field of view"}); continue
            result[key] = camera
        out[field] = result
    return out, audit
