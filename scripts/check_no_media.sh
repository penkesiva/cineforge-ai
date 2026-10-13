#!/usr/bin/env bash
# Repository hygiene gate: fail if Git tracks or stages media binaries, oversized
# files, or secrets.
#
#   - media/binary extensions are only allowed under tests/fixtures/approved/
#   - no file may exceed CHECK_MEDIA_MAX_BYTES (default 5 MB, measured on the index blob)
#   - no .env files (except .env.example), *.pem, *.key, *.p12, *.pfx
#
# Usage: scripts/check_no_media.sh   (run from anywhere inside the repo)
# Compatible with macOS bash 3.2.
set -euo pipefail

MAX_BYTES="${CHECK_MEDIA_MAX_BYTES:-5242880}"
APPROVED_PREFIX="tests/fixtures/approved/"
MEDIA_EXT_RE='\.(mp4|mov|mkv|webm|avi|mp3|wav|aac|m4a|flac|ogg|opus|png|jpg|jpeg|gif|webp|avif|heic|tif|tiff|psd|exr)$'
SECRET_EXT_RE='\.(pem|key|p12|pfx)$'

cd "$(git rev-parse --show-toplevel)"

paths=()
while IFS= read -r path; do
  [ -n "$path" ] && paths+=("$path")
done < <(
  {
    git -c core.quotepath=off ls-files --cached
    git -c core.quotepath=off diff --cached --name-only --diff-filter=ACMR
  } | sort -u
)

if [ "${#paths[@]}" -eq 0 ]; then
  echo "check_no_media: no tracked or staged files"
  exit 0
fi

sizes=()
while IFS= read -r line; do
  sizes+=("$line")
done < <(printf ':%s\n' "${paths[@]}" | git cat-file --batch-check='%(objectsize)')

violations=()
shopt -s nocasematch
for i in "${!paths[@]}"; do
  path="${paths[$i]}"
  name="${path##*/}"

  if [[ "$path" =~ $MEDIA_EXT_RE ]] && [[ "$path" != "$APPROVED_PREFIX"* ]]; then
    violations+=("media file outside ${APPROVED_PREFIX}: $path")
  fi

  if [[ "$name" == ".env" || ( "$name" == .env.* && "$name" != ".env.example" ) ]]; then
    violations+=("secret env file: $path")
  elif [[ "$name" =~ $SECRET_EXT_RE ]]; then
    violations+=("secret/key file: $path")
  fi

  size="${sizes[$i]}"
  if ! [[ "$size" =~ ^[0-9]+$ ]]; then
    # Not resolvable in the index (e.g. merge conflict): fall back to the working tree.
    size=$( [ -f "$path" ] && wc -c <"$path" | tr -d ' ' || echo 0 )
  fi
  if [ "$size" -gt "$MAX_BYTES" ]; then
    violations+=("file larger than ${MAX_BYTES} bytes (${size}): $path")
  fi
done
shopt -u nocasematch

if [ "${#violations[@]}" -gt 0 ]; then
  echo "check_no_media: FAILED (${#violations[@]} problem(s))" >&2
  printf '  - %s\n' "${violations[@]}" >&2
  echo "Media belongs in the storage backend (cineforge-media volume / object storage)," >&2
  echo "secrets belong in .env (ignored). See AGENTS.md golden rules 2 and 3." >&2
  exit 1
fi

echo "check_no_media: OK (${#paths[@]} files checked)"
