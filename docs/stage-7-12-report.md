# Stage 7–12 — Отчёт о реализации (финишный спринт finish-vk-topic-bridge)

> Отчёт составлен по итогам исполнения плана `.omo/plans/finish-vk-topic-bridge.md`,
> intent `.omo/drafts/finish-vk-topic-bridge.md`, evidence-каталога
> `.omo/evidence/finish-vk-topic-bridge/` (68 файлов), истории коммитов,
> notepad'а исполнителя и двух раундов независимого review.
>
> Статус на дату отчёта (2026-09-19): весь код Stage 7–12 реализован и закоммичен
> (6 коммитов), `make check` — EXIT=0 (847 passed, coverage 90%, basedpyright 0 ошибок),
> независимый review вернул **APPROVE**. **Живое ручное тестирование ещё не выполнялось** —
> это следующий шаг владельца (задача 25 / F3).

---

## 1. Краткое резюме (мнение)

Финишный спринт закрыл последние шесть этапов roadmap (Stage 7–12) одним планом:
Telegram Admin UI с ReplyKeyboard, VK UI с алиасами и ручной пересылкой, стена VK,
медиа-пайплайн (фото/видео/документы ≤50 МБ), General fallback с уведомлениями owners,
персистентный Long Poll курсор, диагностика доставки, acceptance-харденинг и деплой-обвязка.

Главный результат в цифрах: **+13 592 строки в 130 файлах**, тестовый набор вырос
с 501 до **847 тестов** (90% покрытия), все 27 US-историй получили acceptance-файлы,
независимый review production-кода подтвердил соответствие замороженным контрактам.

Главный урок цикла — **три wiring-дефекта, которые прошли мимо 800+ зелёных тестов**:
они жили в точке сборки (`container.py`), которую ни один тест не покрывал, и были найдены
только независимым review. После фиксов добавлены wiring-регрессионные тесты, которые
ловят каждый из трёх мутационными пробами. Мораль: тесты, поднимающие компоненты
изолированно, не проверяют собранное приложение.

Оценка готовности кода: **~95%** (остаток — живая верификация владельцем и мелкие
non-blocking долги). Оценка уверенности в live-поведении: **средняя** — см. §9
(честный список мест, где я не уверен, что оно работает в бою).

---

## 2. Как шла разработка

### 2.1 Процесс: ultrabrain-development-loop

Разработка велась по трёхролевой схеме (skill `ultrabrain-development-loop`):

1. **Ultrabrain (планировщик, одна сессия `ses_f4bfa5016ffeZh8BhXbDWnNLUD`)** — исследовал
   черновик и кодовую базу (через `explore`/`librarian`, включая research-сессии из черновика:
   `ses_f4c7d42f…`, `ses_f4c7d427…`, `ses_f4c1e8b4…`, `ses_f4c1e8d6…`), провёл clarification gate
   (блокирующих USER_OWNED-вопросов не оказалось), создал 26 скелетов с TODO-контрактами
   и написал decision-complete план: **25 задач + F1–F4, 8 волн, матрица зависимостей,
   acceptance-матрица US-01..US-27, owner gates как задача 25**.
2. **Sisyphus (исполнитель)** — реализовывал волнами, писал тесты (TDD: RED→GREEN,
   для миграции — RED на schema-assertions), помечал чекбоксы плана на месте, гонял `make check`
   после каждой задачи, собирал evidence.
3. **Ultrabrain (ревьюер, та же сессия)** — review production-кода по diff от baseline
   `8e26879`: раунд 1 → `REQUEST_CHANGES` (3 блокера), раунд 2 → `APPROVE`.

Контракт непрерывности соблюдён: **одна Ultrabrain-сессия на весь цикл** — 6 раундов
коррекций плана и 2 раунда review шли в `ses_f4bfa5016ffeZh8BhXbDWnNLUD`.

### 2.2 Correction rounds (коррекции плана до и во время реализации)

| Раунд | Что вскрылось | Как решено |
|---|---|---|
| **1** | Ultrabrain закодировал «явный General» как sentinel `topic_id = -1` в `bridge_settings` — прямое нарушение binding-черновика (:32/:169/:185/:240) | Sisyphus поймал на compliance-проверке плана **до** старта реализации. General стал three-state через пару `(configured bool, topic_id nullable)`: `false,NULL` = unset, `true,NULL` = General, `true,N` = named. Sentinel удалён везде (enum `DestinationKind`), миграция добавляет две boolean-колонки |
| **2** | Неоднозначность порядка «скачивание медиа vs планирование публикации»; правила caption | Flow зафиксирован: **download ДО планирования**; download-failure = только warning-строка, никогда не OperationOutcome. Caption-ветка: полный текст ≤1024 + media → caption первой media-операции, TEXT-операций нет; иначе весь текст TEXT-операцией(-ями) ≤4096, media без caption. Никогда оба, никогда обрезка |
| **3** | Противоречие в форме хранения файлов на операциях | `PublicationOperation.file_path` заменён на `media: tuple[PlannedMedia, ...]` (0 для TEXT, 1 для одиночной media, 2–10 для группы); publisher удаляет все temp-файлы операции в per-op `finally` |
| **4** | `Publication.source` не принимал стену (circular import); правила группировки media | `PublicationSource = SourceMessage \| SourceWallPost` (type alias); `SourceWallPost` переехал в `value_objects.py`; группировка: фото/видео свободно миксуются в альбомах 2–10, chunk из 1 → одиночная операция, документы не группируются |
| **5** | Toggle broadcast: как уведомлять других owners с клавиатурой | Presentation-level broadcast: router сам шлёт `bot.send_message(other_owner, text, owner_main_keyboard(new_state))`; `TelegramNotifierPort` остаётся text-only (без утечки aiogram-типов в application-слой) |
| **6** | T17: план «валидация перед publish» устарел после задач 5/15/16 | Полный перевод `ForwardVkMessage`/`ForwardWallPost` на общий пайплайн; startup перестаёт быть фатальным при исчезнувшем destination (WARNING + runtime fallback); feature readiness вместо линейного gate; `PlanOutcome.failed_permanent` + attention-уведомления |

Каждый раунд: правки применялись Ultrabrain в план и скелеты, затем `make check` → EXIT=0.

### 2.3 Волны исполнения и рост тестового набора

| Волна | Задачи | Тесты после | Ключевые доводы |
|---|---|---|---|
| Скелеты | планирование | 501 | `make-check-skeleton-baseline.txt` |
| 1 | 1–4: миграция 0002, VK routing, readiness, notifier | 519 → 526 → 535 → 542 | `make-check-wave-1/task2`, `readiness-green`, `owner-notifier-green` |
| 2 | 5–8: planner+publisher, aliasing, downloader, composition | 562 → 592 → 606 → 623 | `make-check-wave-2a/t7/t6`, `pubplan-green`, `media-downloader-green`, `aliasing-green`, `composition-green` |
| 3 | 9–13: destination admin, Telegram UI (клавиатуры/root, регистрация+меню команд, настройки, визарды) | 633 → 642 → 659 → 662 → 672 | `make-check-t9…t13`, `destadmin-green`, `root-router-green`, `regmaster-green`, `settings-green`, `destwizard-green` |
| 4 | 14–16: VK UI dispatcher, ручная публикация, стена | 709 → 733 | `make-check-t14-t15/t16`, `vkui-manualpub-green`, `manualpub`/`wall-green` |
| 5 | 17–19: fallback+readiness wiring, курсор, диагностика | 742 → 755 → 763 | `make-check-t17/t18/t19`, `red-cursor`, `cursor-green` |
| 6 | 20–23: acceptance-харденинг, e2e, docs 01–06, деплой | 822 → 839 | `acceptance-finish`, `make-check-t20/t22/t23`, `deployment-artifacts` |
| 7 | 24: финальный sweep (миграции, PM2 dry, secrets, coverage) | 839 | `final-sweep`, `migration-cycle` |
| 8 | 25: owner manual gates | — | `owner-gates.md` (ожидает владельца) |
| Review-fixes | F1/F2/F3 фиксы + wiring-тесты | **847** | `make-check-fixes`, `red-wiring-fixes` |

Итог: `make check` — **EXIT=0, 847 passed, 6 deselected; coverage 90%; basedpyright 0 ошибок; ruff clean**.

---

## 3. Что сделано (по этапам roadmap)

| Roadmap stage | Содержание | Статус | Ключевые артефакты |
|---|---|---|---|
| **Этап 7** — Telegram Admin UI | ReplyKeyboard (8 кнопок), root/registration/settings/destinations routers, master `/start`→`/register`, command-menu scopes, owner broadcast, «Диагностика доставки», смена чата. Временные `/topics`/`/set_topic` удалены | ✅ | `presentation/telegram/**`, `infrastructure/telegram/command_menu.py`, `application/admin/destination_admin.py` |
| **Этап 8** — VK UI и ручная пересылка | `presentation/vk/` (session store, клавиатуры, dispatcher FSM): Help, CRUD алиасов, ручная пересылка одного сообщения, alias-shortcut, ordinal-only выбор, без 👍, stale-alias без General-fallback | ✅ | `presentation/vk/**`, `application/manual/**` |
| **Этап 9** — Wall и attachments | Нормализация `wall_post_new`, `ForwardWallPost`, downloader VK (photo/video/doc, 50MB pre-check), media-группы 2–10, caption-ветки, per-item warnings, частичный успех, `#изстенывк` + ссылка | ✅ | `infrastructure/vk/{mapper,media_downloader}.py`, `application/forwarding/{forward_wall,publication_planning,media_prep,composition}.py` |
| **Этап 10** — Reliability | General fallback (auto-потоки) + уведомление owners + 👍; feature-specific readiness; `failed_permanent`/`ambiguous` attention-уведомления; персистентный курсор + history gap; diagnostics `mark_reviewed`/`list_failed_terminal` | ✅ | `application/{readiness_features,notifications/owner_notifier}.py`, `infrastructure/vk/cursor.py`, `infrastructure/db/repositories/delivery.py` |
| **Этап 11** — Acceptance hardening | US-10..22 распакованы в acceptance-файлы; guard `deferred.py` удалён и заменён на `test_all_stories_covered.py`; US-27 (no-config) добавлен; e2e расширение (opt-in) | ✅ | `tests/acceptance/**` (29 файлов), `tests/e2e/test_finish_smoke.py` |
| **Этап 12** — Deployment | `scripts/start.sh` (migrations→run), `ecosystem.config.cjs`, backup/restore SQLite, Makefile-цели, runbook, artifact-тесты | ✅ | `scripts/**`, `ecosystem.config.cjs`, `docs/deployment-runbook.md`, `tests/unit/test_deployment_artifacts.py` |

Проверка по плану: 26 из 29 чекбоксов `[x]`; не отмечены **задача 25** (owner), **F1** (закрывается
после задачи 25 по своему acceptance), **F3** (owner). Ничего из агентской части не осталось
незакрытым — подтверждено аудитом `f1-audit.txt`.

### 3.1 Ключевые архитектурные решения (реализовано)

- **General three-state без sentinel**: `(configured, topic_id)` — пара колонок миграции 0002;
  `DestinationKind` выводится в DTO; домен и UI никогда не видят sentinel-значений.
  General — полноценный destination (ручной выбор, alias, fallback).
- **Единый пайплайн публикации** для auto/стены/manual:
  `compose → prepare_media → append_warnings → plan_publication → reserve_delivery(intent) → begin_send → execute_plan(→publish_plan) → roll-up + 👍 (кроме manual/wall)`.
- **Fail-closed доставка**: `ambiguous` (сеть «зависла» после send intent) — терминальный статус,
  никогда не авто-ретраится; `review_required=1` + запись в диагностике; повторная публикация
  только вручную и осознанно.
- **Media-prep до планирования**: неудача скачивания/недоступность/oversize — это warning-строка
  в тексте публикации, но не операция; `OperationOutcome` — исключительно результат Telegram-вызова.
- **Per-call parse_mode**: глобальный HTML запрещён; HTML только на TEXT-операциях публикаций
  (pre-escaped композицией) и caption; все owner-тексты — plain.
- **Feature-specific readiness**: вместо линейного `FORWARDING_ENABLED` решения о пересылке
  принимаются по состоянию конкретной функции (`messages_auto_ready`, `wall_auto_ready`,
  `manual_forwarding_ready`); «не настроено» — не ошибка, а тихий no-op (DEBUG-лог).
- **Курсор Long Poll**: `skip_old_events=False`, JSON-курсор в `runtime/vk_cursor/bot-polling/{group_id}.json`
  через override `handle_failed_event`; `failed=1/3` → history gap: WARNING + однократное
  уведомление owners без обещания точного числа пропущенных событий.
- **FSM**: Telegram — `FSMStrategy.GLOBAL_USER` (кросс-чат мастер регистрации), VK — ephemeral
  in-memory store по `from_id`; порядок роутеров инвертирован (root последним) + `SkipHandler`
  в state-гвардах, чтобы catch-all не съедал кнопки.

---

## 4. Дерево файлов (production-код)

`src/` — 95 Python-файлов, ~8 338 строк. Исключены `__pycache__` и тесты.

```text
src/vk_topic_bridge/
├── domain/
│   ├── enums.py                  (SourceType, AttachmentKind, PublicationStatus, ReactionStatus)
│   ├── errors.py                 (+ AttachmentTooLargeError, MediaUnavailableError)
│   ├── publication.py            (PublicationPlan, PublicationOperation.media, PlannedMedia, OperationOutcome)
│   ├── routing_policy.py         (classify_peer: DM < 2e9, conversation ≥ 2e9)
│   ├── value_objects.py          (+ PublicationSource, SourceWallPost переехал сюда)
│   ├── wall_post.py              (wall_source_key, wall_post_url + re-export)
│   └── policies/                 (+ без изменений: alias, attachment, delivery, forwarding)
├── application/
│   ├── readiness.py              (линейный gate — только startup-фазы)
│   ├── readiness_features.py     (+ derive_feature_readiness, snapshot_availability, unavailable_reason)
│   ├── errors.py                 (+ без изменений)
│   ├── admin/
│   │   ├── destination_admin.py  (SelectDestinationV2, ResetBridge, RefreshTopicsV2)
│   │   ├── refresh_topics.py     (действующий)
│   │   ├── register_chat.py      (действующий)
│   │   └── toggle_settings.py    (действующий)
│   ├── dto/
│   │   ├── settings.py           (+ DestinationKind, configured-флаги)
│   │   ├── delivery.py           (+ intent)
│   │   └── finish.py             (+ DeliveryReviewEntry, delivery_review_entry)
│   ├── forwarding/
│   │   ├── forward_message.py    (переписан на общий пайплайн + fallback + notifier)
│   │   ├── forward_wall.py       (новый: стена)
│   │   ├── publication_planning.py (новый: plan_publication)
│   │   ├── media_prep.py         (новый: prepare_media + warnings)
│   │   ├── plan_execution.py     (новый: reserve/begin/execute + PlanOutcome)
│   │   └── composition.py        (новый: manual/wall/warnings/split_text_safely)
│   ├── manual/
│   │   ├── aliasing.py           (ManualForwarding, AliasResolution, AliasManager)
│   │   └── publish_manual.py     (PublishManualMessage)
│   ├── notifications/
│   │   └── owner_notifier.py     (OwnerNotifier, fallback/attention/history-gap тексты)
│   └── ports/
│       ├── telegram_ex.py        (TelegramPublisherPlan, TelegramNotifierPort, VkMediaDownloaderPort)
│       ├── vk_ex.py              (VkManualUiPort)
│       └── repositories.py       (+ delete_chat, delete_all, mark_reviewed, list_failed_terminal)
├── infrastructure/
│   ├── db/
│   │   ├── models.py             (+ is_closed/is_hidden, configured-флаги, intent, UNIQUE_GENERAL_ALIAS_INDEX)
│   │   └── repositories/         (+ delete_chat, delete_all, mark_reviewed, list_failed_terminal)
│   ├── telegram/
│   │   ├── publisher.py          (+ publish_plan: media/api/группы/caption/cleanup)
│   │   └── command_menu.py       (новый: CommandMenuSynchronizer)
│   └── vk/
│       ├── mapper.py             (+ extract_forwarded_payload, map_manual_source, extract_wall_payload, map_wall_post)
│       ├── media_downloader.py   (новый: VkMediaDownloader)
│       └── cursor.py             (новый: RuntimePathBotPolling + history_gap_kind)
├── presentation/
│   ├── telegram/
│   │   ├── commands.py           (новый: описания команд и scope-интенты)
│   │   ├── filters.py            (новый: PrivateChat/GroupChat/DirectedAtThisBot)
│   │   ├── keyboards.py          (переписан: 8-кнопочная ReplyKeyboard)
│   │   ├── states.py             (новый: FSM states)
│   │   ├── errors.py             (заглушка — см. §9 долг)
│   │   └── routers/
│   │       ├── root.py           (новый: /start priority, /cancel, catch-all)
│   │       ├── registration.py   (новый: master FSM)
│   │       ├── settings.py       (новый: toggles, топики, диагностика, смена чата)
│   │       ├── destinations.py   (новый: визарды сообщений/стены)
│   │       └── register.py / start.py (совместимые шимы)
│   └── vk/
│       ├── states.py             (VkSessionStore, VkUiState)
│       ├── keyboards.py          (VK JSON-клавиатуры)
│       └── handlers.py           (VkUiDispatcher — полный FSM)
├── bootstrap/
│   ├── container.py              (переписан: вся сборка Stage 7–12)
│   ├── startup.py                (destination больше не фатален + command menu sync)
│   ├── shutdown.py               (+ закрытие aiohttp-сессии)
│   └── vk_consumer.py            (+ wall-ветка, ui_router, cursor, DM-routing)
└── __init__.py / __main__.py

migrations/versions/
├── 0001_initial.py               (Stage 2–6)
└── 0002_finish.py                (новый: availability, General-флаги, intent, alias-индекс)

scripts/  start.sh, backup_db.sh, restore_db.sh
ecosystem.config.cjs              (PM2, один fork, kill_timeout 15s)
Makefile                          (+ backup-db, restore-db)
config.py                         (+ VK_MEDIA_DIR, VK_CURSOR_DIR)
```

Тесты: 104 файла, ~17 653 строк, 747 тест-функций (344 unit + 270 integration + acceptance/e2e).
`tests/acceptance/` — 27 файлов `test_us*.py` + `test_all_stories_covered.py` + `test_stale_alias_and_general.py`.

### 4.1 Документация и .env

- **docs/01–06** синхронизированы с реализацией (354 insertions, 6 файлов; docs/07 не тронут).
- **docs/deployment-runbook.md** — новый (install, reboot/autostart, логи, backup/restore,
  runtime-пути, secrets hygiene, known limitations).
- **`.env.example` не изменился**: новые настройки `VK_MEDIA_DIR`/`VK_CURSOR_DIR` имеют
  дефолты в `config.py` (`runtime/media`, `runtime/vk_cursor`) и в `.env` не обязательны.

---

## 5. Проблемы цикла и как они решались

### 5.1 Sentinel `-1` в плане (пойман до реализации)

Ultrabrain при планировании закодировал «явный General» как sentinel `topic_id = -1`,
обосновав «одноколоночной frozen-схемой». Compliance-проверка Sisyphus'а против черновика
показала, что это прямое нарушение (:32/:169/:185/:240 — «no sentinel 0/-1») и что обоснование
фактически неверно (миграция 0002 может добавлять колонки). Коррекционный раунд 1 перевёл всё
на пару `(configured bool, nullable id)`. **Это лучший момент цикла**: дефект стоил одного
раунда правок плана вместо переделки миграции и UI.

### 5.2 SQLite `batch_alter_table` дублирует constraints

Эмпирическая находка при написании миграции 0002: `op.batch_alter_table` на SQLite **сам**
отражает и копирует существующие constraints; если передать их в `table_args` — они дублируются.
Зафиксировано комментарием в миграции; consequent-правило в notepad: не переобъявлять
существующие constraints в batch-блоках.

### 5.3 План vs исходники vkbottle: точка перехвата history gap

План предписывал «обернуть `listen()` прокси-генератором, инспектирующим ключ `failed`».
Проверка по установленному vkbottle 4.11.0 (`vkbottle/polling/base.py`) показала: `listen()`
потребляет `failed`-события внутри `handle_failed_event` и **никогда не отдаёт их наружу**.
Реализован корректный observation point: override `handle_failed_event` (с вызовом `super()`)
+ per-episode dedup. Техническая коррекция задокументирована в `cursor-green.txt`.

### 5.4 Три wiring-дефекта, найденные только review-раундом

Прошли сквозь 800+ зелёных тестов, потому что тесты поднимали компоненты изолированно,
а не собранный `container.py`:

1. **CRITICAL — отсутствовал `fsm_strategy=FSMStrategy.GLOBAL_USER`.** При дефолтном
   `USER_IN_CHAT` ключ FSM = `(chat_id, user_id)`: private `/start` писал master-state под
   ключом лички, group `/register` читал под ключом группы → кросс-чат мастер регистрации
   был мёртв. Фикс: `build_dispatcher()` с явной стратегией.
2. **CRITICAL — root router включался ДО feature-роутеров.** Catch-all `F.text` глотал тексты
   кнопок меню и ординалы визардов (aiogram останавливает propagation на первом сработавшем
   handler'е). Фикс: порядок `registration → destinations → settings → root(last)` +
   `raise SkipHandler` в 9 state-гвардах (иначе два `^\d+$`-роутера взаимно глотаются).
3. **HIGH — ручная пересылка молча теряла контент.** Контейнер не собирал `source_resolver`:
   fallback строил SourceMessage из собственного текста DM (обычно пустого) → публикация
   из двух ссылок без текста и вложений, пользователю «Сообщение отправлено». Фикс:
   обязательный `source_resolver` (структурная гарантия), `extract_forwarded_payload` +
   `map_manual_source`; тихий fallback удалён полностью.

После фиксов добавлены **wiring-регрессионные тесты** (`test_dispatcher_wiring.py`),
валидированные мутационными пробами: возврат дефекта → тест падает (evidence `red-wiring-fixes.txt`).

### 5.5 Acceptance-набор нашёл продовый дефект

При написании `test_us12_unsupported.py` выяснилось, что `media_prep.prepare_media`
**молча выбрасывал неподдерживаемые вложения** — без warning-строки, что нарушало
AC-12.2/12.3. Исправлено: `MediaFailureReason.UNSUPPORTED` + строка предупреждения на элемент.

### 5.6 Тестовый hang и ложные RED

- `_sync_command_menu`, добавленный в startup, в lifecycle-тестах вызывал **реальный Bot API**
  (в тестах собирался контейнер с реальным `Bot`) → прогон вис. Фикс: `FakeCommandMenu`
  в тестовом контейнере.
- Попытка замокать `vkbottle.polling.BotPolling` (upstream-класс) вместо module-local символа
  привела к **реальному сетевому polling-циклу** в тесте. Правило: патчить только имя,
  импортированное в модуль.
- Первые RED-артефакты трёх задач (routing/notifier/fallback) изначально фиксировали баг
  тестового харнесса, а не отсутствие поведения. После этого введена практика **mutation probe**:
  временно ломаем проверяемую строку продового кода и убеждаемся, что тест падает по нужной
  причине; артефакт сохраняется, код немедленно восстанавливается. Аудит F1 позже нашёл
  три недостающих RED-файла и закрыл их именно этим способом.

### 5.7 Прочее (операционные мелочи)

- **pytest**: флаги должны идти ДО пути (`pytest -q ./tests/...` при `--cov` в addopts),
  иначе uv съедает аргументы и гоняется весь suite.
- **ruff format (py314)** переписывает `except (A, B):` → `except A, B:` (PEP 758) — принято как форма.
- **RUF001** (кириллические гомоглифы) — точечные `# noqa: RUF001` на конкретных строках.
- **CC Safety Net** заблокировал дважды: grep-паттерн со словом `.env` и проверку наличия
  dotenv-файла. Не обходилось; отражено в evidence.

---

## 6. Отклонения от плана

### 6.1 Технические коррекции плана (план был фактологически неверен)

| # | Отклонение | Обоснование |
|---|---|---|
| 1 | Курсор: override `handle_failed_event` вместо обёртки `listen()` | `listen()` в vkbottle 4.11.0 не отдаёт `failed` наружу (проверено по исходникам) |
| 2 | VK-клавиатуры: цвета `default/positive/negative`, не `secondary` | `secondary` отсутствует в актуальной vk-api-schema (проверено librarian); intent не изменился |

### 6.2 Review-driven фиксы (усиление контрактов)

| # | Отклонение | Обоснование |
|---|---|---|
| 3 | `source_resolver` стал обязательным параметром `VkUiDispatcher` | Структурная гарантия против тихой потери контента (скелет допускал optional); все construction-сайты обновлены |
| 4 | `SkipHandler` в state-гвардах + root последним | Без этого feature-роутеры не получают часть сообщений; изменение внутреннего мехнизма, не продукта |
| 5 | `build_dispatcher()` с `GLOBAL_USER` | План **требовал** GLOBAL_USER; это было исправление пропущенной реализации, а не отклонение |
| 6 | Linear `ReadinessPort` удалён из forwarding use cases | Решение round-6: линеный gate остаётся для startup/registration, пересылка — на feature readiness |

### 6.3 Решения по месту (в рамках плана)

| # | Решение | Обоснование |
|---|---|---|
| 7 | `DirectedAtThisBotFilter`: отклоняет любой `@other_bot`, включая вкомпонованный в токен команды (`/register@other_bot`) | Найдено при реализации T11; исходная реализация пропускала такие сообщения чужому боту |
| 8 | Повторный `/register` в зарегистрированном чате: тихая очистка scope + state, без ответа | Приведение к контракту «silent ignore» из доков/04 |
| 9 | `deferred.py` guard заменён на `test_all_stories_covered.py` | План допускал оба варианта; выбран позитивный guard (каждый US имеет acceptance-файл) |
| 10 | e2e-смоуки: `pytest.plugins`-skip при живом приложении и без credentials | Не деструктивность и не-вмешательство в боевой процесс |

---

## 7. Что проверено живьём и что нет

| Проверка | Статус |
|---|---|
| `make check` (полный) | ✅ EXIT=0, 847 passed, 90% coverage, повторено многократно |
| Миграции base→0001→0002→base→head | ✅ Идемпотентно, `migration-cycle.txt` |
| Backup→restore roundtrip на tmp-SQLite | ✅ revision после restore == head 0002 |
| PM2 dry-check (`node -e require(...)`, `bash -n`) | ✅ Без запуска приложения |
| Secrets hygiene (нет .env/session/db в git) | ✅ Проверено по git-истории и `.gitignore` |
| Wiring через реальный `Dispatcher.feed_update` | ✅ Независимые пробы ревьюера (P1/P2/P4/P5) |
| **Реальный VK→Telegram E2E** | ⏳ **Не выполнялся** (owner gates) |
| **Живой registration master в Telegram** | ⏳ Не выполнялся |
| **Живой Long Poll restart/PM2 reboot/cursor continuity** | ⏳ Не выполнялся |
| **Реальные медиа в Bot API (album, caption, 50MB)** | ⏳ Не выполнялся |
| **Живой history gap (failed=1/3)** | ⏳ Не наблюдался |
| **`.env` содержимое** | ⏳ Не читался агентом (CC Safety Net + политика) |

Полный чек-лист владельца (a)–(p) — в `.omo/evidence/finish-vk-topic-bridge/owner-gates.md`.

---

## 8. Что отходило от плана в процессе (сводка)

- 6 correction rounds (см. §2.2) — все правки внесены в план **до** реализации.
- План не предвидел 3 wiring-дефекта (см. §5.4) — исправлены в review-раунде, добавлены тесты.
- Acceptance-набор нашёл дефект `media_prep` (см. §5.5) — исправлен.
- Отклонения по месту — §6.3.
- Никаких изменений продуктового intent не происходило: спорный момент (sentinel) решался
  в пользу черновика, а не в пользу удобства реализации.

---

## 9. Где я не уверен, что работает (честный список)

Эти места либо не покрыты ничем, либо покрыты только фейками, либо зависят от внешних
контрактов, которые живьём не проверялись. Прусский порядок — от самого рискованного.

1. **Весь live-контур.** Ни один сетевой вызов после большого спринта не выполнялся.
   Вся сеть (Telegram Bot API, Telethon, VK Long Poll, VK API медиа) закрыта фейками/моками.
   Это главный риск; ровно поэтому существует задача 25.
2. **Кросс-чат master «/start в личке → /register в группе».** FSM-стратегия исправлена и покрыта
   wiring-тестом через `Dispatcher.feed_update`, но живой поток (права, тихий ответ, обновление
   меню команд) не проверен.
3. **Source resolver для пересланных вложений.** Реализация опирается на схему VK
   (`fwd_messages[]` — полные объекты с attachments), проверенную librarian'ом, но **живой
   Long Poll может прислать усечённую форму** (`is_cropped`). Если так — резолвер вернёт `None`,
   пользователь получит явную ошибку, но пересылка фото в ручном режиме не заработает.
4. **VK video без прямого URL.** Ветка «недоступно → warning-строка» реализована, но если
   VK начнёт отдавать `files` иначе, поведение не проверено живьём.
5. **Медиа в реальном Bot API**: лимиты (10 МБ фото на hosted, 50 МБ документ), поведение
   `send_media_group` (2–10, caption на первом item), слитные ошибки частичного успеха —
   всё это проверено моками aiogram, не живым API. Возможна коррекция лимитов.
6. **Персистентный курсор после PM2 reboot.** `ts_state_path` и restore покрыты юнит-тестами
   против установленного vkbottle 4.11.0, но живой re-start процесса (и тем более ребут)
   не наблюдался. Возможны сюрпризы с относительным путём (cwd под PM2).
7. **History gap**: однократность уведомления и отсутствие точного счёта — юнит-тесты;
   настоящего `failed=1/3` не было.
8. **Long-running dedup и конкурентность** — покрыты unit/integration С реальным SQLite, но
   под нагрузкой и при рестартах между инстансами не проверялись.
9. **Owner broadcast** при втором owner: если у него не открыт диалог с ботом, `send_text`
   упадёт; обработка изолирована (log+continue), но живой сценарий не проверялся.
10. **Command scopes**: реальные `setMyCommands`/`deleteMyCommands` в живом Bot API —
    e2e smoke требует credentials; логика покрыта mock-ботом.

Если что-то из этого списка сломается на ручном прогоне — это ожидаемо, не сюрприз:
для каждого пункта указаны признаки и вероятные причины.

---

## 10. Quality gates и метрики

| Метрика | Значение | Evidence |
|---|---|---|
| `make check` | **EXIT=0, 847 passed, 6 deselected** | `make-check-fixes.txt`, `make-check-f1.txt` |
| Coverage (`vk_topic_bridge`) | **90%** (3791 stmts, 302 missed, 726 branches) | там же, guardrail ≥80% |
| basedpyright | 0 ошибок | там же |
| ruff | clean (lint + format) | там же |
| Acceptance | 133 passed; 27 US-файлов; US-01..US-27 покрыты | `acceptance-finish.txt` |
| Тест-функции | 747 (344 unit + 270 integration + acceptance) | подсчёт по дереву |
| Миграции | base↔0002 цикл, идемпотентно | `migration-cycle.txt` |
| Deploy-артефакты | 17 статических тестов | `deployment-artifacts.txt` |
| Diff от baseline `8e26879` | 130 файлов, +13 592 / −1 031 | `git diff --stat` |
| Коммиты | 6 (см. §11) | `git log` |
| Evidence-каталог | 68 файлов | `.omo/evidence/finish-vk-topic-bridge/` |

---

## 11. Коммиты

Все коммиты прошли pre-commit hook (`make check`) и сделаны от имени владельца
(без co-authored-by — правило репозитория).

```
ba7759b feat(finish): схема 0002, модели и репозитории — General three-state, availability, intent
dfd7b49 feat(finish): реализация Stage 7–12 — UI, media, wall, fallback, cursor, диагностика
e07accd refactor(admin): удалить временные /topics и /set_topic
9c088e6 chore(deploy): скрипты запуска/бэкапа, PM2 и рунбук
28328f1 docs(finish): синхронизировать docs/01–06 с реализацией Stage 7–12
ba2faa9 chore(omo): план finish-vk-topic-bridge, notepads и evidence
```

**Не закоммичено** (осознанно): этот отчёт (`docs/stage-7-12-report.md`) — ждёт решения
владельца о коммите.

---

## 12. Что осталось сделать (рекомендации)

1. **Пройти owner gates (a)–(p)**; результаты внести в
   `.omo/evidence/finish-vk-topic-bridge/owner-gates.md`. Это закроет F1/F3 и позволит
   объявить проект завершённым.
2. **Приоритетно проверить живой E2E-контур:** `@all`/хештег → публикация + 👍; `/start`→`/register`;
   ручная пересылка (алиас и ординал); пост стены; fallback (закрыть/удалить целевой топик).
   Именно эти сценарии проверяют три wiring-фикса.
3. **Медиа-прогон**: фото/видео/документ ≤50 МБ, документ >50 МБ (warning-строка),
   альбом 2–10, видео без URL (если попадётся).
4. **PM2/reboot**: `pm2 save`/`pm2 startup` и ребут; убедиться, что курсор продолжил с
   сохранённого `ts` (файл `runtime/vk_cursor/bot-polling/{group_id}.json`).
5. **Мелкие долги (non-blocking, из review):**
   - `errors.py` — заглушка `@router.error`: решить, реализовать или удалить;
   - dead-параметр `publisher` в `PublishManualMessage`;
   - `vk_ex.py::VkMediaFacade = object` — мёртвый alias;
   - PEP 758 стиль `except A, B:` — вопрос вкуса (Python 3.14).
6. **После успешных гейтов**: коммит этого отчёта (если нужно), закрытие задачи 25
   и F1/F3 в плане.
7. **Если live-прогон вскроет расхождения контрактов** (VK payload, лимиты Bot API,
   media-формы) — следовать правилу: Librarian против официальных доков + pinned-версии,
   фиксация в evidence, эскалация при конфликте с планом.

---

## 13. Приложение: как читать evidence

| Префикс | Что внутри |
|---|---|
| `make-check-*` | Снимки полного `make check` по задачам/волнам (последний — `make-check-fixes`) |
| `red-*` | RED-доказательства TDD (падение до реализации или mutation probe) |
| `*-green.*` | GREEN-доказательства конкретных задач (команда + результат) |
| `production-diff.patch`, `production-files.txt` | Диффы для review от baseline `8e26879` |
| `review-fixes-round1.txt`, `red-wiring-fixes.txt` | Раунд 1 review: 3 блокера и их RED-пробы |
| `f1-audit.txt` | Аудит плана: чекбоксы, полнота RED/GREEN, закрытые пробелы |
| `final-sweep.txt`, `migration-cycle.txt` | Финальная проверка: миграции, PM2 dry, secrets, coverage |
| `owner-gates.md`, `owner-gates-readiness.txt` | Чек-лист владельца и проверка окружения |
| `scope-fidelity.txt` | Инварианты (нет FastAPI/Redis/inline/VK_SOURCE_PEER_ID/sentinel) |

---

*Отчёт подготовлен на основе плана, 68 evidence-артефактов, notepad'а сессии, шести commit-объектов
и итогов двух раундов независимого review. Все утверждения сверены с `make check` от 2026-09-19.*
