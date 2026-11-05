"""Required files for building and rendering with the pinned Linux UE engine."""

import json
import os

REQUIRED = {
    "Engine/Binaries/Linux/UnrealEditor": True,
    "Engine/Binaries/Linux/UnrealEditor-Cmd": True,
    "Engine/Binaries/Linux/ShaderCompileWorker": True,
    "Engine/Binaries/Linux/libUnrealEditor-Core.so": False,
    "Engine/Binaries/Linux/libUnrealEditor-Engine.so": False,
    "Engine/Build/BatchFiles/Linux/Build.sh": True,
    "Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll": False,
    "Engine/Extras/ThirdPartyNotUE/SDKs/HostLinux/Linux_x64/"
    "v26_clang-20.1.8-rockylinux8/x86_64-unknown-linux-gnu/bin/clang++": True,
}


def engine_errors(path, label):
    errors = []
    for name, executable in REQUIRED.items():
        file = path / name
        if (
            not file.is_file()
            or not os.access(file, os.R_OK)
            or executable
            and not os.access(file, os.X_OK)
        ):
            errors.append(
                label
                + ": missing/unreadable"
                + (" or non-executable " if executable else " ")
                + name
            )
    try:
        version = json.loads((path / "Engine/Build/Build.version").read_text())
        if [version[k] for k in ("MajorVersion", "MinorVersion", "PatchVersion")] != [
            5,
            8,
            3,
        ]:
            errors.append(label + ": expected UE 5.8.3")
    except (OSError, ValueError, KeyError):
        errors.append(label + ": missing/invalid Engine/Build/Build.version")
    return errors
