#!/bin/sh
# Бэкап базы и загруженных файлов. Работает в контейнере backup
# (см. docker-compose.yml), складывает архивы в ./backups на сервере.
#
#   backup.sh          ждать и делать бэкап раз в сутки в BACKUP_HOUR_UTC
#   backup.sh now      сделать бэкап прямо сейчас и выйти
#
# Что внутри:
#   db-ГГГГ-ММ-ДД_ЧЧММ.dump      база (pg_dump -Fc, восстанавливается pg_restore)
#   media-ГГГГ-ММ-ДД_ЧЧММ.tar.gz  загрузки: решения участников, условия, фото
set -eu

OUT=/backups
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
HOUR="${BACKUP_HOUR_UTC:-00}"   # 00 UTC = 03:00 по Москве

run_backup() {
    stamp=$(date -u +%F_%H%M)
    echo "backup: начинаю $stamp"
    # Сначала во временный файл: оборванный бэкап не должен выглядеть целым.
    pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$OUT/.db-$stamp.tmp"
    mv "$OUT/.db-$stamp.tmp" "$OUT/db-$stamp.dump"
    tar czf "$OUT/.media-$stamp.tmp" -C /media .
    mv "$OUT/.media-$stamp.tmp" "$OUT/media-$stamp.tar.gz"
    find "$OUT" -maxdepth 1 \( -name 'db-*.dump' -o -name 'media-*.tar.gz' \) -mtime +"$KEEP_DAYS" -delete
    echo "backup: готово — $(ls -1 "$OUT" | wc -l) файлов в /backups, храню $KEEP_DAYS дн."
}

if [ "${1:-}" = now ]; then
    run_backup
    exit 0
fi

echo "backup: ежедневно в ${HOUR}:xx UTC, храню ${KEEP_DAYS} дн."
while true; do
    today=$(date -u +%F)
    # «Настал час и сегодня ещё не делали», а не «ровно этот час»: если
    # сервер лежал в BACKUP_HOUR_UTC, бэкап сделается сразу после старта.
    if [ "$(date -u +%H)" -ge "$HOUR" ] && ! ls "$OUT"/db-"$today"_*.dump >/dev/null 2>&1; then
        run_backup || echo "backup: ОШИБКА, повторю через 10 минут"
    fi
    sleep 600
done
