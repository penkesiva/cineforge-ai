#!/usr/bin/env bash
# Self-test for scripts/check_no_media.sh using throwaway Git repos.
# Usage: scripts/tests/test_check_no_media.sh   (or `make check-media-selftest`)
set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/check_no_media.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

passed=0
failed=0

new_repo() {
  local dir="$WORK/$1"
  mkdir -p "$dir"
  git -C "$dir" init -q
  git -C "$dir" config user.name selftest
  git -C "$dir" config user.email selftest@example.invalid
  git -C "$dir" config commit.gpgsign false
  echo "$dir"
}

# expect <pass|fail> <description> <repo> [ENV=VALUE...]
expect() {
  local want="$1" desc="$2" repo="$3"
  shift 3
  local got
  if (cd "$repo" && env "$@" bash "$SCRIPT") >"$WORK/out.log" 2>&1; then
    got=pass
  else
    got=fail
  fi
  if [ "$got" = "$want" ]; then
    passed=$((passed + 1))
    echo "ok   - $desc"
  else
    failed=$((failed + 1))
    echo "FAIL - $desc (expected $want, got $got)"
    sed 's/^/       /' "$WORK/out.log"
  fi
}

repo=$(new_repo empty)
expect pass "empty repository" "$repo"

repo=$(new_repo clean)
mkdir -p "$repo/src" "$repo/tests/fixtures/approved"
echo "print('hi')" >"$repo/src/app.py"
echo "PLACEHOLDER=" >"$repo/.env.example"
printf 'tiny' >"$repo/tests/fixtures/approved/tiny.png"
git -C "$repo" add -A && git -C "$repo" commit -qm init
expect pass "clean repo with .env.example and approved fixture" "$repo"

repo=$(new_repo tracked-mp4)
echo "x" >"$repo/README.md"
printf 'not really a video' >"$repo/clip.mp4"
git -C "$repo" add -A && git -C "$repo" commit -qm init
expect fail "committed .mp4" "$repo"

repo=$(new_repo staged-png)
echo "x" >"$repo/README.md"
git -C "$repo" add -A && git -C "$repo" commit -qm init
mkdir -p "$repo/apps/web"
printf 'img' >"$repo/apps/web/Logo.PNG"
git -C "$repo" add -A
expect fail "staged-only .PNG (uppercase extension)" "$repo"

repo=$(new_repo fixture-outside)
mkdir -p "$repo/tests/fixtures/other"
printf 'wav' >"$repo/tests/fixtures/other/beep.wav"
git -C "$repo" add -A
expect fail ".wav outside tests/fixtures/approved/" "$repo"

repo=$(new_repo env-file)
echo "SECRET=1" >"$repo/.env"
git -C "$repo" add -f .env
expect fail "tracked .env" "$repo"

repo=$(new_repo env-local)
mkdir -p "$repo/apps/dashboard"
echo "SECRET=1" >"$repo/apps/dashboard/.env.local"
git -C "$repo" add -f apps/dashboard/.env.local
expect fail "tracked nested .env.local" "$repo"

repo=$(new_repo pem)
echo "-----BEGIN-----" >"$repo/server.pem"
git -C "$repo" add -f server.pem
expect fail "tracked .pem" "$repo"

repo=$(new_repo key)
echo "k" >"$repo/deploy.key"
git -C "$repo" add -f deploy.key
expect fail "tracked .key" "$repo"

repo=$(new_repo large)
head -c 4096 /dev/zero >"$repo/blob.bin"
git -C "$repo" add -A
expect fail "file above size limit" "$repo" CHECK_MEDIA_MAX_BYTES=1024
expect pass "file below size limit" "$repo" CHECK_MEDIA_MAX_BYTES=8192

echo
echo "check_no_media selftest: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
