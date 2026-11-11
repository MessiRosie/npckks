#!/bin/sh
# Build the npckks usage-reporter binary for Windows (x64).
#
# Produces native/npckks_usage_report.exe — a single, statically-linked
# executable with zero runtime dependencies (uses Windows' built-in WinHTTP).
#
# Preferred toolchain: Zig (cross-compiles to Windows from macOS/Linux).
#   macOS (Homebrew):  brew install zig
#   Debian/Ubuntu:     apt-get install zig   (or download from ziglang.org)
#
# Alternative: mingw-w64.
#   macOS (Homebrew):  brew install mingw-w64
#   Debian/Ubuntu:     apt-get install gcc-mingw-w64-x86-64
#
# Usage:  ./native/build.sh

set -e
cd "$(dirname "$0")"

TARGET="${TARGET:-x86_64-windows-gnu}"

if command -v zig >/dev/null 2>&1; then
    echo "Compiling report.c -> npckks_usage_report.exe (zig cc, target $TARGET)"
    zig cc -target "$TARGET" -O2 -s -o npckks_usage_report.exe \
        report.c -lwinhttp -lws2_32 -lshell32
elif command -v x86_64-w64-mingw32-gcc >/dev/null 2>&1; then
    echo "Compiling report.c -> npckks_usage_report.exe (mingw-w64)"
    x86_64-w64-mingw32-gcc -O2 -s -static \
        -o npckks_usage_report.exe report.c \
        -lwinhttp -lws2_32 -lshell32
else
    echo "ERROR: neither 'zig' nor 'x86_64-w64-mingw32-gcc' found." >&2
    echo "Install one of them (see comments above)." >&2
    exit 1
fi

echo "Done: $(pwd)/npckks_usage_report.exe"
