# Deployment Runbook — VK Topic Bridge

Процедуры установки, эксплуатации и восстановления. Дополняет `docs/05-architecture-and-engineering.md` §21–22;
не заменяет его.

---

## 1. Fresh install

1. Клонировать репозиторий и перейти в него.
2. `make sync` — создать окружение и зависимости (`uv`, Python 3.14, committed `uv.lock`).
3. `make hooks` — подключить versioned git-хуки из `.githooks/` (`core.hooksPath`).
4. Создать `.env` (см. `.env.example`):
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `VK_GROUP_TOKEN`, `OWNER_IDS` — обязательные;
   - опционально: `TELEGRAM_BOT_API_URL`, `TELEGRAM_MTPROXY_*`, `SOCKS5_PROXY_URL`, `VK_GROUP_ID`, `DATABASE_URL`, `LOG_LEVEL`.
5. Авторизовать пользовательскую Telegram-сессию: `uv run --locked python authorize_telegram.py`
   (скрипт спросит телефон/пароль/код; сессия ложится в `runtime/telethon/`, gitignored).
6. Применить миграции: `uv run --locked alembic upgrade head`.
7. Первый запуск под PM2: `pm2 start ecosystem.config.cjs`.
8. Проверить: `pm2 status`, `pm2 logs vk-topic-bridge --lines 50`; в логах — успешные startup-проверки.
9. Выполнить owner-регистрацию Telegram-чата (см. § Manual gates).

## 2. Reboot / autostart

```bash
pm2 save                    # сохранить текущий список процессов
pm2 startup                 # выполнить напечатанную команду (один раз, с правами sudo)
```

После reboot `pm2` поднимает `vk-topic-bridge` автоматически; миграции выполняет `scripts/start.sh`
до старта pollers. Курсор VK Long Poll сохраняется в `runtime/vk_cursor/` и переживает перезапуск:
приём продолжается с сохранённого `ts`.

## 3. Logs

| Поток | Путь | Владелец |
|---|---|---|
| stdout/stderr приложения | `logs/pm2.log` | PM2 (`log_file` в `ecosystem.config.cjs`) |
| структурированные логи | `logs/app.log` | Loguru (ротация `LOG_ROTATION`, хранение `LOG_RETENTION`, сжатие `LOG_COMPRESSION`) |

`pm2-logrotate` на сервере уже установлен. Проект его не переустанавливает и не перезаписывает
существующую policy. Проверка текущей конфигурации:

```bash
pm2 conf pm2-logrotate
```

Настройка при необходимости (пример):

```bash
pm2 set pm2-logrotate:max_size 10M
pm2 set pm2-logrotate:retain 14
pm2 set pm2-logrotate:compress true
```

## 4. Runtime paths

| Данные | Путь | Git |
|---|---|---|
| SQLite DB | `data/vk_topic_bridge.db` (`DATABASE_URL`) | ignored |
| Telethon session | `runtime/telethon/` | ignored |
| VK Long Poll cursor | `runtime/vk_cursor/` | ignored |
| Временные медиа | `runtime/media/` | ignored |
| PID PM2 | `pid/` | только `.gitkeep` |
| Логи | `logs/` | только `.gitkeep` |

## 5. Backup

```bash
make backup-db
# или: bash scripts/backup_db.sh [db_path] [dest_dir]
```

Скрипт использует `sqlite3 .backup` (online-copy, безопасно при работающем приложении в WAL-режиме)
и печатает путь созданного файла. Не копировать БД через `cp` при запущенном приложении.

Резервное копирование включает также:
- `runtime/telethon/` (session) — иначе потребуется повторная авторизация;
- `runtime/vk_cursor/` — иначе возможен history gap после восстановления;
- `.env` — хранить отдельно, в защищённом месте (не в Git).

## 6. Restore

1. Остановить приложение: `pm2 stop vk-topic-bridge`.
2. Выполнить restore:
   ```bash
   make restore-db BACKUP=backups/vk_topic_bridge-YYYYMMDD-HHMMSS.db
   # или: bash scripts/restore_db.sh <backup_file> [db_path]
   ```
   Скрипт заменяет файл БД, удаляет устаревшие `-wal`/`-shm` и проверяет, что revision
   восстановленной БД совпадает с head миграций.
3. Запустить приложение: `pm2 start vk-topic-bridge`.
4. Проверить `pm2 logs` и startup-проверки.

## 7. Secrets hygiene

- Никогда не коммитить `.env`, session-файлы, runtime-БД, скачанные медиа.
- Проверка перед коммитом:
  ```bash
  git status --porcelain | grep -E '\.env|\.session|data/.*\.db' && echo "STOP: секреты" || echo "clean"
  ```
- При утечке — ротация токена(ов) через BotFather / VK и обновление `.env`.

## 8. Graceful shutdown

`SIGINT`/`SIGTERM` (в т.ч. `pm2 restart/stop`) запускают согласованное завершение:
остановка pollers → закрытие HTTP-сессий (aiogram, aiohttp) → disconnect Telethon →
`AsyncEngine.dispose()` → flush логирования. `kill_timeout: 15000` в PM2 даёт процессу
достаточно времени. Незавершённые FSM-состояния теряются (ephemeral by design);
delivery-записи остаются в SQLite и доступны через диагностику.

## 9. Known limitations

- **History gap VK Long Poll.** Режим `skip_old_events=False` + персистентный курсор не даёт
  гарантии полного реплея: при `failed=1/3` часть событий может быть потеряна, точное число
  неизвестно. Owners получают однократное уведомление, приём продолжается с нового курсора.
- **Ambiguous delivery.** Если результат вызова Telegram не подтверждён, запись помечается
  `ambiguous` и автоматический повтор запрещён (fail-closed). Разбор — через `Диагностика доставки`
  в Telegram-боте.
- **FSM ephemeral.** Незавершённые операции (мастер регистрации, wizard'ы, ручная пересылка)
  теряются при рестарте; их нужно начать заново.
- **No edit/delete sync.** Изменения и удаления VK-сообщений/постов после публикации не
  синхронизируются.
