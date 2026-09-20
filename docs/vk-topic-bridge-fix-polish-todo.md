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
- [ ] если дефект был найден только live-тестом — выполнен соответствующий live retest;
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
- [ ] есть ли URL уже в payload/full message;
- [ ] выполнялся ли дополнительный VK API lookup;
- [ ] имя VK API метода;
- [ ] тип токена/adapter path без вывода самого токена;
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

**Статус:** product decision / не смешивать с BUG-013.

Если CR утверждён:

- [ ] warning является отдельным служебным блоком композиции;
- [ ] исходный VK-текст остаётся неизменным;
- [ ] warning сообщает имя/идентификатор недоступного destination;
- [ ] явно сообщает использование General;
- [ ] определить положение блока: сверху или снизу;
- [ ] отдельно решить, применяется ли тот же UX для wall fallback;
- [ ] шаблон покрыт snapshot/unit test.

**Рекомендация:** служебный warning ставить **над исходным контентом**, визуально отделять пустой строкой и не смешивать с пользовательским текстом.

Пример смысла:

```text
⚠️ Исходный топик «Важное» недоступен.
Сообщение автоматически отправлено в General.

<неизменённый исходный контент>
```

**OWNER DECISION:** CR-015 не считать реализуемым автоматически только потому, что BUG-013 исправляется рядом.

---

# WAVE 3 — P1 Wall pipeline

## T3.1 — BUG-011: сначала доказать получение `wall_post_new`

- [ ] Проверить `groups.getLongPollSettings`/эквивалент и факт включения `wall_post_new`.
- [ ] Проверить raw DEBUG: приходит ли событие вообще.
- [ ] Если raw event не приходит — **не трогать mapper/use case**, сначала исправить VK group Long Poll settings.
- [ ] Если приходит — сохранить sanitized live fixture.

**Исследование:** `wall_post_new` является отдельным настраиваемым событием Bots Long Poll. Это нужно проверять так же рано, как `message_new`.

## T3.2 — BUG-011: пройти pipeline по слоям

Только если T3.1 доказал raw event:

- [ ] raw consumer;
- [ ] event classifier;
- [ ] wall mapper;
- [ ] `ForwardWallPost`;
- [ ] wall readiness;
- [ ] wall destination;
- [ ] delivery ledger reserve;
- [ ] publication composition;
- [ ] plan;
- [ ] Telegram publisher.

На каждом переходе должна быть одна DEBUG-точка.

## T3.3 — Wall text-only live acceptance

- [ ] text-only post публикуется;
- [ ] присутствует `#изстенывк`;
- [ ] присутствует `https://vk.com/wall{owner_id}_{post_id}`;
- [ ] destination правильный;
- [ ] duplicate event не создаёт дубль;
- [ ] wall toggle OFF блокирует публикацию.

**Не переходить к wall media, пока text-only wall не зелёный.**

---

# WAVE 4 — P1 Media pipeline

## T4.1 — INV-005: проверить общую причину media failures

До трёх отдельных фиксов:

- [ ] получить live fixture одного сообщения с photo;
- [ ] получить fixture с doc;
- [ ] получить fixture с video;
- [ ] сравнить, что именно mapper сохраняет из каждого attachment;
- [ ] проверить `owner_id/id/access_key`;
- [ ] проверить наличие URL в полном объекте сообщения;
- [ ] проверить, не теряется `access_key` при преобразовании в domain DTO.

### Важное исследование

VKBottle рекомендует `Message.get_full_message()` перед работой с attachments: full message может дать рабочие `access_key` и более полный объект вложений.

**Рекомендация:** для входящих message attachments сначала использовать данные **full message/payload**, и лишь затем делать дополнительный `photos.getById`/`docs.getById`/`video.get`, если реально не хватает URL/метаданных.

## T4.2 — Проверить token/API compatibility lookup-методов

- [ ] отдельно записать реальный результат `photos.getById`;
- [ ] отдельно `docs.getById`;
- [ ] отдельно `video.get`;
- [ ] для ошибки записать VK error code и method;
- [ ] не менять token model до получения live evidence.

### Нюанс из исследования

В открытой JSON schema VK API 5.199:

- `photos.getById` перечисляет `user`/`service` token types;
- `docs.getById` перечисляет `user`/`group`.

Это **не доказательство**, что именно это ломает текущий проект, но это сильный сигнал проверить token capability прежде, чем переписывать downloader.

**Запрещено:** молча добавлять пользовательский VK token как новый секрет, пока не доказано, что он действительно нужен продукту.

## T4.3 — BUG-008: Photo

- [ ] сохраняется корректная attachment identity;
- [ ] выбирается лучший разумный `sizes[].url`, если URL уже доступен;
- [ ] при необходимости lookup работает;
- [ ] download работает;
- [ ] 1 photo → одиночная Telegram media operation;
- [ ] 2/5 photo → album;
- [ ] temp file удаляется после send;
- [ ] user-facing warning нормальный, без `Фото «без имени»`.

**Рекомендация:** фото обычно не нуждается в искусственном `filename`. Для warning лучше `Фото не удалось перенести: <короткая причина>.`

## T4.4 — BUG-009: Document

- [ ] `owner_id/id/access_key`;
- [ ] title/filename;
- [ ] size pre-check, если размер известен;
- [ ] URL;
- [ ] download;
- [ ] ≤50 MB отправляется;
- [ ] >50 MB не скачивается дальше/не отправляется;
- [ ] warning содержит имя и лимит;
- [ ] остальные части публикации продолжают отправляться.

## T4.5 — BUG-010: Video

- [ ] `owner_id/id/access_key`;
- [ ] `video.get` response залогирован структурно;
- [ ] доступные direct file variants определены;
- [ ] выбирается подходящий вариант;
- [ ] если downloadable file нет — это normal partial-success warning;
- [ ] остальные вложения и текст продолжают отправляться.

**Рекомендация:** не считать любое VK video гарантированно скачиваемым. Продуктовый контракт уже допускает warning вместо видео.

## T4.6 — Общий media regression

- [ ] 1 photo;
- [ ] 2 photos;
- [ ] 5 photos;
- [ ] doc ≤50 MB;
- [ ] doc >50 MB;
- [ ] video;
- [ ] unsupported audio;
- [ ] unsupported voice;
- [ ] unsupported video message;
- [ ] mixed success/failure;
- [ ] Telegram partial success сохраняет delivery semantics;
- [ ] 👍 ставится, если логическая публикация создана несмотря на skipped attachment.

## T4.7 — Wall media после починки message media

- [ ] wall photo;
- [ ] wall several photos;
- [ ] wall doc;
- [ ] wall video;
- [ ] warning behavior;
- [ ] source link и `#изстенывк` не теряются.

**Рекомендация:** wall и message должны использовать один проверенный media-preparation слой. Не создавать второй downloader только для wall.

---

# WAVE 5 — P2 Existing FSM / contract bugs

## T5.1 — BUG-001: Back из topic settings

- [ ] `← Назад` очищает вложенный state;
- [ ] возвращает main owner menu;
- [ ] не проходит в unknown-command catch-all;
- [ ] повторный вход работает без `/cancel`.

## T5.2 — BUG-002: `/start` из submenu

- [ ] `/start` всегда возвращает root/main state;
- [ ] не сообщает ложное `Чат зарегистрирован`;
- [ ] показывает `Главное меню`/актуальный summary;
- [ ] клавиатура строится из текущего persisted state.

## T5.3 — BUG-006: Alias navigation

- [ ] после add → обновлённый alias root;
- [ ] после edit → обновлённый alias root;
- [ ] после delete → обновлённый alias root;
- [ ] Back alias root → VK main menu;
- [ ] Help появляется только по явному запросу.

## T5.4 — BUG-007: manual publication initiator

- [ ] publication различает original author и initiator;
- [ ] оба профиля кликабельны;
- [ ] отсутствующий/недоступный profile name имеет безопасный fallback;
- [ ] manual idempotency semantics не ломаются.

---

# WAVE 6 — P2 VK UX redesign

## T6.1 — Перевести VK menu actions на inline callback keyboard

**Связано:** CR-008, INV-004, US-UPDATE-17.

- [ ] включить/проверить VK Long Poll event `message_event`;
- [ ] добавить обработку `GroupEventType.MESSAGE_EVENT`;
- [ ] использовать `Keyboard(inline=True)`;
- [ ] использовать `Callback` для действий, где не нужно отправлять текст пользователя в чат;
- [ ] payload содержит стабильный `action` и минимально необходимый id;
- [ ] callback проверяет `from_id/peer_id` и актуальность состояния;
- [ ] после callback всегда завершать event response (`show_snackbar`, edit/send и т.п.), чтобы кнопка не «крутилась»;
- [ ] stale callback даёт понятный snackbar/новый экран;
- [ ] double click идемпотентен.

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

То есть для alias/topic UI **не нужно эмулировать inline через обычные text-кнопки**.

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

- [ ] `Добавить` callback;
- [ ] `Изменить` callback;
- [ ] `Удалить` callback;
- [ ] `Назад` callback;
- [ ] действия не засоряют диалог сообщениями `Добавить`, `2`, `Назад`;
- [ ] после mutation экран обновляется сразу.

## T6.3 — Topic selection в VK через callback buttons

- [ ] General;
- [ ] named topics;
- [ ] unavailable исключены/помечены;
- [ ] stale topic callback безопасно отклоняется;
- [ ] длинный список имеет paging/несколько экранов;
- [ ] при выборе сохраняется именно internal topic id из payload, а не label.

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

- [ ] сделать маленький live spike в тестовом DM;
- [ ] проверить desktop;
- [ ] проверить mobile;
- [ ] проверить кириллицу + emoji;
- [ ] проверить ссылки;
- [ ] после этого оформить общий helper/templates.

**Рекомендация:** не писать свой Markdown parser. Сначала использовать `vkbottle.tools.formatting`.

## T6.5 — Единые VK message templates

- [ ] success;
- [ ] warning;
- [ ] error;
- [ ] main menu;
- [ ] alias menu;
- [ ] selection;
- [ ] help;
- [ ] manual forwarding success.

Правила:

- короткий заголовок;
- пустая строка между смысловыми блоками;
- важное выделяется `bold`;
- ссылки оформляются через `url`;
- emoji используются как семантические маркеры, а не декор в каждой строке;
- технические ids пользователю не показываются.

---

# WAVE 7 — P2 Telegram UX changes

## T7.1 — CR-003: переработать topic management

**Рекомендованное решение:** объединить «список» и refresh вокруг одного экрана `Топики`.

После refresh показывать:

- [ ] актуальные cached topics;
- [ ] added;
- [ ] removed;
- [ ] unavailable;
- [ ] текущий messages destination;
- [ ] текущий wall destination;
- [ ] `Изменений нет`, если diff пуст.

Не заставлять owner гадать, сработал refresh или нет.

## T7.2 — CR-004 / US-UPDATE-05: inline destination keyboard Telegram

Это **осознанное изменение старого требования ReplyKeyboard-only**.

- [ ] General callback;
- [ ] named topic callbacks;
- [ ] unavailable safe reject;
- [ ] stale callback;
- [ ] callback другого owner;
- [ ] старое сообщение;
- [ ] double click;
- [ ] Back;
- [ ] Cancel;
- [ ] current destination clearly shown.

**Рекомендация:** callback_data хранит operation + destination identity, а не название топика.

## T7.3 — CR-005 / US-NEW-02: proof-send для General

В manual-testing report это сформулировано как новый intent.

- [x] General получает такой же реальный proof-send;
- [x] destination сохраняется только после success;
- [x] failure не изменяет persisted destination;
- [x] owner получает понятную ошибку.

**Предположение этого TODO:** CR-005 считается утверждённым. Если владелец передумает — снять задачу до реализации.

## T7.4 — CR-006: единый cancel feedback

- [ ] registration: `Регистрация Telegram-чата отменена.`;
- [ ] destination selection;
- [ ] change-chat;
- [ ] другие mutable FSM.

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

- [ ] понятный empty state;
- [ ] ambiguous explanation;
- [ ] failed_permanent explanation;
- [ ] mark reviewed только где допустимо.

**OWNER DECISION:** если владелец всё-таки хочет убрать кнопку из main menu, сам use case/историю лучше сохранить.

---

# WAVE 8 — P2 Manual forwarding UX

## T8.1 — CR-009: success сообщает destination

- [ ] например: `✅ Сообщение отправлено в топик «General».`
- [ ] named topic аналогично;
- [ ] destination берётся из фактического outcome, не из старого UI state.

## T8.2 — CR-010: новый manual publication template

Минимальный смысл:

```text
Автор: <original VK profile>
Переслал: <initiator VK profile>

<исходный текст>
```

- [ ] original author;
- [ ] initiator;
- [ ] исходный текст;
- [ ] attachments;
- [ ] warnings;
- [ ] служебные метки;
- [ ] не переносить reply context;
- [ ] не разворачивать nested forwards;
- [ ] manual никогда не ставит 👍.

## T8.3 — CR-011: `#извк` для manual

- [ ] добавить `#извк`;
- [ ] не добавлять `#извкважно` автоматически только потому, что исходный forward содержит `@all`, если это отдельно не оговорено;
- [ ] regression auto flow не ломается.

**Предположение этого TODO:** новый intent `#извк` для manual считается утверждённым.

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
- [ ] wall OFF действительно блокирует;
- [ ] обратно ON восстанавливает;
- [ ] second-owner notification.

## T10.3 — Auto filter semantics

- [ ] plain text → no publication;
- [ ] hashtag → one publication;
- [ ] @all → one publication;
- [ ] @all + hashtag → **one**, не две;
- [ ] service tags корректны;
- [ ] 👍 после success.

## T10.4 — `is_cropped`

- [ ] fixture/live event;
- [ ] full message fetched;
- [ ] filters считаются по full message;
- [ ] attachments берутся из full message;
- [ ] source identity не меняется.

## T10.5 — Fallback

- [ ] удалить/закрыть configured named topic;
- [ ] automatic message → General;
- [ ] wall → General;
- [ ] owner notification;
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
- [ ] duplicate wall event;
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
- [ ] Telegram Back/start FSM;
- [ ] topic refresh transparent;
- [x] named + General proof-send (локальные regression tests и live-проверка владельца);
- [x] stale topic selection → automatic refresh → wizard recovery (локальные regression tests и live-проверка владельца);
- [x] invalid/stale topic никогда не сохраняется;
- [x] General fallback уведомляет всех owners (локальный integration regression test и live-проверка владельца);
- [ ] fallback publication warning, если CR-015 утверждён;
- [ ] VK alias add/edit/delete;
- [ ] VK inline/callback UI;
- [ ] VK formatted text live-tested;
- [ ] manual by number;
- [ ] manual by alias;
- [ ] manual initiator metadata;
- [ ] auto text;
- [ ] photo;
- [ ] media group;
- [ ] document;
- [ ] oversize document;
- [ ] video or correct partial-success warning;
- [ ] wall text;
- [ ] wall media;
- [ ] fallback;
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
6. **«Диагностика доставки»** — открытое UX-решение: оставить в main menu, переименовать/спрятать глубже или убрать только кнопку. Рекомендация: оставить capability и переименовать в `Проблемы доставки`.
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
