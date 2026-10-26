#!/bin/sh
# Respaldos de PostgreSQL con retención.
#   backup.sh once   -> un respaldo y termina (se usa antes de migrar y desde scripts/backup-db.ps1)
#   backup.sh loop   -> un respaldo cada BACKUP_INTERVAL_HOURS horas
#   backup.sh restore ARCHIVO -> restaura un respaldo de BACKUP_DIR en una sola transacción
set -eu

BACKUP_DIR=${BACKUP_DIR:-/backups}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}
INTERVAL_HOURS=${BACKUP_INTERVAL_HOURS:-24}
LABEL=${BACKUP_LABEL:-manual}

export PGPASSWORD="$POSTGRES_PASSWORD"

backup() {
    mkdir -p "$BACKUP_DIR"
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    target="$BACKUP_DIR/edumeeting-$stamp-$1.dump"
    pg_dump --host="${POSTGRES_HOST:-db}" --port="${POSTGRES_PORT:-5432}" --username="$POSTGRES_USER" \
        --dbname="$POSTGRES_DB" --format=custom --no-owner --file="$target.partial" || { rm -f "$target.partial"; return 1; }
    mv "$target.partial" "$target" || return 1
    echo "Respaldo creado: $(basename "$target") ($(du -h "$target" | cut -f1))"
    find "$BACKUP_DIR" -maxdepth 1 -name 'edumeeting-*.dump' -type f -mtime +"$RETENTION_DAYS" -print -delete \
        | sed 's/^/Respaldo antiguo eliminado: /'
    find "$BACKUP_DIR" -maxdepth 1 -name '*.partial' -type f -mmin +60 -delete
}

case "${1:-once}" in
    once)
        backup "$LABEL"
        ;;
    loop)
        while true; do
            backup programado || echo "El respaldo programado falló; se reintentará en el siguiente ciclo." >&2
            sleep $((INTERVAL_HOURS * 3600))
        done
        ;;
    restore)
        name=$(basename "${2:?Indica el archivo a restaurar}")
        test -f "$BACKUP_DIR/$name" || { echo "No existe $name" >&2; exit 1; }
        pg_restore --host="${POSTGRES_HOST:-db}" --port="${POSTGRES_PORT:-5432}" --username="$POSTGRES_USER" \
            --dbname="$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction "$BACKUP_DIR/$name"
        echo "Restaurado: $name"
        ;;
    *)
        echo "Uso: backup.sh once|loop|restore ARCHIVO" >&2
        exit 2
        ;;
esac
