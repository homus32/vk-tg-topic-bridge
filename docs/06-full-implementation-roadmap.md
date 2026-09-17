# VK Topic Bridge — Full Implementation Roadmap

> Этот документ — карта всей реализации до полностью рабочего проекта.
> Он намеренно поверхностный: детали каждого этапа формируются отдельным intent/draft вместе с Prometheus.

## Оглавление

- [[#1. Правило работы с roadmap]]
- [[#2. Этап 1 — Bootstrap проекта]]
- [[#3. Этап 2 — Config, logger и lifecycle]]
- [[#4. Этап 3 — Database и migrations]]
- [[#5. Этап 4 — Telegram infrastructure]]
- [[#6. Этап 5 — VK infrastructure]]
- [[#7. Этап 6 — Forwarding core]]
- [[#8. Этап 7 — Telegram admin UI]]
- [[#9. Этап 8 — VK UI и ручная пересылка]]
- [[#10. Этап 9 — Wall и attachments]]
- [[#11. Этап 10 — Reliability и edge cases]]
- [[#12. Этап 11 — Acceptance hardening]]
- [[#13. Этап 12 — Deployment]]
- [[#14. Готовность проекта]]

---

# 1. Правило работы с roadmap

Каждый этап ниже — отдельный будущий intent.

Для конкретного этапа:

1. Prometheus исследует текущую кодовую базу и документацию;
2. проводит интервью только по оставшимся неопределённостям;
3. фиксирует acceptance criteria;
4. Ultrabrain проверяет архитектуру и создаёт skeleton только нужных файлов;
5. создаётся decision-complete план в `.omo/plans/`;
6. Sisyphus реализует;
7. выполняются quality gates;
8. Ultrabrain делает review до явного `APPROVE`.

Следующий этап начинается только после завершения предыдущего либо после осознанного изменения roadmap.

Этот roadmap не заменяет планы `.omo/plans/`.

---

# 2. Этап 1 — Bootstrap проекта

Цель: превратить текущий минимальный репозиторий в корректно настроенный Python-проект без реализации продуктовой логики.

Включает:

- окончательную настройку `pyproject.toml`;
- runtime dependencies;
- dev dependencies;
- `uv.lock`;
- Python 3.14;
- Ruff;
- BasedPyright;
- pytest;
- базовые pytest markers/config;
- Makefile bootstrap commands;
- `.gitignore`;
- `.env.example`;
- directory skeleton;
- проверку совместимости всех выбранных библиотек.

Не включает:

- бизнес-логику;
- handlers;
- database models;
- migrations;
- реальные API clients;
- PM2 deployment;
- полноценный `config.py` / `logger.py`.

Результат: чистое окружение разворачивается одной командой, quality tooling работает, будущая архитектура имеет подготовленную структуру.

Подробный draft этого этапа: отдельный артефакт `07-bootstrap-intent-draft.md`.

---

# 3. Этап 2 — Config, logger и lifecycle

Реализовать инфраструктурный фундамент процесса:

- корневой `config.py` через `pydantic-settings`;
- валидацию `.env`;
- `OWNER_IDS`;
- proxy settings;
- корневой `logger.py` по утверждённому reference;
- Loguru + interception stdlib logging;
- `logs/app.log`;
- startup/shutdown orchestration;
- composition root;
- fatal startup policy.

После этапа приложение должно уметь корректно стартовать и завершаться, даже если продуктовые adapters ещё не реализованы полностью.

---

# 4. Этап 3 — Database и migrations

Реализовать:

- SQLAlchemy AsyncIO;
- `aiosqlite`;
- SQLite pragmas;
- ORM models;
- repository interfaces/implementations;
- transaction strategy;
- Alembic;
- initial migration;
- миграционные Makefile commands.

Минимальное persisted state:

- bridge settings;
- Telegram topics;
- VK aliases;
- delivery/idempotency records.

После этапа schema управляется только migrations.

---

# 5. Этап 4 — Telegram infrastructure

Реализовать инфраструктуру Telegram без полного UI:

- aiogram Bot API client;
- custom/local Bot API URL;
- независимую SOCKS5 policy Bot API;
- Telethon client;
- MTProto Proxy → SOCKS5 → direct;
- persistent Telethon session;
- root `authorize_telegram.py`;
- получение Telegram topics;
- startup connectivity checks;
- adapters/ports для application layer.

---

# 6. Этап 5 — VK infrastructure

Реализовать:

- VKBottle initialization;
- Long Poll;
- VK API adapter;
- нормализацию VK events в собственные DTO;
- получение полной версии `is_cropped`;
- получение автора;
- реакцию 👍;
- необходимые startup/config checks.

На этом этапе handlers остаются максимально тонкими.

---

# 7. Этап 6 — Forwarding core

Реализовать центральную application-логику сообщений VK → Telegram:

- `@all`;
- hashtag;
- оба условия одновременно → одна публикация;
- toggles;
- destination topic;
- author link;
- служебные hashtags;
- publication composition;
- успешная публикация → VK 👍;
- idempotency повторных автоматических events.

Бизнес-правила должны быть покрыты unit/application tests без реальной сети.

---

# 8. Этап 7 — Telegram admin UI

Реализовать User Stories Telegram owner interface:

- owner access;
- silent ignore unauthorized;
- `/start`;
- registration Telegram chat;
- проверка прав;
- refresh topics;
- выбор destination topics;
- три toggle;
- settings list;
- owner notifications;
- change Telegram chat;
- reset defaults;
- FSM/navigation.

UI должен работать поверх application use cases, без SQL/API логики внутри handlers.

---

# 9. Этап 8 — VK UI и ручная пересылка

Реализовать пользовательский VK interface:

- Help;
- кнопки;
- ручная пересылка ровно одного сообщения;
- выбор topic по номеру;
- cancel/back;
- aliases;
- add/edit/delete alias;
- unknown alias flow;
- VK FSM/session state.

---

# 10. Этап 9 — Wall и attachments

Реализовать полный content pipeline:

- новые VK wall posts;
- отдельный wall destination;
- `#изстенывк`;
- ссылка на оригинальный post;
- photos;
- videos;
- documents;
- лимит 50 МБ;
- unsupported attachments;
- attachment download failures;
- partial success;
- корректное разбиение Telegram publication при platform limits.

---

# 11. Этап 10 — Reliability и edge cases

Закрыть failure scenarios:

- удалённый/недоступный target topic;
- General fallback;
- owner notification;
- fallback success считается delivery success;
- transient Telegram/VK errors;
- повторные events;
- DB contention;
- crash одной critical background task;
- graceful shutdown;
- корректные user-facing errors;
- отсутствие traceback пользователю.

Здесь же проводится architecture cleanup только по реально обнаруженному duplication/complexity.

---

# 12. Этап 11 — Acceptance hardening

Сопоставить **каждый** User Story / Acceptance Criterion с тестом или явной manual verification.

Проверить:

- Product Spec;
- User Stories;
- Technical Requirements;
- FSM & UI;
- Architecture & Engineering Specification.

Добавить:

- acceptance tests;
- integration tests;
- opt-in E2E smoke tests;
- regression tests для найденных bugs.

Ни один AC не должен оставаться «реализованным на глаз».

---

# 13. Этап 12 — Deployment

Реализовать production deployment:

- `scripts/start.sh`;
- `ecosystem.config.cjs`;
- PID-файл процесса PM2 хранится в `pid/`;
- migration-before-start;
- PM2 autorestart;
- `logs/pm2.log`;
- отдельный `logs/app.log`;
- проверка установленного `pm2-logrotate`;
- согласованная log rotation policy;
- `pm2 save`;
- `pm2 startup`;
- persistent SQLite/session paths;
- backup/restore SQLite;
- deployment/runbook documentation.

Проверить fresh install и reboot scenario.

---

# 14. Готовность проекта

Проект считается полностью реализованным, когда:

- закрыты все User Stories и Acceptance Criteria;
- выполнены Architecture Acceptance Criteria;
- `make check` проходит;
- migration test проходит от пустой БД до `head`;
- E2E smoke успешно проходит на тестовой инфраструктуре;
- приложение корректно переживает restart PM2;
- после reboot PM2 автоматически поднимает приложение;
- конфигурация и secrets не требуют правки исходного кода;
- Loguru и PM2 ведут независимые ротируемые логи;
- в репозитории нет токенов, session и runtime DB;
- Ultrabrain дал `APPROVE` финальному состоянию.
