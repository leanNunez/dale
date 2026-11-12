#!/usr/bin/env bash
# Fail if tracked code or config names an Anthropic key or token, or if a test re-enables
# sockets. The SDK client takes no arguments (the environment holds the credentials).
# Prints file names only, never the matching line. Exit: 0 clean, 1 found, 2 error.
# Usage: check_no_api_key.sh [repo_root]   (default: the repository root)
set -uo pipefail

root="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$root" && git rev-parse --git-dir >/dev/null 2>&1 || { echo "error: $root is not a git repo" >&2; exit 2; }

# This guard and its own test fixtures name the patterns on purpose.
skip=(':(exclude)openspec' ':(exclude)uv.lock'
  ':(exclude)scripts/check_no_api_key.sh' ':(exclude)tests/unit/test_no_api_key_script.py'
  ':(exclude)tests/unit/test_anthropic_client_args.py')
# A key/token name assigned, passed, quoted or used as a dict key (not a bare mention).
keys="anthropic_api_key|anthropic_auth_token|secrets\\.anthropic"
keys+="|(api[_-]key|auth[_-]token)[\"']?[[:space:]]*[]=:,)}]"
sockets='enable_socket|socket_enabled|force-enable-socket'

# scan <regex> <git pathspec...>: -l prints names only; grep exit 2 (unreadable file) is fatal.
scan() {
  local pattern=$1 files out rc
  shift
  mapfile -d '' files < <(git ls-files -z -- "$@" "${skip[@]}")
  [ "${#files[@]}" -eq 0 ] && return 0
  out=$(grep -ilE -e "$pattern" -- "${files[@]}")
  rc=$?
  case $rc in
    0) printf '%s\n' "$out"; return 1 ;;
    1) return 0 ;;
    *) echo "error: grep could not read every file" >&2; return 2 ;;
  esac
}

status=0
scan "$keys" '*.py' '*.sh' '*.toml' '*.yml' '*.yaml' '*.cfg' '*.ini' '*.json' || status=$?
scan "$sockets" tests || { rc=$?; [ "$rc" -gt "$status" ] && status=$rc; }
[ "$status" -eq 1 ] && echo "error: key reference or enabled socket found in the files above" >&2
exit "$status"
