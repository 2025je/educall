#!/bin/sh
set -eu

case "${APP_NAME:-}" in
    edumeeting-llamadas|edumeeting-asistencia) ;;
    *) echo "APP_NAME debe ser edumeeting-llamadas o edumeeting-asistencia." >&2; exit 1 ;;
esac

workdir="$(mktemp -d)"
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

set -- "$@" :edumeeting-ui:testDebugUnitTest :app:testDebugUnitTest

gradle --no-daemon --console=plain --max-workers=2 \
    -Dorg.gradle.java.installations.auto-download=false \
    "$@" \
    :app:assembleDebug

mkdir -p /output
cp app/build/outputs/apk/debug/app-debug.apk "/output/$APP_NAME-debug.apk"
echo "APK generado: artifacts/android/$APP_NAME-debug.apk"
