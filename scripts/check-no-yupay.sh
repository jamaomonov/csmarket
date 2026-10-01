#!/usr/bin/env bash
# Fail when a YuPay-specific token appears in csmarket source (spec §4.3).
#
# Scope is the source trees only — tests, docs and infra may mention YuPay
# (this repo is ported from it and says so). Every token is a case-insensitive
# substring match except `sku`, which is matched by identifier shape so that
# sku, skus, sku_id, SkuId, mySkuId, SKU_ID and skuCode hit while skull, Skull,
# SKULL and skunk do not. Legitimate exceptions (an acquirer's own field name)
# go in check-no-yupay.allow, one regex per line, and are stripped from a line
# BEFORE the check. Uses perl (present on macOS and ubuntu-latest) because BSD
# sed has no case-insensitive flag and BSD grep has no -P.
#
# Usage: scripts/check-no-yupay.sh [ROOT]   (ROOT defaults to the repo root)
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
root="${1:-$(cd "$script_dir/.." && pwd)}"
allow_file="$script_dir/check-no-yupay.allow"

scopes=(
  apps/api/src apps/worker/src apps/scheduler/src
  apps/web/src apps/admin/src
)
# packages/*/src — globbed at run time; a missing dir is fine.
for d in "$root"/packages/*/src; do
  [ -d "$d" ] && scopes+=("${d#"$root"/}")
done

# Perl regex, applied with /i except for the sku alternative which is
# case-sensitive on purpose: (?-i:...) switches /i off inside the group.
CHECK_REGEX='yupay|brand_|supplier|guest_email|fulfiller|merchants|merchant_api|voucher|game_id|(?-i:(?:sku|Sku)s?(?![a-z])|SKUS?(?![A-Za-z]))'
export CHECK_REGEX

# Allowed-token regexes, joined into one alternation ("" when none).
allow_regex=""
if [ -f "$allow_file" ]; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in \#*) continue ;; esac
    allow_regex+="${allow_regex:+|}${line}"
  done < "$allow_file"
fi
export ALLOW_REGEX="$allow_regex"

# Reads one file; prints "line: token" per hit.
scan='
  BEGIN {
    $re = qr/$ENV{CHECK_REGEX}/i;
    $allow = length $ENV{ALLOW_REGEX} ? qr/$ENV{ALLOW_REGEX}/i : undef;
  }
  my $l = $_;
  $l =~ s/$allow//g if defined $allow;
  my @m = $l =~ /($re)/g;
  print "$.: @m\n" if @m;
'

status=0
for scope in "${scopes[@]}"; do
  dir="$root/$scope"
  [ -d "$dir" ] || continue
  while IFS= read -r -d '' file; do
    hits="$(perl -ne "$scan" "$file" || true)"
    if [ -n "$hits" ]; then
      status=1
      while IFS= read -r hit; do
        printf '%s:%s\n' "${file#"$root"/}" "$hit"
      done <<< "$hits"
    fi
  done < <(find "$dir" -type f \
      -not -path '*/node_modules/*' -not -path '*/generated/*' -not -path '*/.next/*' \
      -not -path '*/dist/*' -not -name '*.png' -not -name '*.jpg' -not -name '*.svg' -print0)
done

if [ "$status" -ne 0 ]; then
  echo "::error::YuPay-specific tokens found in csmarket source (spec §4.3). Rename, or add a justified exception to scripts/check-no-yupay.allow." >&2
fi
exit "$status"
