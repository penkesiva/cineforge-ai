#!/usr/bin/env bash
# Repository hygiene gate: fail if Git tracks or stages media binaries, oversized
# files, or secrets.
#
#   - media/binary extensions are only allowed under tests/fixtures/approved/
#   - no file may exceed CHECK_MEDIA_MAX_BYTES (default 5 MB, measured on the index blob)
#   - no .env files (except .env.example), *.pem, *.key, *.p12, *.pfx
#   - no likely API keys in file contents (Anthropic sk-ant-..., OpenAI sk-...)
#   - env files (.env.example, *.env, ...) keep *_API_KEY / *_TOKEN / *_SECRET /
#     *_SERVICE_ROLE_KEY values empty or as obvious placeholders (<...>, ${...}, xxx)
#   Matches are reported as path:line only; the secret itself is never printed.
#
# Usage: scripts/check_no_media.sh   (run from anywhere inside the repo)
# Compatible with macOS bash 3.2.
set -euo pipefail

MAX_BYTES="${CHECK_MEDIA_MAX_BYTES:-5242880}"
APPROVED_PREFIX="tests/fixtures/approved/"
MEDIA_EXT_RE='\.(mp4|mov|mkv|webm|avi|mp3|wav|aac|m4a|flac|ogg|opus|png|jpg|jpeg|gif|webp|avif|heic|tif|tiff|psd|exr)$'
SECRET_EXT_RE='\.(pem|key|p12|pfx)$'
# Content patterns (POSIX ERE for `git grep -E`).
KEY_PATTERNS=(
  'sk-ant-[A-Za-z0-9_-]{20,}'
  '(^|[^A-Za-z0-9_-])sk-[A-Za-z0-9]{32,}'
  '(^|[^A-Za-z0-9_-])sk-proj-[A-Za-z0-9_-]{20,}'
)
ENV_FILE_RE='(^|/)(\.env(\..*)?|.*\.env(\..*)?|env\.example)$'
ENV_SECRET_KEY_RE='^[[:space:]]*(export[[:space:]]+)?([A-Z0-9_]*(_API_KEY|_TOKEN|_SECRET|_SECRET_KEY|_SERVICE_ROLE_KEY))[[:space:]]*=(.*)$'
PLACEHOLDER_RE='^(<.*>|\$\{.*\}|x+|\.\.\.|changeme|change-me|change_me|replace-me|replace_me|placeholder|your[-_].*)$'

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

  if [[ "$path" =~ $ENV_FILE_RE ]]; then
    lineno=0
    while IFS= read -r line || [ -n "$line" ]; do
      lineno=$((lineno + 1))
      if [[ "$line" =~ $ENV_SECRET_KEY_RE ]]; then
        var="${BASH_REMATCH[2]}"
        value="${BASH_REMATCH[4]}"
        value="${value%%[[:space:]]#*}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        if [[ "$value" == \"*\" || "$value" == \'*\' ]]; then
          value="${value:1:${#value}-2}"
        fi
        if [ -n "$value" ] && ! [[ "$value" =~ $PLACEHOLDER_RE ]]; then
          violations+=("non-placeholder value for $var in env file: $path:$lineno")
        fi
      fi
    done < <(git show ":$path" 2>/dev/null || true)
  fi
done
shopt -u nocasematch

grep_args=()
for pattern in "${KEY_PATTERNS[@]}"; do
  grep_args+=(-e "$pattern")
done
while IFS= read -r hit; do
  [ -n "$hit" ] && violations+=("likely API key in file contents: $hit")
done < <(
  set +e
  git -c core.quotepath=off grep --cached -I -n -E "${grep_args[@]}" | cut -d: -f1,2
  code=${PIPESTATUS[0]}
  # git grep exits 1 when nothing matches; anything above 1 is a real error.
  [ "$code" -le 1 ] || echo "git grep failed with exit code $code"
)

if [ "${#violations[@]}" -gt 0 ]; then
  echo "check_no_media: FAILED (${#violations[@]} problem(s))" >&2
  printf '  - %s\n' "${violations[@]}" >&2
  echo "Media belongs in the storage backend (cineforge-media volume / object storage)," >&2
  echo "secrets belong in .env (ignored). See AGENTS.md golden rules 2 and 3." >&2
  exit 1
fi

echo "check_no_media: OK (${#paths[@]} files checked)"
