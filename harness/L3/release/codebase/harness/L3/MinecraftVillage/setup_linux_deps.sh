#!/usr/bin/env bash
# Ubuntu user-space Vulkan loader/tools; no sudo and no system-package changes.
set -euo pipefail
task_runtime_root="${1:?Usage: setup_linux_deps.sh /absolute/runtime/directory}"
case "$task_runtime_root" in /*) ;; *) echo 'Runtime directory must be absolute' >&2; exit 2;; esac
mkdir -p "$task_runtime_root/downloads" "$task_runtime_root/deps" "$task_runtime_root/xdg"
chmod 700 "$task_runtime_root/xdg"
cd "$task_runtime_root/downloads"
apt-get download libvulkan1 vulkan-tools git-lfs
for task_package in ./*.deb; do dpkg-deb -x "$task_package" "$task_runtime_root/deps"; done
sha256sum ./*.deb > "$task_runtime_root/dependency-sha256.txt"
env LD_LIBRARY_PATH="$task_runtime_root/deps/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    XDG_RUNTIME_DIR="$task_runtime_root/xdg" \
    "$task_runtime_root/deps/usr/bin/vulkaninfo" --summary > "$task_runtime_root/vulkan-summary.txt"
echo "Vulkan report: $task_runtime_root/vulkan-summary.txt"
