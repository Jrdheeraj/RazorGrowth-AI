#!/usr/bin/env bash
# Lightweight secret scan for CI — fails when obvious credential patterns
# are committed. Deliberately conservative: catches real-looking keys while
# tolerating documentation placeholders.
set -euo pipefail

PATTERNS=(
  'sk-proj-[A-Za-z0-9_-]{20,}'          # OpenAI project keys
  'sk-[A-Za-z0-9]{32,}'                 # generic sk- keys
  'gsk_[A-Za-z0-9]{20,}'                # Groq keys
  'rzp_live_[A-Za-z0-9]{10,}'           # Razorpay LIVE key ids
  'AKIA[0-9A-Z]{16}'                    # AWS access keys
)

EXCLUDES=(
  ':!.env'
  ':!*.lock'
  ':!frontend/node_modules'
  ':!.venv'
  ':!*__pycache__*'
)

found=0
for pat in "${PATTERNS[@]}"; do
  # git grep against the index (committed content only)
  if git grep -nE "$pat" -- . "${EXCLUDES[@]}" >/dev/null 2>&1; then
    echo "::error::Potential secret matching pattern '$pat':"
    git grep -nE "$pat" -- . "${EXCLUDES[@]}" | sed 's/^/  /'
    found=1
  fi
done

if [ "$found" -eq 0 ]; then
  echo "Secret scan clean."
fi
exit "$found"
