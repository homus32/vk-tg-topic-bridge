# VK Topic Bridge — Fix & Polish TODO

> **Назначение:** рабочий чек-лист следующего fix/polish цикла после live-тестирования 19.09.2026.
> **Источник истины по найденным проблемам:** исходный manual-testing report владельца.
> **Этот файл не заменяет Product Spec / User Stories / Technical Requirements.** Он задаёт порядок исправлений, зависимости, рекомендации по реализации и повторной проверке.
>
> Главный принцип цикла:
>
> ```text
> observe
> → reproduce
> → localize
> → regression test
> → fix
> → make check
> → live retest
> → mark done
> ```
>
> Не делать общий архитектурный refactor «заодно». Кодовая база уже существует; задача цикла — исправить доказанные live-дефекты и затем отполировать UX.


> **Mandatory Research Gate**
>
> Перед началом каждой задачи агент сначала исследует текущую реализацию и способ исправления.
> Если задача касается VK API, Telegram API, aiogram, VKBottle, Telethon, SQLite/SQLAlchemy или другого внешнего контракта — **обязательно использовать Librarian и официальную документацию/исходники актуальной версии**.
>
> До реализации агент должен зафиксировать:
>
> * как сейчас работает код;
> * подтверждённый внешний контракт;
> * предполагаемый root cause;
> * выбранный способ исправления;
> * риски и edge cases.
>
> Только после этого переходить к коду.
>
> Не реализовывать решение только по предположению или памяти модели.

---

## 0. Как работать с этим TODO

### Статусы

- [ ] не начато;
- [~] в работе;
- [x] закрыто и подтверждено;
- `[BLOCKED]` — нужна внешняя причина/решение владельца.

### Mandatory Research Gate — перед каждой задачей

Перед тем как менять код, агент обязан сначала провести короткое исследование.

- [x] Найти текущую реализацию и пройти реальный execution path задачи.
- [x] Определить, какой слой действительно владеет поведением и где должен находиться fix.
- [x] Если задача зависит от VK API, VKBottle, Telegram Bot API, aiogram, Telethon, SQLAlchemy/SQLite или другого внешнего контракта — **сначала использовать Librarian** и проверить актуальную документацию/исходники используемой версии.
- [x] Сопоставить внешний контракт с тем, что реально делает текущий код.
- [x] Зафиксировать предполагаемый root cause и evidence, который его подтверждает.
- [x] Продумать failure/recovery path и edge cases.
- [x] Только после этого писать regression test и реализацию.

**Запрещено:** начинать fix только по памяти модели, названию exception или первой правдоподобной гипотезе.

Для простых локальных UI/FSM-багов Librarian не обязателен, если внешний API/библиотечное поведение не участвует. Но чтение текущего кода и поиск root cause обязательны всегда.

### Definition of Done для любой задачи

Задача считается закрытой только если:

- [x] root cause понятен и записан в report/evidence;
- [x] есть regression test, если дефект воспроизводим без реальной сети;
- [x] `make check` зелёный;
- [x] если дефект был найден только live-тестом — выполнен соответствующий live retest;
- [x] исходный manual-testing report обновлён: BUG/CR/INV помечен итогом;
- [x] новые DEBUG-логи не содержат токены, session, proxy secret, authorization code или полный `.env`.

### Правило приоритета

```text
P0  наблюдаемость и диагностическая база
 ↓
P1  сломанный control plane
 ↓
P1  destination recovery / fallback reliability
 ↓
P1  wall/media data plane
 ↓
P2  FSM/контрактные дефекты
 ↓
P2  новые UX-фичи и inline UI
 ↓
P3  сетевой шум, deployment, полный regression
```

**Не начинать большой UI-polish, пока wall/media и registration recovery остаются красными.**

---

# CYCLE 6/7 — итог сессии (VK + Telegram UX redesign)

**Статус:** `[x]` Wave 6 и Wave 7 закрыты. Все задачи этой сессии реализованы, дополнительно улучшены в ходе живой проверки и подтверждены владельцем: всё проверено, протестировано и работает как требовалось.

Что сделано в этой сессии:

- VK: главное меню и alias root используют обычные text-кнопки; inline `Callback` — только для выбора топика.
- VK: выбор топика редактирует исходное сообщение и полностью убирает inline-клавиатуру.
- VK: inline topic picker не переводит пользователя в text-wait; `← Назад` возвращает в main, ввод номеров игнорируется.
- VK: `Отмена` редактирует сообщение в «Отмена» и сохраняет reply-клавиатуру текущего flow (alias menu или main).
- VK: Delete показывает только топики с алиасами; stale/удалённый callback редактирует исходное сообщение с ошибкой и убирает inline.
- VK: ручная пересылка — overlay поверх любого FSM: inline-only выбор топика, FSM не очищается, generic success не отправляется, alias shortcut сохранён (см. T8.4).
- Telegram: refresh экрана `Топики` показывает diff; inline destination selection редактирует исходное сообщение и убирает кнопки; Cancel-кнопка удалена; диагностика переименована в «Проблемы доставки».
- US-NEW-06 переведён в `[x]` без изменения реализации (фича уже была live-проверена владельцем).

**Источник истины:** этот файл — единственный актуальный чек-лист цикла. Отдельный `docs/vk-topic-bridge-cycle-6-7-report.md` удалён по решению владельца; `docs/tmp/` устарел и не должен использоваться. Итог Cycle 6/7 зафиксирован в этом разделе и в соответствующих WAVE-секциях ниже.

## FINAL PRODUCT POLISH — текущий цикл

Локальная реализация и regression-тесты завершены; live retest владельцем остаётся отдельным gate перед Final Regression.

- [x] VK/Telegram labels сокращены без изменения callback/FSM identity.
- [x] VK использует native `KeyboardButtonColor` для primary/positive/negative/secondary действий.
- [x] Telegram использует native `style` только при явном capability flag `TELEGRAM_BOT_API_BUTTON_STYLES_ENABLED`; default оставлен безопасным.
- [x] manual publication получает отдельный `#извк` без автоматического `#извкважно`.
- [x] automatic message и wall General fallback получают warning-блок над исходным контентом.
- [x] media/video warnings переведены на пользовательские формулировки и semantic markers.
- [x] delivery diagnostics показывает `Неясный результат` и `Ошибка доставки` вместо internal enum names.
- [x] VK Help объясняет только доступные пользователю manual forwarding и aliases; admin-only automatic settings не упоминаются.
- [x] alias-based manual forwarding возвращает VK success response с Telegram destination и topic title.
- [x] manual retry после недоступного topic оставляет только доступные inline destinations и Cancel.
- [ ] owner live retest product-polish checklist.

Framework-native статус цикла:

- VKBottle-native primitives: `Keyboard(inline=True/False)`, `Text`, `Callback`, `MessageEvent`/`MessageEventObject`, `GroupEventType.MESSAGE_EVENT`, `sendMessageEventAnswer` (snackbar), `messages.edit` (редактирование callback-сообщения), `Formatter`/`bold`.
- aiogram-native primitives: `Router.callback_query`, `CallbackData`/`CallbackData.filter`, `InlineKeyboardBuilder`, `CallbackQuery.answer()`, `Message.edit_text()`, `FSMContext.clear()`.
- Новые framework-over-framework abstractions не вводились; единая UI abstraction между VKBottle и aiogram не создавалась.

Осталось на будущий Framework Refactor (вне scope этого цикла):

- VK: `VkUiDispatcher` + in-memory `VkSessionStore` дублируют идеи `labeler`/`StateDispenser`, но runtime потребляет raw Long Poll поток и не создаёт `BotLabeler`; удаление требует отдельной runtime-миграции и анализа гонок/персистентности.
- VK: ordinal text fallback для destination оставлен как shipped-совместимость.
- Telegram: `RegistrationCoordinator` (owner lock) оставлен — `FSMContext` не моделирует межчатовый lock; text ordinal fallback в destinations также оставлен.

---

# WAVE 0 — P0 Observability first

**Статус первого цикла:** `[x]` registration/FSM, VK routing, forwarding, media и Telegram publication trace реализованы и покрыты targeted tests; live retest остаётся за владельцем.

## T0.1 — Добавить сквозной DEBUG trace для VK event pipeline

**Связано:** CR-001, US-NEW-04, BUG-008..011.

- [x] Логировать факт получения каждого поддерживаемого raw VK event.
- [x] Логировать `event_type`, `group_id`, безопасный event/source key.
- [x] Для `message_new` логировать `peer_id`, `from_id`, `conversation_message_id`, cropped lookup, количество attachments.
- [x] Для `wall_post_new` логировать `owner_id`, `post_id`, количество attachments.
- [x] Логировать результат classifier: `dm | conversation | wall | ignored`.
- [x] Логировать mapper outcome.
- [x] Логировать readiness decision и **причину** no-op.
- [x] Логировать выбранный destination.
- [x] Логировать reserve/begin/terminal delivery outcome.
- [x] Логировать публикационный plan: число операций и их типы, но не содержимое секретов/файлов.

**Рекомендация:** использовать `logger.bind()` и один стабильный набор полей:

```text
flow_id
source_type
source_key
vk_event_type
vk_peer_id
vk_from_id
vk_owner_id
vk_item_id
attachment_kind
destination_chat_id
destination_topic_id
delivery_id
operation_kind
```

`flow_id` не обязан храниться в БД. Для одного события достаточно детерминированного source key либо короткого correlation id.

**Важно:** не писать весь raw payload на `INFO`. Полный sanitized payload можно временно писать на `DEBUG`, но лучше иметь helper, который удаляет потенциально чувствительные поля и длинные URL query.

## T0.2 — Добавить отдельный media trace

**Связано:** BUG-008, BUG-009, BUG-010, INV-005.

Для каждого attachment:

- [x] исходный `kind` и безопасный индекс attachment;
- [x] identity не выводится в raw виде; access key не попадает в лог;
- [x] есть ли URL уже в payload/full message;
- [x] выполнялся ли дополнительный VK API lookup;
- [x] имя VK API метода;
- [x] тип токена/adapter path без вывода самого токена;
- [x] lookup success/failure + VK error code/class;
- [x] URL resolution success/failure без query-параметров;
- [x] известный размер и oversize decision;
- [x] download start/end;
- [x] HTTP status;
- [x] bytes downloaded;
- [x] temp path не выводится;
- [x] cleanup temp file.

**Рекомендация:** не превращать исключение в строку `«медиа недоступно»` слишком рано. Сначала логировать структурную техническую причину, затем уже переводить её в user-facing warning.

## T0.3 — Добавить registration/FSM trace

**Связано:** BUG-003, BUG-004, CR-012, CR-013.

- [x] owner начал registration;
- [x] acquisition/release registration session;
- [x] `/register` принят/отклонён и почему;
- [x] capability check result;
- [x] куда отправлен feedback: group/DM;
- [x] state before → state after;
- [x] `/cancel` инициатор;
- [x] success;
- [x] recoverable failure;
- [x] fatal failure.

**Правило:** recoverable error не должен выглядеть в логах как завершение FSM.

## T0.4 — Добавить INFO-логи только для значимых состояний

`INFO` не должен дублировать весь DEBUG.

- [x] startup завершён;
- [x] Telegram chat зарегистрирован/сброшен;
- [x] topics refresh завершён с количеством topics;
- [x] destination изменён;
- [x] toggle изменён;
- [x] automatic delivery published;
- [x] automatic delivery fallback → General (WARNING как degraded path);
- [x] ambiguous / failed_permanent (WARNING);
- [x] history gap;
- [x] wall event published;
- [x] graceful shutdown started/completed.

**Не логировать на INFO:** каждую кнопку, каждый SQL query, полный payload, URL медиа.

---

# WAVE 1 — P1 Registration & routing blockers

## T1.1 — BUG-003: missing capabilities не должен сам падать

- [x] Capability checker возвращает полный список missing permissions.
- [x] Если group reply невозможен — не делать `message.answer()` в group.
- [x] Отправлять owner список missing capabilities в ЛС.
- [x] Registration session остаётся активной.
- [x] Нет необработанного `TelegramBadRequest` в registration feedback path.

`[ ]` Live retest в реальной группе с недостаточными правами выполняет владелец.

**Рекомендация:** application use case должен возвращать structured result (`success | missing_capabilities | ...`), а presentation выбирает доступный канал ответа. Не прятать Telegram transport exception внутри бизнес-результата.

## T1.2 — BUG-004: registration recovery после recoverable error

- [x] После ошибки прав state не очищается.
- [ ] Вернуть права.
- [x] Повторный `/register` проходит **без нового `/start`**.
- [x] Временная Telegram API ошибка также не завершает session.
- [x] Session завершается только `success` или явным `cancel`.

**Regression test:** ошибка capabilities → затем success в том же FSM.

`[ ]` Live retest с реальным изменением прав выполняет владелец.

## T1.3 — BUG-005: убрать private catch-all из group context

- [x] `/asd` в group → полный silence.
- [x] неизвестный текст в group → silence, если нет явно разрешённого handler.
- [x] `/register` продолжает работать в допустимом registration context.
- [x] private owner catch-all остаётся только в DM.

`[ ]` Live retest group silence выполняет владелец.

**Рекомендация:** фильтровать context **до** catch-all. Не чинить специальным `if text == "/asd"`.

## T1.4 — CR-012 / US-NEW-01: эксклюзивная registration session

- [x] Одновременно только один owner владеет registration flow.
- [x] Owner B не может перехватить flow owner A.
- [x] `/register` от B ничего не меняет.
- [x] `/cancel` от B ничего не меняет.
- [x] lock освобождается success/cancel владельца flow.
- [x] restart сбрасывает in-memory registration session вместе с процессом.

`[ ]` Live retest competing owners выполняет владелец.

**Рекомендация:** так как регистрация — глобальная операция над одним Telegram-чатом, lock должен быть **глобальным для bridge**, а не только `GLOBAL_USER` FSM.

Допустим in-memory lock, если restart просто сбрасывает незавершённую registration session. Не добавлять Redis/новый сервис ради этого.

## T1.5 — CR-013 / INV-003: command scopes

После T1.1–T1.4:

- [x] mode OFF → `/register` не показывается;
- [x] mode ON → подсказка `/register` создаётся только для активного owner;
- [x] success/cancel → scope очищается;
- [x] backend owner-check остаётся независимо от command menu;
- [x] протестировать `/register` и `/register@BotUsername` на уровне regression tests;
- [x] проверить поведение в группе с несколькими ботами на уровне mention/filter tests.

`[ ]` Live retest реальных command scopes и нескольких ботов выполняет владелец.

**Рекомендация:** считать command scopes только UX-подсказками. Нельзя строить security на том, отображается команда или нет.

---

# WAVE 2 — P1 Destination self-healing & fallback reliability

## T2.1 — BUG-012: stale topic proof-send не должен ронять wizard

**Связано:** BUG-012, US-NEW-05, CR-004.

Сценарий уже подтверждён live: topic удалён или закрыт в Telegram, но остаётся в локальном кеше; при выборе proof-send Telegram возвращает `message thread not found` или `TOPIC_CLOSED`.

- [x] Воспроизвести сценарий с сохранённым stale topic.
- [x] Перехватить ожидаемую `PublicationRejectedError`, соответствующую отсутствующему thread/topic.
- [x] Не отправлять exception в общий aiogram error pipeline как необработанную пользовательскую ошибку.
- [x] Автоматически выполнить refresh topics через существующий Telethon path.
- [x] Обновить availability/cache.
- [x] Пометить исчезнувший topic unavailable/inactive.
- [x] Не сохранять stale topic как новый destination.
- [x] Оставить FSM в состоянии выбора destination.
- [x] Сразу показать owner актуальный список: General + доступные topics.
- [x] Дать понятный пользовательский feedback без traceback.

**Рекомендация:** не делать отдельный второй механизм refresh. Использовать тот же use case/service, который уже корректно обнаруживает удалённые topics при ручном `Обновить список`.

**Librarian/research:** проверить точную классификацию Telegram ошибки в текущих версиях aiogram/Bot API. Не завязываться только на текст exception, если библиотека даёт устойчивый error code/type/parameters.

### Regression cases

- [x] named topic существует → proof-send success → destination сохраняется;
- [x] topic удалён после кеширования → auto refresh → wizard продолжает работу;
- [x] General после recovery можно выбрать без `/cancel`;
- [x] другой named topic после recovery можно выбрать;
- [x] временная network/API ошибка не помечает topic удалённым без достаточного evidence;
- [x] старый destination не перезаписывается при failed proof-send.

---

## T2.2 — BUG-013: General fallback обязан уведомлять всех owners

Live-тест уже доказал:

- General fallback **работает**;
- owner notification **не работает**.

Проверить:

```text
ForwardVkMessage
→ fallback decision
→ OwnerNotifier
→ TelegramNotifierPort
→ broadcast owners
```

- [x] notifier действительно вызывается при fallback;
- [x] корректно используются `OWNER_IDS`;
- [x] notification отправляется каждому owner;
- [x] ошибка отправки одному owner не останавливает остальных;
- [x] notification содержит прежний destination;
- [x] notification явно говорит, что применён General fallback;
- [x] успех/неуспех notification не влияет на публикацию;
- [x] 👍 не зависит от broadcast результата.

`[x]` Live retest BUG-013 выполнен владельцем; локальный integration regression test пройден.

**Рекомендация:** broadcast должен иметь best-effort fan-out semantics. Ошибка одного recipient логируется отдельно, но не отменяет уже успешную delivery.

---

## T2.3 — CR-015: warning внутри самой fallback-публикации

**Статус:** реализовано; локальные regression-тесты зелёные, owner live retest остаётся в Final Regression.

Если CR утверждён:

- [x] warning является отдельным служебным блоком композиции;
- [x] исходный VK-текст остаётся неизменным;
- [x] warning сообщает имя или fallback identifier недоступного топика;
- [x] явно сообщает использование General;
- [x] блок находится сверху исходного контента;
- [x] тот же UX применяется для automatic wall fallback;
- [x] шаблон покрыт unit/acceptance regression tests.

**Рекомендация:** служебный warning ставить **над исходным контентом**, визуально отделять пустой строкой и не смешивать с пользовательским текстом.

Пример смысла:

```text
⚠️ Исходный топик «Важное» недоступен.
Сообщение автоматически отправлено в General.

<неизменённый исходный контент>
```

**OWNER DECISION:** CR-015 реализован отдельно от BUG-013; live acceptance остаётся открытой.

---

# WAVE 3 — P1 Wall pipeline

## T3.1 — BUG-011: сначала доказать получение `wall_post_new`

- [x] Проверить `groups.getLongPollSettings`/эквивалент и факт включения `wall_post_new`.
- [x] Проверить raw DEBUG: приходит ли событие вообще.
- [x] Если raw event не приходит — **не трогать mapper/use case**, сначала исправить VK group Long Poll settings.
- [ ] Если приходит — сохранить sanitized live fixture.

**Исследование:** `wall_post_new` является отдельным настраиваемым событием Bots Long Poll. Это нужно проверять так же рано, как `message_new`.

## T3.2 — BUG-011: пройти pipeline по слоям

Только если T3.1 доказал raw event:

- [x] raw consumer;
- [x] event classifier;
- [x] wall mapper;
- [x] `ForwardWallPost`;
- [x] wall readiness;
- [x] wall destination;
- [x] delivery ledger reserve;
- [x] publication composition;
- [x] plan;
- [x] Telegram publisher.

На каждом переходе должна быть одна DEBUG-точка.

## T3.3 — Wall text-only live acceptance

- [x] text-only post публикуется;
- [x] присутствует `#изстенывк`;
- [x] присутствует `https://vk.com/wall{owner_id}_{post_id}`;
- [x] destination правильный;
- [x] duplicate event не создаёт дубль;
- [x] wall toggle OFF блокирует публикацию.

**Не переходить к wall media, пока text-only wall не зелёный.**

---

# WAVE 4 — P1 Media pipeline

## T4.1 — INV-005: проверить общую причину media failures

До трёх отдельных фиксов:

- [x] получить live fixture одного сообщения с photo;
- [x] получить fixture с doc;
- [x] получить fixture с video;
- [x] сравнить, что именно mapper сохраняет из каждого attachment;
- [x] проверить `owner_id/id/access_key`;
- [x] проверить наличие URL в полном объекте сообщения;
- [x] проверить, не теряется `access_key` при преобразовании в domain DTO.

### Важное исследование

VKBottle рекомендует `Message.get_full_message()` перед работой с attachments: full message может дать рабочие `access_key` и более полный объект вложений.

**Рекомендация:** для входящих message attachments сначала использовать данные **full message/payload**, и лишь затем делать дополнительный `photos.getById`/`docs.getById`/`video.get`, если реально не хватает URL/метаданных.

## T4.2 — Проверить token/API compatibility lookup-методов

- [x] отдельно записать реальный результат `photos.getById`;
- [x] отдельно `docs.getById`;
- [x] отдельно `video.get`;
- [x] для ошибки записать VK error code и method;
- [x] не менять token model до получения live evidence.

### Нюанс из исследования

В открытой JSON schema VK API 5.199:

- `photos.getById` перечисляет `user`/`service` token types;
- `docs.getById` перечисляет `user`/`group`.

Это **не доказательство**, что именно это ломает текущий проект, но это сильный сигнал проверить token capability прежде, чем переписывать downloader.

**Запрещено:** молча добавлять пользовательский VK token как новый секрет, пока не доказано, что он действительно нужен продукту.

## T4.3 — BUG-008: Photo

- [x] сохраняется корректная attachment identity;
- [x] выбирается лучший разумный `sizes[].url`, если URL уже доступен;
- [x] при необходимости lookup работает;
- [x] download работает;
- [x] 1 photo → одиночная Telegram media operation;
- [x] 2/5 photo → album;
- [x] temp file удаляется после send;
- [x] user-facing warning нормальный, без `Фото «без имени»`.

**Рекомендация:** фото обычно не нуждается в искусственном `filename`. Для warning лучше `Фото не удалось перенести: <короткая причина>.`

## T4.4 — BUG-009: Document

- [x] `owner_id/id/access_key`;
- [x] title/filename;
- [x] size pre-check, если размер известен;
- [x] URL;
- [x] download;
- [x] ≤50 MB отправляется;
- [x] >50 MB не скачивается дальше/не отправляется;
- [x] warning содержит имя и лимит;
- [x] остальные части публикации продолжают отправляться.

## T4.5 — BUG-010: Video

- [x] `owner_id/id/access_key`;
- [x] `video.get` response залогирован структурно;
- [x] доступные direct file variants определены;
- [x] выбирается подходящий вариант;
- [x] если downloadable file нет — это normal partial-success warning;
- [x] остальные вложения и текст продолжают отправляться.

**Рекомендация:** не считать любое VK video гарантированно скачиваемым. Продуктовый контракт уже допускает warning вместо видео.

### Принятое решение владельца: best-effort video fallback

**Статус:** `[x]` реализовано и live-проверено владельцем.

Алгоритм для каждого VK video:

1. Если VK предоставляет поддерживаемый прямой `mp4` — скачать и отправить видео в Telegram.
2. Если прямого файла нет — не считать публикацию fatal: отправить текст с ссылкой `Открыть в VK`. Сначала использовать безопасно полученный `player`, иначе построить каноническую ссылку из `owner_id` и `id` (`https://vk.com/video{owner_id}_{id}`).
3. Если пригодной ссылки нет — сохранить текущий понятный warning и продолжить публикацию текста/остальных вложений.

Ограничения:

- ссылка ведёт к исходному VK-объекту и не переносит права доступа;
- пересланное видео не становится новой публичной копией;
- участник Telegram сможет открыть ссылку только если его VK-аккаунт имеет доступ к исходному видео;
- scraping, сторонние downloaders и обход приватности не добавляются.

Live retest владельца:

- [x] публичное видео с прямым `mp4` → Telegram video;
- [x] видео без `mp4`, но с `player` → Telegram link;
- [x] пересланное/ограниченное видео → проверить фактический доступ по ссылке;
- [x] auto, manual и wall используют один и тот же fallback;
- [x] текст и другие attachments продолжают отправляться при недоступном video.

## T4.6 — Общий media regression

- [x] 1 photo;
- [x] 2 photos;
- [x] 5 photos;
- [x] doc ≤50 MB;
- [x] doc >50 MB;
- [x] video;
- [x] unsupported audio;
- [x] unsupported voice;
- [x] unsupported video message;
- [x] mixed success/failure;
- [x] Telegram partial success сохраняет delivery semantics;
- [x] 👍 ставится, если логическая публикация создана несмотря на skipped attachment.

## T4.7 — Wall media после починки message media

- [x] wall photo;
- [x] wall several photos;
- [x] wall doc;
- [x] wall video;
- [x] warning behavior;
- [x] source link и `#изстенывк` не теряются.

**Рекомендация:** wall и message должны использовать один проверенный media-preparation слой. Не создавать второй downloader только для wall.

---

# WAVE 5 — P2 Existing FSM / contract bugs

## T5.1 — BUG-001: Back из topic settings

- [x] `← Назад` очищает вложенный state;
- [x] возвращает main owner menu;
- [x] не проходит в unknown-command catch-all;
- [x] повторный вход работает без `/cancel`.

## T5.2 — BUG-002: `/start` из submenu

- [x] `/start` всегда возвращает root/main state;
- [x] не сообщает ложное `Чат зарегистрирован`;
- [x] показывает `Главное меню`/актуальный summary;
- [x] клавиатура строится из текущего persisted state.

## T5.3 — BUG-006: Alias navigation

- [x] после add → обновлённый alias root;
- [x] после edit → обновлённый alias root;
- [x] после delete → обновлённый alias root;
- [x] Back alias root → VK main menu;
- [x] Help появляется только по явному запросу;
- [x] Add/Edit объединены одной кнопкой;
- [x] список топиков показывается перед add/edit/delete;
- [x] delete выполняется сразу после номера и сохраняет кнопку `Отмена`.

## T5.4 — BUG-007: manual publication initiator

- [x] publication различает original author и initiator;
- [x] оба профиля кликабельны;
- [x] отсутствующий/недоступный profile name имеет безопасный fallback;
- [x] видимая ссылка инициатора называется `Автор пересылки`;
- [x] manual idempotency semantics не ломаются.

Статус T5.1–T5.4: исправлено, покрыто regression tests и подтверждено live retest владельца.

## T5.5 — Сообщения от имени VK-сообщества

- [x] negative `from_id` получает профиль через `groups.getById`;
- [x] сообщение сообщества с `#hashtag` проходит automatic forwarding;
- [x] сообщение сообщества с `@all` проходит automatic forwarding;
- [x] `#hashtag` и `@all` создают одну публикацию и одну реакцию;
- [x] профиль автора-сообщества и initiator ручной пересылки не смешиваются.

Статус T5.5: исправлено, покрыто end-to-end regression tests и подтверждено live retest владельца.

---

# WAVE 6 — P2 VK UX redesign

**Статус:** `[x]` закрыто; итог и дополнительные улучшения сессии — в разделе CYCLE 6/7 выше.

## T6.1 — Разделить VK text menus и inline topic selection

**Связано:** CR-008, INV-004, US-UPDATE-17.

- [x] включить/проверить VK Long Poll event `message_event`;
- [x] добавить обработку `GroupEventType.MESSAGE_EVENT`;
- [x] использовать обычные `Text` actions для главного меню и alias root;
- [x] использовать `Keyboard(inline=True)` и `Callback` только для выбора topic;
- [x] payload содержит стабильный `action` и минимально необходимый id;
- [x] callback проверяет `from_id/peer_id` и актуальность состояния;
- [x] после callback всегда завершать event response (`show_snackbar`, edit/send и т.п.), чтобы кнопка не «крутилась»;
- [x] cancel topic selection убирает inline keyboard и сохраняет reply-клавиатуру текущего flow;
- [x] stale callback даёт понятный snackbar/новый экран;
- [x] double click идемпотентен.

### Подтверждено исследованием

VKBottle штатно поддерживает:

```python
Keyboard(inline=True)
Callback(...)
GroupEventType.MESSAGE_EVENT
MessageEvent
event.show_snackbar(...)
event.message_edit(...)
event.message_send(...)
```

Главное меню и alias root сохраняют text-button UX; inline используется только для выбора topic.

### Консервативный дизайн

Чтобы не упираться в лимиты клиента/API:

- держать inline screen до ~10 actions;
- не делать payload длинным;
- использовать короткие action codes и numeric ids;
- большие topic lists делать страницами/следующим сообщением, а не огромной одной клавиатурой.

## T6.2 — Новый VK Alias root

Пример UX-смысла:

```text
Алиасы

General — гл
Разработка — dev
Новости — не задан

[ Добавить ]
[ Изменить ] [ Удалить ]
[ ← Назад ]
```

- [x] `Добавить/Изменить` text button;
- [x] `Удалить` text button;
- [x] `Назад` text button;
- [x] topic selection после действия использует callback buttons;
- [x] inline topic picker сохраняет `ALIAS_MENU` и не переводит пользователя в ordinal/text wait state;
- [x] `← Назад` во время inline topic picker обрабатывается как alias-menu navigation;
- [x] Delete inline picker показывает только доступные topics с существующими aliases;
- [x] stale/removed Delete callback редактирует исходное сообщение с ошибкой и полностью убирает inline keyboard;
- [x] обычные menu actions сохраняют исходный text-button UX;
- [x] после mutation экран обновляется сразу.

## T6.3 — Topic selection в VK через callback buttons

- [x] General;
- [x] named topics;
- [x] unavailable исключены/помечены;
- [x] stale topic callback безопасно отклоняется;
- [x] большой список: paging не потребовался — текущие списки топиков помещаются на экран; решение пересматривается только при реальном росте списка;
- [x] при выборе сохраняется именно internal topic id из payload, а не label.

## T6.4 — Rich text VK через встроенный VKBottle Formatter

**Это больше не research-only: VKBottle документирует поддержку.**

Доступны:

- `bold`;
- `italic`;
- `underline`;
- `url`;
- комбинации;
- `Formatter(...).format(...)`;
- `Format`;
- `format_data`;
- отправка formatted object напрямую через `message.answer(...)`.

- [x] сделать маленький live spike в тестовом DM;
- [x] проверить desktop;
- [x] проверить mobile;
- [x] проверить кириллицу + emoji;
- [x] проверить ссылки;
- [x] после этого использовать `Formatter` в VK selection/alias templates без собственного parser.

Форматирование подтверждено владельцем в рамках финальной live-проверки цикла: всё работает как требуется.

**Рекомендация:** не писать свой Markdown parser. Сначала использовать `vkbottle.tools.formatting`.

## T6.5 — Единые VK message templates

- [x] success;
- [x] warning;
- [x] error;
- [x] main menu;
- [x] alias menu;
- [x] selection;
- [x] help;
- [x] manual forwarding success.

Правила:

- короткий заголовок;
- пустая строка между смысловыми блоками;
- важное выделяется `bold`;
- ссылки оформляются через `url`;
- emoji используются как семантические маркеры, а не декор в каждой строке;
- технические ids пользователю не показываются.

---

# WAVE 7 — P2 Telegram UX changes

**Статус:** `[x]` закрыто; итог и дополнительные улучшения сессии — в разделе CYCLE 6/7 выше.

## T7.1 — CR-003: переработать topic management

**Рекомендованное решение:** объединить «список» и refresh вокруг одного экрана `Топики`.

После refresh показывать:

- [x] актуальные cached topics;
- [x] added;
- [x] removed;
- [x] unavailable;
- [x] текущий messages destination;
- [x] текущий wall destination;
- [x] `Изменений нет`, если diff пуст.

Не заставлять owner гадать, сработал refresh или нет.

## T7.2 — CR-004 / US-UPDATE-05: inline destination keyboard Telegram

Это **осознанное изменение старого требования ReplyKeyboard-only**.

- [x] General callback;
- [x] named topic callbacks;
- [x] unavailable safe reject;
- [x] stale callback;
- [x] callback другого owner;
- [x] старое сообщение;
- [x] double click;
- [x] Back;
- [x] Cancel;
- [x] current destination clearly shown.

**Рекомендация:** callback_data хранит operation + destination identity, а не название топика.

**OWNER DECISION (Cycle 6/7):** inline-кнопка «Отмена» удалена из destination selection как ненужная; успешный выбор топика редактирует исходное сообщение и полностью убирает inline-клавиатуру, текст сообщения сообщает выбранный топик.

## US-NEW-06 — Связывать отдельный документ с media-сообщением

**Статус:** `[x]` реализовано и live-проверено владельцем.

### User story

Как владелец, я хочу, чтобы документ из одной VK-публикации был отдельным Telegram-сообщением,
но отвечал на предыдущее media-сообщение этой же публикации, чтобы было понятно, к каким фото
или видео он относится.

### Acceptance criteria

- [x] `PHOTO`/`VIDEO` продолжают отправляться по действующим правилам album: mixed `PHOTO + VIDEO`
  допустим, `DOCUMENT` в этот album не добавляется.
- [x] `DOCUMENT` отправляется отдельным `send_document` сообщением.
- [x] Если в публикации уже отправлено `PHOTO` или `VIDEO`, первый документ отвечает на последнее
  Telegram-сообщение, созданное предыдущей media-operation этой публикации.
- [x] При нескольких документах каждый следующий документ отвечает на непосредственно предыдущее
  Telegram-сообщение этой же логической публикации.
- [x] Reply использует Telegram message id из фактического результата отправки, а не VK id.
- [x] Если предыдущая media-operation не создала Telegram-сообщение, документ отправляется без
  несуществующего reply, а публикация сохраняет partial-success semantics.
- [x] Если фото/видео в публикации нет, существующее поведение отдельного документа не меняется.
- [x] Поведение одинаково для automatic message, manual forwarding и wall post через общий
  publication planner/publisher.
- [x] Для reply-связи добавлены regression tests, включая один документ, несколько документов,
  отсутствие предыдущего сообщения и failed previous operation.

**Ограничение Telegram API:** это логическая связь через reply, а не попытка создать один mixed
album `DOCUMENT + PHOTO/VIDEO`; такой album Bot API не поддерживает.

## T7.3 — CR-005 / US-NEW-02: proof-send для General

В manual-testing report это сформулировано как новый intent.

- [x] General получает такой же реальный proof-send;
- [x] destination сохраняется только после success;
- [x] failure не изменяет persisted destination;
- [x] owner получает понятную ошибку.

**Предположение этого TODO:** CR-005 считается утверждённым. Если владелец передумает — снять задачу до реализации.

## T7.4 — CR-006: единый cancel feedback

- [x] registration: `Регистрация Telegram-чата отменена.`;
- [x] destination selection;
- [x] change-chat;
- [x] другие mutable FSM.

Cancel:

1. ничего частично не сохраняет;
2. очищает state;
3. показывает следующий понятный экран.

## T7.5 — CR-007: переименовать диагностику

**Рекомендация:** функцию не удалять. Она нужна для fail-closed `ambiguous`.

Предлагаемое имя:

```text
Проблемы доставки
```

В root screen добавить коротко:

```text
Здесь показаны доставки, которые требуют ручной проверки.
Автоматический повтор неоднозначных отправок не выполняется, чтобы не создать дубль.
```

- [x] понятный empty state;
- [x] ambiguous explanation;
- [x] failed_permanent explanation;
- [x] mark reviewed только где допустимо.

**OWNER DECISION:** если владелец всё-таки хочет убрать кнопку из main menu, сам use case/историю лучше сохранить.

---

# WAVE 8 — P2 Manual forwarding UX

## T8.1 — CR-009: success сообщает destination

**OWNER DECISION (Cycle 6/7, live-проверено):** отдельное success-сообщение `Сообщение отправлено.` не отправляется (оно ломало активный FSM). После выбора топика кнопкой исходное сообщение редактируется в `Выбран топик "<имя>"`; при ручной пересылке через alias shortcut дополнительных сообщений не отправляется вовсе.

- [x] destination сообщается через редактирование исходного сообщения (`Выбран топик "<имя>"`), а не отдельным success-сообщением;
- [x] General и named topic показываются одинаково — именем выбранного топика;
- [x] имя топика берётся из фактически выбранного destination, не из старого UI state.

## T8.2 — CR-010: новый manual publication template

**Статус:** `[x]` реализовано и live-проверено владельцем. Текущий формат: ссылка на original author → исходный текст → ссылка-подпись `Автор пересылки` на initiator. Реализация: `application/forwarding/composition.py::compose_manual_publication`; покрыто `tests/unit/application/test_composition.py`.

Минимальный смысл:

```text
Автор: <original VK profile>
Переслал: <initiator VK profile>

<исходный текст>
```

- [x] original author;
- [x] initiator;
- [x] исходный текст;
- [x] attachments;
- [x] warnings;
- [x] служебные метки;
- [x] не переносить reply context;
- [x] не разворачивать nested forwards;
- [x] manual никогда не ставит 👍.

**Примечание:** «служебные метки» для manual — ссылки профилей (`Автор` / `Автор пересылки`) и отдельный service tag `#извк`.

## T8.3 — CR-011: `#извк` для manual

**Статус:** реализовано и покрыто локальным regression; owner live retest остаётся открытым. `compose_manual_publication` добавляет отдельный `#извк` и не наследует `#извкважно` из `@all`.

- [x] добавить `#извк`;
- [x] не добавлять `#извкважно` автоматически только потому, что исходный forward содержит `@all`;
- [x] regression auto flow не ломается.

**Предположение этого TODO:** новый intent `#извк` для manual считается утверждённым.

## T8.4 — CR-012: manual forwarding overlay и inline-only destination

- [x] ровно одно forwarded message перехватывается поверх любого текущего VK FSM;
- [x] текущий FSM не очищается и не заменяется состоянием manual forwarding;
- [x] destination после обычной пересылки выбирается только inline callback-кнопкой;
- [x] текстовый номер topic во время manual picker игнорируется без ответа и публикации;
- [x] после callback исходное сообщение редактируется в `Выбран топик "<имя>"`;
- [x] отдельное generic-сообщение `Сообщение отправлено.` не отправляется;
- [x] после manual callback можно продолжить исходный alias/FSM flow;
- [x] известный alias в сопровождающем тексте пересылки остаётся рабочим shortcut.
- [x] alias shortcut после успешной manual publication получает отдельный VK success response с destination/topic.
- [x] manual `telegram_topic_not_found` показывает retry destinations без недоступного topic.

---

# WAVE 9 — P3 Network investigations / shutdown

## T9.1 — INV-001: `Server closed the connection...`

Исследование уже сузило источник: такая формулировка характерна для **Telethon network connection layer**.

- [ ] подтвердить logger name/module в вашем runtime;
- [ ] записать transport: direct / SOCKS5 / MTProto proxy;
- [ ] проверить, происходит ли reconnect;
- [ ] проверить, теряется ли доступ к topic refresh;
- [ ] проверить частоту warning;
- [ ] проверить корреляцию с proxy;
- [ ] только после этого решать, менять ли level/filter/reconnect policy.

**Не делать:** просто `logger.disable("telethon")`.

## T9.2 — INV-002: shutdown `Failed to fetch updates`

Aiogram polling сам ловит network errors и retry/backoff'ит их. Поэтому сообщение во время shutdown может быть гонкой: HTTP session уже закрывается, а polling loop ещё успел сделать очередной `getUpdates`.

- [ ] instrument shutdown stages;
- [ ] stop Telegram polling;
- [ ] дождаться polling task;
- [ ] затем закрыть bot HTTP session;
- [ ] затем прочие adapters;
- [ ] проверить повторно.

**Цель:** сначала исправить ordering, а не скрывать лог.

---

# WAVE 10 — P3 Remaining acceptance / untouched cases

## T10.1 — Alias full validation

- [ ] delete;
- [ ] duplicate;
- [ ] case-insensitive duplicate;
- [ ] spaces;
- [ ] reserved word;
- [ ] General alias;
- [ ] stale alias;
- [ ] navigation.

## T10.2 — Toggle live behavior

- [ ] @all OFF действительно блокирует;
- [ ] hashtag OFF действительно блокирует;
- [x] wall OFF действительно блокирует;
- [x] обратно ON восстанавливает;
- [ ] second-owner notification.

## T10.3 — Auto filter semantics

- [x] plain text → no publication;
- [x] hashtag → one publication;
- [x] @all → one publication;
- [x] @all + hashtag → **one**, не две;
- [x] service tags корректны;
- [x] 👍 после success.

## T10.4 — `is_cropped`

- [ ] fixture/live event;
- [ ] full message fetched;
- [ ] filters считаются по full message;
- [ ] attachments берутся из full message;
- [ ] source identity не меняется.

## T10.5 — Fallback

- [x] удалить/закрыть configured named topic;
- [ ] automatic message → General;
- [x] wall → General;
- [x] owner notification;
- [ ] 👍 для message success;
- [ ] ledger destination = General;
- [ ] manual selected named topic → error, **без fallback**.

## T10.6 — Diagnostics terminal outcomes

- [ ] ambiguous;
- [ ] failed_permanent;
- [ ] details;
- [ ] known Telegram message ids;
- [ ] review_required;
- [ ] mark reviewed;
- [ ] no automatic retry ambiguous.

## T10.7 — Idempotency / replay

- [ ] duplicate auto message event;
- [x] duplicate wall event;
- [ ] cursor restart replay;
- [ ] published short-circuit;
- [ ] ambiguous short-circuit;
- [ ] manual repeated intentional forward остаётся отдельным intent.

## T10.8 — PM2 / reboot / persistence

- [ ] PM2 start;
- [ ] PM2 restart;
- [ ] `pm2 save`;
- [ ] startup;
- [ ] reboot;
- [ ] DB сохранилась;
- [ ] Telethon session сохранилась;
- [ ] VK cursor сохранился;
- [ ] приложение само поднялось.

## T10.9 — Backup / restore

- [ ] backup;
- [ ] restore;
- [ ] Alembic revision head;
- [ ] startup after restore;
- [ ] settings/topics/aliases/delivery data ожидаемо восстановлены.

## T10.10 — Long-running stability

- [ ] минимум один длительный прогон;
- [ ] нет роста temp media;
- [ ] нет утечки aiohttp sessions;
- [ ] нет лавины reconnect logs;
- [ ] cursor продолжает обновляться;
- [ ] wall/message events продолжают приниматься;
- [ ] DB не уходит в устойчивый lock/contention.

---

# 10. Финальный regression gate

Закрывать fix cycle только когда:

- [x] `make check` зелёный;
- [ ] registration happy path;
- [ ] registration missing-rights recovery;
- [ ] competing owner protection;
- [ ] group unknown commands silent;
- [x] Telegram Back/start FSM;
- [x] topic refresh transparent (owner live-проверка Cycle 6/7);
- [x] named + General proof-send (локальные regression tests и live-проверка владельца);
- [x] stale topic selection → automatic refresh → wizard recovery (локальные regression tests и live-проверка владельца);
- [x] invalid/stale topic никогда не сохраняется;
- [x] General fallback уведомляет всех owners (локальный integration regression test и live-проверка владельца);
- [ ] fallback publication warning, если CR-015 утверждён;
- [x] VK alias add/edit/delete;
- [x] VK inline/callback UI;
- [x] VK formatted text live-tested;
- [x] manual inline destination callback;
- [x] manual by alias shortcut;
- [x] manual overlay preserves the active VK FSM;
- [x] manual initiator metadata;
- [x] auto text;
- [x] photo;
- [x] media group;
- [x] document;
- [x] oversize document;
- [x] video or correct partial-success warning;
- [x] wall text;
- [x] wall media;
- [x] fallback;
- [ ] diagnostics;
- [ ] duplicate protection;
- [ ] PM2 restart/reboot;
- [ ] backup/restore;
- [ ] no known Critical/Major defect without explicit owner acceptance.

---

# 11. Решения владельца, которые не должны блокировать первые волны

Первые WAVE 0–4 можно выполнять без дополнительных решений.

Перед WAVE 5–7 стоит проверить следующие product decisions:

1. **General proof-send** — в этом TODO считается утверждённым.
2. **`#извк` для manual forwarding** — в этом TODO считается утверждённым.
3. **Telegram inline destination selection** — считается утверждённым новым требованием, несмотря на старый ReplyKeyboard-only контракт.
4. **VK inline/callback UI** — считается утверждённым.
5. **VK rich formatting** — считается утверждённым как UX-polish. Использовать встроенный VKBottle formatting, а не самописную разметку.
6. **«Диагностика доставки»** — РЕШЕНО в Cycle 6/7: capability сохранена в main menu и переименована в `Проблемы доставки`, добавлены объяснения ambiguous/failed_permanent (см. T7.5).
7. **CR-015 — warning внутри General fallback publication** — пока считать отдельным owner decision. Рекомендация: отдельный служебный блок **над** неизменённым исходным текстом; тот же принцип разумно применить и к wall fallback, если owner это подтвердит.

---

# 12. Research notes для агента

## Telegram stale topic recovery

Live-тест подтвердил конкретный recovery case: локальный topic cache может устареть после удаления thread в Telegram, а proof-send возвращает `message thread not found`.

Практический вывод:

```text
proof-send says topic/thread missing
→ НЕ сохранять destination
→ refresh topics через существующий Telethon path
→ пометить stale topic unavailable
→ оставить FSM в selection state
→ показать актуальный список
```

Перед реализацией агент должен через Librarian проверить, какой устойчивый exception/error classification доступен в используемой версии aiogram/Bot API. Не полагаться без необходимости только на string matching текста ошибки.

---

## VK inline/callback — подтверждено

VKBottle documentation:

- `Keyboard(inline=True)`;
- action `Callback`;
- `GroupEventType.MESSAGE_EVENT`;
- `MessageEvent`;
- `show_snackbar`;
- `message_edit`;
- `message_send`.

Практический вывод: callback UI может менять экран без отправки пользователем мусорного текстового сообщения в диалог.

Sources:

- https://vkbottle.readthedocs.io/ru/latest/tools/keyboard/
- https://vkbottle.readthedocs.io/ru/latest/tools/message-event/

## VK formatting — подтверждено

VKBottle `Formatter` / `Format` поддерживает:

- bold;
- italic;
- underline;
- url;
- `format_data`;
- прямую отправку formatted object через `message.answer`.

Source:

- https://vkbottle.readthedocs.io/ru/latest/tools/formatting/

**Не нужен отдельный Markdown parser для текущего scope.**

## VK full message для attachments

VKBottle 4.3+ документирует `Message.get_full_message()` как способ получить полное сообщение и рабочие `access_key`, особенно для attachments.

Source:

- https://vkbottle.readthedocs.io/ru/latest/whats_new/4.3/

Практический вывод: до дополнительного lookup сначала проверить full message.

## VK media API token nuance

Открытая схема VK API 5.199 показывает разные token capabilities для media lookup методов. В частности:

- `photos.getById`: user/service;
- `docs.getById`: user/group.

Sources:

- https://github.com/VKCOM/vk-api-schema/blob/master/photos/methods.json
- https://github.com/VKCOM/vk-api-schema/blob/master/docs/methods.json

Это **диагностическая подсказка, не готовый root cause**. Проверять реальный pinned API/VKBottle live-вызовом.

## `wall_post_new` / `message_event`

Оба события требуют соответствующей Long Poll event configuration.

Sources:

- https://github.com/VKCOM/vk-php-sdk/blob/master/README.md
- https://github.com/VKCOM/vk-php-sdk/blob/master/src/VK/Actions/Groups.php

Практический вывод:

```text
нет raw event
→ проверяем VK Long Poll settings
→ только потом код pipeline
```

## Aiogram polling noise

Aiogram intentionally ловит ошибки `getUpdates`, пишет `Failed to fetch updates`, делает backoff и продолжает polling.

Source:

- https://github.com/aiogram/aiogram/blob/dev-3.x/aiogram/dispatcher/dispatcher.py

Поэтому shutdown error сначала проверять как ordering/race, а не глушить logger.

## Telethon connection warning

Фраза `Server closed the connection: ... bytes read ...` встречается непосредственно в Telethon network connection/MTProto flow.

Практический вывод: первым делом подтвердить logger/module и transport; не глушить весь Telethon logger.

---

# 13. Анти-паттерны этого fix cycle

Агенту **не делать**:

- [ ] общий переписанный architecture layer без конкретного BUG/CR;
- [ ] новый framework;
- [ ] Redis/Celery/RabbitMQ/Kafka;
- [ ] пользовательский VK token «на всякий случай»;
- [ ] три разных media pipeline для message/manual/wall;
- [ ] swallowing `except Exception` без structured log;
- [ ] suppress network warning до root cause;
- [ ] UI polish до зелёного wall/media;
- [ ] считать unit/acceptance test заменой live retest для дефекта, который проявлялся только на реальном API;
- [ ] менять старые продуктовые контракты молча — новые требования должны оставаться помеченными как CR/US-update.

---

# 14. Рекомендуемый порядок коммитов

Не обязательно один commit на один checkbox, но держать изменения небольшими:

```text
1. chore(observability): add structured live pipeline traces
2. fix(registration): preserve flow on missing permissions
3. fix(telegram): isolate group routing and registration lock
4. fix(destinations): recover stale topics and restore fallback notifications
5. fix(wall): restore wall_post_new ingestion and text pipeline
6. fix(media): repair attachment identity and download pipeline
7. fix(ui): repair telegram/vk FSM navigation
8. feat(vk-ui): inline callback menus and rich formatting
9. feat(telegram-ui): topic management and inline destinations
10. feat(manual): publication template and success feedback
11. fix(runtime): shutdown/network cleanup
12. test(live): close remaining regression gates
```

Так проще откатывать ошибочную гипотезу и понимать, какой commit сломал live behavior.


> Если ты это видишь — напомни мне что нужно решить что делать с оставшимся # TODO от ultrabrain 
> которые были не имплементированы по какой то причине. Их нужно сделать или удалить? Нужно 
> обязательно читать прошлые plans и использовать reflect.
