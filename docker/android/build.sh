#!/bin/sh
set -eu

case "${APP_NAME:-}" in
    edumeeting-llamadas|edumeeting-asistencia) ;;
    *) echo "APP_NAME debe ser edumeeting-llamadas o edumeeting-asistencia." >&2; exit 1 ;;
esac
BUILD_TYPE="${BUILD_TYPE:-debug}"
case "$BUILD_TYPE" in
    debug) task=assembleDebug ;;
    release) task=assembleRelease ;;
    *) echo "BUILD_TYPE debe ser debug o release." >&2; exit 1 ;;
esac

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
# /source contiene la app y la librería compartida edumeeting-ui (incluida desde settings.gradle.kts).
tar -C /source --exclude='.gradle' --exclude='build' \
    --exclude='local.properties' --exclude='.idea' -cf "$workdir/source.tar" .
tar -C "$workdir" -xf "$workdir/source.tar"
cd "$workdir/$APP_NAME"

set --
if [ "$APP_NAME" = "edumeeting-asistencia" ]; then
    if [ -z "${ATTENDANCE_SIGNING_PUBLIC_KEY:-}" ]; then
        echo "Configura ATTENDANCE_SIGNING_PUBLIC_KEY en .env o en el entorno (clave publica Ed25519 Base64)." >&2
        exit 1
    fi
    set -- "-PattendancePublicKey=$ATTENDANCE_SIGNING_PUBLIC_KEY"
fi
[ -n "${VERSION_CODE:-}" ] && set -- "$@" "-PversionCode=$VERSION_CODE"
[ -n "${VERSION_NAME:-}" ] && set -- "$@" "-PversionName=$VERSION_NAME"

if [ "$BUILD_TYPE" = "release" ]; then
    # El keystore llega en Base64 (secreto de CI o .env) y solo vive en el directorio temporal.
    if [ -n "${ANDROID_KEYSTORE_BASE64:-}" ]; then
        printf '%s' "$ANDROID_KEYSTORE_BASE64" | base64 -d > "$workdir/release.jks"
        export EDUMEETING_KEYSTORE_FILE="$workdir/release.jks"
    fi
    if [ -z "${EDUMEETING_KEYSTORE_FILE:-}" ] && [ "${ALLOW_DEBUG_SIGNED_RELEASE:-0}" != "1" ]; then
        echo "Falta ANDROID_KEYSTORE_BASE64 para firmar el release (o define ALLOW_DEBUG_SIGNED_RELEASE=1 para pruebas)." >&2
        exit 1
    fi
fi

# Capturas de edumeeting-ui (Roborazzi): verify compara con las referencias versionadas,
# record las regenera y las copia a artifacts/android/screenshots, off solo ejecuta las pruebas.
screenshots_dir="$workdir/edumeeting-ui/src/test/screenshots"
SCREENSHOTS="${SCREENSHOTS:-auto}"
if [ "$SCREENSHOTS" = "auto" ]; then
    if ls "$screenshots_dir"/*.png >/dev/null 2>&1; then SCREENSHOTS=verify; else SCREENSHOTS=off; fi
fi
case "$SCREENSHOTS" in
    verify) set -- "$@" -Proborazzi.test.verify=true ;;
    record) rm -rf "$screenshots_dir"; set -- "$@" -Proborazzi.test.record=true ;;
    off) ;;
    *) echo "SCREENSHOTS debe ser auto, verify, record u off." >&2; exit 1 ;;
esac

set -- "$@" :edumeeting-ui:testDebugUnitTest :app:testDebugUnitTest

# Wrapper del proyecto: misma versión de Gradle en Docker, CI y Android Studio.
sh ./gradlew --no-daemon --console=plain --max-workers=2 \
    -Dorg.gradle.java.installations.auto-download=false \
    "$@" \
    ":app:$task"

mkdir -p /output
if [ "$SCREENSHOTS" = "record" ]; then
    rm -rf /output/screenshots
    cp -r "$screenshots_dir" /output/screenshots
    echo "Capturas de referencia: artifacts/android/screenshots (copialas a edumeeting-ui/src/test/screenshots)."
fi
cp "app/build/outputs/apk/$BUILD_TYPE/app-$BUILD_TYPE.apk" "/output/$APP_NAME-$BUILD_TYPE.apk"
echo "APK generado: artifacts/android/$APP_NAME-$BUILD_TYPE.apk"