#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE="$ROOT/menu-bar"
BUILD_ROOT="$ROOT/.build/menu-app"
APP="$ROOT/assets/CodexSpeakMenu.app"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/codex-speak-menu.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT

export CLANG_MODULE_CACHE_PATH="$BUILD_ROOT/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$BUILD_ROOT/module-cache"

build_arch() {
    local architecture="$1"
    local scratch="$BUILD_ROOT/$architecture"
    swift build \
        --disable-sandbox \
        --package-path "$PACKAGE" \
        --scratch-path "$scratch" \
        --configuration release \
        --arch "$architecture" \
        --product CodexSpeakMenu
}

build_arch arm64
build_arch x86_64

ARM64_BINARY="$BUILD_ROOT/arm64/arm64-apple-macosx/release/CodexSpeakMenu"
X86_64_BINARY="$BUILD_ROOT/x86_64/x86_64-apple-macosx/release/CodexSpeakMenu"
STAGED_APP="$STAGING/CodexSpeakMenu.app"

mkdir -p "$STAGED_APP/Contents/MacOS"
cp "$PACKAGE/Resources/Info.plist" "$STAGED_APP/Contents/Info.plist"
mkdir -p "$STAGED_APP/Contents/Resources"
cp "$PACKAGE/Resources/AppIcon.icns" "$STAGED_APP/Contents/Resources/AppIcon.icns"
for localization in en zh-Hans; do
    source="$PACKAGE/Resources/$localization.lproj/Localizable.strings"
    destination="$STAGED_APP/Contents/Resources/$localization.lproj"
    mkdir -p "$destination"
    cp "$source" "$destination/Localizable.strings"
done
lipo -create "$ARM64_BINARY" "$X86_64_BINARY" \
    -output "$STAGED_APP/Contents/MacOS/CodexSpeakMenu"
chmod 755 "$STAGED_APP/Contents/MacOS/CodexSpeakMenu"

mkdir -p "$ROOT/assets"
rm -rf "$APP"
mv "$STAGED_APP" "$APP"

cd "$ROOT"
codesign --force --deep --sign - "assets/CodexSpeakMenu.app"
codesign --verify --deep --strict "assets/CodexSpeakMenu.app"
