#!/usr/bin/env bash
set -euo pipefail

work_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/g2lex-espeak-ng"
prefix="${ESPEAK_NG_PREFIX:-$work_dir/install}"
revision="$(awk -F '"' '/^espeak_git_revision = / { print $2; exit }' datasets.toml)"
expected_version="$(awk -F '"' '/^expected_espeak_version = / { print $2; exit }' datasets.toml)"

if [[ -z "$revision" || -z "$expected_version" ]]; then
  echo "eSpeak-NG revision and expected version must be configured in datasets.toml" >&2
  exit 1
fi

rm -rf "$work_dir"
mkdir -p "$work_dir"
archive="$work_dir/espeak-ng.tar.gz"
curl --fail --silent --show-error --location \
  "https://github.com/espeak-ng/espeak-ng/archive/${revision}.tar.gz" \
  --output "$archive"
tar -xzf "$archive" -C "$work_dir"
source_dir="$(find "$work_dir" -mindepth 1 -maxdepth 1 -type d -name 'espeak-ng-*' -print -quit)"

cmake -S "$source_dir" -B "$work_dir/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON \
  -DENABLE_TESTS=OFF \
  -DUSE_KLATT=OFF \
  -DUSE_SPEECHPLAYER=OFF \
  -DUSE_MBROLA=OFF \
  -DUSE_LIBSONIC=OFF \
  -DUSE_LIBPCAUDIO=OFF \
  -DCMAKE_INSTALL_PREFIX="$prefix"
cmake --build "$work_dir/build" --parallel "$(nproc)"
cmake --install "$work_dir/build"

"$prefix/bin/espeak-ng" --version | grep -F "${expected_version}" >/dev/null
test -f "$prefix/lib/libespeak-ng.so"
test -d "$prefix/share/espeak-ng-data"

if [[ -n "${GITHUB_ENV:-}" ]]; then
  {
    printf 'ESPEAK_NG_LIBRARY=%s\n' "$prefix/lib/libespeak-ng.so"
    printf 'ESPEAK_NG_DATA=%s\n' "$prefix/share/espeak-ng-data"
  } >> "$GITHUB_ENV"
  printf '%s/bin\n' "$prefix" >> "$GITHUB_PATH"
fi
