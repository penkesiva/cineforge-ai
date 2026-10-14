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

# Fake keys are assembled at runtime so this file never matches the scanner itself.
rep() { local out="" i; for ((i = 0; i < $2; i++)); do out="$out$1"; done; echo "$out"; }
ANT_KEY="sk-""ant-api03-$(rep aB3_ 8)"
OPENAI_KEY="sk-""$(rep Ab12 10)"
PROJ_KEY="sk-""proj-$(rep A1_- 6)"

repo=$(new_repo anthropic-key)
mkdir -p "$repo/src"
echo "client = Anthropic(api_key=\"$ANT_KEY\")" >"$repo/src/llm.py"
git -C "$repo" add -A && git -C "$repo" commit -qm init
expect fail "Anthropic key in a tracked .py file" "$repo"

repo=$(new_repo openai-key)
echo "token: $OPENAI_KEY" >"$repo/config.yaml"
git -C "$repo" add -A && git -C "$repo" commit -qm init
expect fail "OpenAI-style key in a tracked .yaml file" "$repo"

repo=$(new_repo openai-proj-key)
echo "OPENAI=$PROJ_KEY" >"$repo/notes.txt"
git -C "$repo" add -A && git -C "$repo" commit -qm init
expect fail "OpenAI project key in a tracked file" "$repo"

repo=$(new_repo staged-key)
echo "x" >"$repo/README.md"
git -C "$repo" add -A && git -C "$repo" commit -qm init
echo "key = '$ANT_KEY'" >"$repo/leak.py"
git -C "$repo" add leak.py
expect fail "staged-only file with an Anthropic key" "$repo"

repo=$(new_repo env-example-real-value)
echo "ANTHROPIC_API_KEY=abc123notaplaceholder" >"$repo/.env.example"
git -C "$repo" add -A && git -C "$repo" commit -qm init
expect fail ".env.example with a real-looking ANTHROPIC_API_KEY value" "$repo"

repo=$(new_repo env-file-quoted-export)
mkdir -p "$repo/config"
echo "export ANTHROPIC_API_KEY=\"abc123notaplaceholder\"  # oops" >"$repo/config/prod.env"
git -C "$repo" add -A && git -C "$repo" commit -qm init
expect fail "quoted export of ANTHROPIC_API_KEY in a tracked *.env file" "$repo"

repo=$(new_repo env-example-service-role)
echo "SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiJ9.payload" >"$repo/.env.example"
git -C "$repo" add -A && git -C "$repo" commit -qm init
expect fail ".env.example with a SUPABASE_SERVICE_ROLE_KEY value" "$repo"

repo=$(new_repo env-example-placeholders)
cat >"$repo/.env.example" <<'EOF'
# Anthropic key is optional (Sources page)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=""
OTHER_API_KEY=<your-key>
EXTRA_API_KEY=${EXTRA_API_KEY}
MORE_API_KEY=xxxxxxxx
GITHUB_TOKEN=   # optional
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
export WEBHOOK_SECRET='changeme'
ANTHROPIC_MODEL=claude-sonnet-4-5
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres
EOF
git -C "$repo" add -A && git -C "$repo" commit -qm init
expect pass ".env.example with empty and placeholder key values" "$repo"

repo=$(new_repo docs-mention-key)
mkdir -p "$repo/docs"
cat >"$repo/docs/providers.md" <<'EOF'
Set `ANTHROPIC_API_KEY=sk-ant-...` in .env, or ANTHROPIC_API_KEY=your-key.
Example: ANTHROPIC_API_KEY=abc123notaplaceholder (docs are not env files).
EOF
echo "short = 'sk-ant-short'" >"$repo/docs/short.py"
echo "id = 'mask-$(rep Ab12 10)'" >"$repo/docs/ids.py"
git -C "$repo" add -A && git -C "$repo" commit -qm init
expect pass "docs mentioning the key variable, short sk- strings, embedded 'sk-'" "$repo"

repo=$(new_repo large)
head -c 4096 /dev/zero >"$repo/blob.bin"
git -C "$repo" add -A
expect fail "file above size limit" "$repo" CHECK_MEDIA_MAX_BYTES=1024
expect pass "file below size limit" "$repo" CHECK_MEDIA_MAX_BYTES=8192

echo
echo "check_no_media selftest: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
