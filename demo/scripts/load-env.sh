#!/usr/bin/env bash
# Source API keys for CloudAgent (login shell uses the same env.sh path)
set -a

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_DEMO_DIR="$(cd "$_SCRIPT_DIR/.." && pwd)"
_ROOT_DIR="$(cd "$_DEMO_DIR/.." && pwd)"

[ -f "$HOME/.config/cloudagent/env.sh" ] && . "$HOME/.config/cloudagent/env.sh"
[ -f "$_DEMO_DIR/.env" ] && . "$_DEMO_DIR/.env"
[ -f "$_ROOT_DIR/.env" ] && . "$_ROOT_DIR/.env"

set +a

if [ -z "${TOGETHER_API_KEY:-}" ]; then
  cat >&2 <<'EOF'
TOGETHER_API_KEY is not set. Use one of:

  1. ~/.config/cloudagent/env.sh  (recommended; loaded by .bashrc)
     cp ~/.config/cloudagent/env.sh.example ~/.config/cloudagent/env.sh
     chmod 600 ~/.config/cloudagent/env.sh
     # edit: export TOGETHER_API_KEY=...

  2. demo/.env or CloudAgent/.env (gitignored)
     cp ../.env.example ../.env   # from demo/, or copy .env.example at repo root

  3. export TOGETHER_API_KEY=... in this shell before sourcing
EOF
  exit 1
fi
