#!/bin/sh
# Бэкап базы и загруженных файлов. Работает в контейнере backup
# (см. docker-compose.yml), складывает архивы в ./backups на сервере [или он же /backups в контейнере].
#
#   backup.sh          ждать и делать бэкап раз в сутки в BACKUP_HOUR_UTC
#   backup.sh now      сделать бэкап прямо сейчас и выйти
#
# Что внутри:
#   db-ГГГГ-ММ-ДД_ЧЧММ.dump      база (pg_dump -Fc, восстанавливается pg_restore)
#   media-ГГГГ-ММ-ДД_ЧЧММ.tar.gz  загрузки: решения, сканы согласий, условия, фото
#
# Если задан BACKUP_AGE_RECIPIENT (открытый ключ age, «age1…»), оба файла
# шифруются и получают расширение .age. В бэкапах паспортные данные и
# сканы согласий: зашифрованными их можно спокойно копировать во внешнее
# хранилище. Расшифровать можно только закрытым ключом, которого на
# сервере нет (см. docs/deploy.md, «Бэкапы»).
set -eu

OUT=/backups
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
HOUR="${BACKUP_HOUR_UTC:-00}"   # 00 UTC = 03:00 по Москве
RECIPIENT="${BACKUP_AGE_RECIPIENT:-}"

if [ -n "$RECIPIENT" ] && ! command -v age >/dev/null 2>&1; then
    echo "backup: ставлю age для шифрования"
    apk add --no-cache age >/dev/null || { echo "backup: ОШИБКА — не удалось поставить age" >&2; exit 1; }
fi

fail() {
    echo "backup: ОШИБКА — $1" >&2
    rm -f "$OUT"/.db-*.tmp "$OUT"/.media-*.tmp
    return 1
}

# Каждый шаг проверяется явно, а не через set -e: в ежедневном цикле
# функция вызывается как «run_backup || …», и там set -e не действует —
# упавший pg_dump иначе дал бы недописанный файл под видом бэкапа.
run_backup() {
    stamp=$(date -u +%F_%H%M)
    echo "backup: начинаю $stamp"
    # Сначала во временный файл: оборванный бэкап не должен выглядеть целым.
    pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$OUT/.db-$stamp.tmp" \
        || { fail "pg_dump не отработал"; return 1; }
    # Дамп читается — значит, он целый.
    pg_restore --list "$OUT/.db-$stamp.tmp" >/dev/null \
        || { fail "дамп базы повреждён"; return 1; }
    tar czf "$OUT/.media-$stamp.tmp" -C /media . \
        || { fail "не удалось упаковать загрузки (место на диске?)"; return 1; }
    ext=""
    if [ -n "$RECIPIENT" ]; then
        for part in db media; do
            age -r "$RECIPIENT" -o "$OUT/.$part-$stamp.tmp.age" "$OUT/.$part-$stamp.tmp" \
                || { fail "шифрование не удалось"; rm -f "$OUT"/.*.tmp.age; return 1; }
            mv "$OUT/.$part-$stamp.tmp.age" "$OUT/.$part-$stamp.tmp"
        done
        ext=".age"
    fi
    mv "$OUT/.db-$stamp.tmp" "$OUT/db-$stamp.dump$ext" || { fail "mv"; return 1; }
    mv "$OUT/.media-$stamp.tmp" "$OUT/media-$stamp.tar.gz$ext" || { fail "mv"; return 1; }
    # Старые удаляем только после удачного бэкапа: полоса ошибок не должна
    # съесть последние хорошие копии.
    find "$OUT" -maxdepth 1 \( -name 'db-*.dump*' -o -name 'media-*.tar.gz*' \) -mtime +"$KEEP_DAYS" -delete
    echo "backup: готово — $(ls -1 "$OUT" | wc -l) файлов в /backups, храню $KEEP_DAYS дн."
}

if [ "${1:-}" = now ]; then
    run_backup || exit 1
    exit 0
fi

echo "backup: ежедневно в ${HOUR}:xx UTC, храню ${KEEP_DAYS} дн."
while true; do
    today=$(date -u +%F)
    # «Настал час и сегодня ещё не делали», а не «ровно этот час»: если
    # сервер лежал в BACKUP_HOUR_UTC, бэкап сделается сразу после старта.
    if [ "$(date -u +%H)" -ge "$HOUR" ] && ! ls "$OUT"/db-"$today"_*.dump* >/dev/null 2>&1; then
        run_backup || echo "backup: ОШИБКА, повторю через 10 минут"
    fi
    sleep 600
done
