#!/bin/sh
set -eu

failed=0
for command in docker curl ssh scp; do
  if command -v "$command" >/dev/null 2>&1; then
    printf '%-18s %s\n' "$command" "OK"
  else
    printf '%-18s %s\n' "$command" "MISSING"
    failed=1
  fi
done

if docker compose version >/dev/null 2>&1; then
  printf '%-18s %s\n' "Compose plugin" "OK"
else
  printf '%-18s %s\n' "Compose plugin" "MISSING"
  failed=1
fi

if docker info >/dev/null 2>&1; then
  printf '%-18s %s\n' "Docker daemon" "OK"
  daemon_ok=1
else
  printf '%-18s %s\n' "Docker daemon" "UNAVAILABLE"
  failed=1
  daemon_ok=0
fi

architecture=$(uname -m)
printf '%-18s %s\n' "WSL architecture" "$architecture"
if [ "$architecture" = "x86_64" ] && [ "$daemon_ok" -eq 1 ]; then
  if docker run --rm --platform linux/arm64 arm64v8/alpine uname -m 2>/dev/null | grep -q aarch64; then
    printf '%-18s %s\n' "ARM64 emulation" "OK"
  else
    printf '%-18s %s\n' "ARM64 emulation" "FAILED"
    failed=1
  fi
fi

keyword_models=$(find models/keyword-detection \
  -maxdepth 1 \
  -type f \
  -name '*.eim' \
  2>/dev/null | wc -l)

object_models=$(find models/object-detection \
  -maxdepth 1 \
  -type f \
  -name '*.eim' \
  2>/dev/null | wc -l)

printf '%-18s %s\n' "Keyword models" "$keyword_models found"
printf '%-18s %s\n' "Object models" "$object_models found"

if [ "$keyword_models" -eq 0 ] && [ "$object_models" -eq 0 ]; then
  printf '%-18s %s\n' "EIM models" "NOT FOUND"
fi

exit "$failed"
