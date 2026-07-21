#!/usr/bin/env bash
# Fail unless a Quay repository is anonymously readable.
#
# Quay creates a repository on first push and makes it PRIVATE by default. A
# private GaCDI image is not a build failure -- the push succeeds and the tag is
# there -- but every Galaxy job that requires the container then dies at pull
# time with an authentication error that says nothing about visibility. This
# check turns that into an immediate, explanatory CI failure the first time an
# image is published.
#
# Visibility is queried without credentials on purpose: the workflow is logged in
# to Quay, so any authenticated check would pass on a private repository and
# prove nothing about what Galaxy can pull.
set -euo pipefail

ORG="${1:?usage: assert-public-image.sh ORG IMAGE}"
IMAGE="${2:?usage: assert-public-image.sh ORG IMAGE}"
# Overridable so the branches can be exercised against a local fixture server.
API="${QUAY_API_BASE:-https://quay.io/api/v1}/repository/${ORG}/${IMAGE}"

response="$(curl -sS -o /tmp/quay-repo.json -w '%{http_code}' "$API" || true)"
is_public="$(jq -r 'if .is_public == null then "unknown" else (.is_public | tostring) end' /tmp/quay-repo.json 2>/dev/null || echo unknown)"

if [[ "$response" == "200" && "$is_public" == "true" ]]; then
  echo "quay.io/${ORG}/${IMAGE} is public."
  exit 0
fi

cat >&2 <<EOF
quay.io/${ORG}/${IMAGE} is not anonymously readable (HTTP ${response}, is_public=${is_public}).

The image was pushed, but Galaxy cannot pull it. Quay makes a repository private
when it is first created, so this is expected on a brand-new image and must be
changed once by hand:

  https://quay.io/repository/${ORG}/${IMAGE}?tab=settings
  -> Repository Visibility -> Make Public

Re-run this workflow afterwards to confirm.
EOF
exit 1
