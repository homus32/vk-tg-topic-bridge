---
title: "VK Topic Bridge — ручное тестирование и backlog доработок"
date: 2026-09-19
project: vk-topic-bridge
status: "manual-testing / fix-backlog"
---

# VK Topic Bridge — ручное тестирование и backlog доработок

> Основано на live-тестировании 19.09.2026. Документ отделяет фактические результаты тестов от дефектов, изменений требований, новых фич и вопросов на исследование.

## Оглавление

- [[#1. Краткий итог]]
- [[#2. Среда тестирования]]
- [[#3. Матрица результатов]]
- [[#4. Подробные результаты тестов]]
- [[#5. Реестр дефектов]]
- [[#6. Change Requests]]
- [[#7. Новые и изменяемые User Stories]]
- [[#8. Вопросы на исследование]]
- [[#9. Приоритет исправлений]]
- [[#10. План повторного тестирования]]
- [[#11. Что ещё не протестировано]]

---

# 1. Краткий итог

Live-прогон подтвердил, что базовый каркас проекта работает: старт через `scripts/start.sh`, миграции на чистой БД, повторный запуск, восстановление VK Long Poll cursor, Telegram registration happy path, смена Telegram-чата, toggle-настройки, базовая ручная пересылка VK → Telegram, алиасы, текстовая автопересылка и реакция 👍.

Критические проблемы:

1. **Медиа не доставляются:** фото, документ и видео провалили live-тест.
2. **Посты стены VK не пересылаются вообще:** новый пост не дал ни Telegram-публикации, ни понятной ошибки.
3. **Registration flow ломается при недостаточных правах:** приложение находит missing capabilities, но затем пытается ответить в чат, куда писать запрещено.
4. После registration error корректный `/register` переставал обрабатываться до нового `/start`.
5. Telegram-бот отвечает на посторонние group-команды вроде `/asd`.
6. Есть нарушения FSM/навигации в Telegram и VK UI.
7. Manual forwarding не содержит всей ожидаемой метаинформации об инициаторе пересылки.

## Классы записей

- **BUG** — нарушение существующего поведения/контракта.
- **CR** — осознанное изменение требований или новая UX-фича.
- **US-UPDATE / US-NEW** — формализованное изменение User Story.
- **INV** — вопрос требует исследования, прежде чем называть его багом.

---

# 2. Среда тестирования

- Дата: **2026-09-19**.
- Реальные VK и Telegram.
- Перед прогоном рабочая SQLite БД была удалена.
- Миграции применялись автоматически.
- Запуск: `scripts/start.sh`.
- Использовался реальный Telegram-чат с топиками.
- Использовались реальные VK-чат, VK-бот и стена сообщества.

## Cold start

Наблюдалось:

```text
Running upgrade  -> 0001
Running upgrade 0001 -> 0002
```

Приложение запустилось без fatal startup error.

**Статус:** ✅ PASS.

## Повторный запуск

```text
Restoring bot polling ts 1067 from runtime/vk_cursor/bot-polling/185042850.json
```

**Статус:** ✅ PASS.

## Shutdown

Процесс останавливается нормально, но при остановке появляются сетевые сообщения:

```text
Failed to fetch updates
ServerDisconnectedError: Server disconnected
Sleep for 1.000000 seconds and try again...
```

**Статус:** ✅ PASS с замечанием `INV-002`.

## Повторяющийся warning

```text
Server closed the connection: 0 bytes read on a total of 4 expected bytes
```

Не глушить автоматически в `logger.py`, пока не установлена причина.

**Статус:** `INV-001`.

---

# 3. Матрица результатов

| Область | Статус | Результат |
|---|---|---|
| Fresh DB + migrations | ✅ PASS | `0001 → 0002`, запуск успешный |
| Restart + cursor restore | ✅ PASS | cursor восстановлен |
| Graceful shutdown | ✅ PASS / remark | функционально нормально, сетевой шум |
| `/start` до регистрации | ✅ PASS | onboarding корректный |
| `/cancel` registration | ✅ PASS / UX | режим выключается, feedback можно улучшить |
| `/register` при mode OFF | ✅ PASS | silent ignore |
| `/register` в ЛС | ✅ PASS | не обрабатывается |
| `/register@BotUsername` | ✅ PASS | регистрация успешна |
| Недостаточные права | ❌ FAIL | вторичная `TelegramBadRequest` |
| Registration после ошибки | ❌ FAIL | state/flow перестал принимать `/register` |
| Посторонняя group-команда | ❌ FAIL | `/asd` получает ответ |
| Telegram command scopes | ⚠️ INVESTIGATE | подсказки появляются/исчезают неочевидно |
| Смена Telegram-чата | ✅ PASS | Cancel/Да/`/cancel` работают |
| Список/refresh топиков | ✅ PASS / UX | функции работают, feedback слабый |
| `← Назад` из topic settings | ❌ FAIL | попадает в unknown-command |
| `/start` из submenu | ❌ FAIL | пишет «Чат зарегистрирован» |
| Диагностика доставки | ✅ PASS | empty state + Back работают |
| Toggles | ✅ PASS | UI и broadcast второму owner работают |
| Auto без destination | ✅ PASS | публикации нет |
| Destination setup | ✅ PASS | cancel / invalid / General работают |
| Named proof-send | ✅ PASS | в topic пришёл test message |
| General proof-send | ➕ CR | теперь требуется как новое поведение |
| VK plain message | ✅ PASS | без `@all/#` не пересылается |
| Manual forward по номеру | ✅ PASS | отправляется |
| VK Help | ✅ PASS | работает |
| Alias add/edit | ✅ PASS / UX | данные сохраняются, навигация плохая |
| Alias delete | ⏸ NOT RUN | не тестировался |
| Forward по alias | ✅ PASS | работает |
| Manual metadata | ❌ FAIL | нет initiator |
| Auto text | ✅ PASS | текст + `#извк` + 👍 |
| Фото | ❌ FAIL | не скачивается |
| Документ | ❌ FAIL | не скачивается |
| Видео | ❌ FAIL | не скачивается |
| Wall post | ❌ FAIL | ничего не произошло |

---

# 4. Подробные результаты тестов

## TC-01 — Telegram `/start` до регистрации

**Связано:** US-02  
**Статус:** ✅ PASS

Получено ожидаемое onboarding-сообщение с инструкцией добавить бота, выдать права и выполнить `/register`. Registration mode активировался.

## TC-02 — `/cancel` registration

**Статус:** ✅ PASS / UX

Режим регистрации действительно отключается.

**Доработка:** явно писать `Регистрация Telegram-чата отменена.` (`CR-006`).

## TC-03 — `/register` при выключенном режиме

**Статус:** ✅ PASS

Бот молчит, как и должен.

## TC-04 — `/register` в ЛС

**Статус:** ✅ PASS

Команда не запускает регистрацию группы.

## TC-05 — `/register@HexletVkBridgeBot`

**Статус:** ✅ PASS

В ЛС owner пришло:

```text
Чат зарегистрирован. Клавиатура управления обновлена.
```

Клавиатура появилась.

## TC-06 — Недостаточные права бота

**Связано:** US-03  
**Статус:** ❌ FAIL

Application layer корректно определил:

```text
missing required bot capabilities:
can_send_text, can_send_photo, can_send_video, can_send_document
```

Но затем presentation выполнил ответ в тот же чат и получил:

```text
TelegramBadRequest:
not enough rights to send text messages to the chat
```

Связано: `BUG-003`.

## TC-07 — Recovery registration после ошибки

**Статус:** ❌ FAIL

После возврата прав корректный `/register@HexletVkBridgeBot` не обработался. Новый `/start` восстановил flow.

Root cause не доказан, но recoverable error не должна разрушать registration mode.

Связано: `BUG-004`.

## TC-08 — Посторонняя команда в группе

**Статус:** ❌ FAIL

`/asd` получил:

```text
Неизвестная команда. Воспользуйтесь кнопками меню.
```

Private admin catch-all не должен работать как общий group handler.

Связано: `BUG-005`.

## TC-09 — Список настроек топиков

**Статус:** ✅ PASS / UX

Показываются текущие назначения и кнопка refresh.

Нужно дополнительно показывать:

- что refresh реально произошёл;
- актуальный кеш топиков;
- что добавилось/исчезло;
- какие destinations назначены.

Связано: `CR-003`.

## TC-10 — `← Назад` из настроек топиков

**Статус:** ❌ FAIL

Получено:

```text
Неизвестная команда. Воспользуйтесь кнопками меню.
```

Ожидается главное owner menu.

Связано: `BUG-001`.

## TC-11 — `/start` из submenu

**Статус:** ❌ FAIL

Главная клавиатура вернулась, но бот написал:

```text
Чат «123» зарегистрирован.
```

Это ложное событие. Должно быть `Главное меню` или актуальный summary.

Связано: `BUG-002`.

## TC-12 — Смена Telegram-чата

**Связано:** US-21  
**Статус:** ✅ PASS

Проверены:

- `Отмена`;
- `Да`;
- `/cancel`.

Сброс работает.

## TC-13 — Диагностика доставки

**Статус:** ✅ PASS

Empty state:

```text
Записей нет: проблемные доставки не найдены.
```

Back работает.

Но владельцу продукта непонятно назначение функции → `CR-007`.

## TC-14 — Toggles

**Связано:** US-20  
**Статус:** ✅ PASS

Все три toggle меняются, клавиатура обновляется, второй owner получает broadcast.

Осталось проверить реальное влияние OFF/ON на live events.

## TC-15 — Auto-forward без destination

**Статус:** ✅ PASS

VK events не публикуются, если destination не настроен.

## TC-16 — Настройка destination

**Связано:** US-05  
**Статус:** ✅ PASS + CR

Проверены:

- `Отмена`;
- неверный номер;
- General.

Для named wall topic пришёл proof-send.

Для General proof-send нет. По текущему FSM-контракту это было намеренно, поэтому это **не regression**, а новый `CR-005`.

## TC-17 — VK manual forward по номеру

**Связано:** US-15  
**Статус:** ✅ PASS / content issue

FSM предлагает список, номер принимается, сообщение уходит.

Недостатки:

- `Сообщение отправлено.` не содержит destination;
- Telegram publication не показывает инициатора ручной пересылки;
- оформление слишком техническое.

Связано: `BUG-007`, `CR-009`, `CR-010`.

## TC-18 — Help

**Связано:** US-19  
**Статус:** ✅ PASS

Справка работает.

## TC-19 — Alias add/edit

**Связано:** US-17  
**Статус:** ✅ PASS / UX issue

Add и edit сохраняют данные.

После success alias flow не возвращает пользователя в удобный alias root; `← Назад` приводит к Help.

Связано: `BUG-006`, `CR-008`.

## TC-20 — Alias delete

**Статус:** ⏸ NOT RUN

Не считать подтверждённым.

## TC-21 — Forward по alias

**Статус:** ✅ PASS

Алиас `гл` успешно отправил сообщение в General.

## TC-22 — Auto-forward текста

**Связано:** US-06, US-09, US-13  
**Статус:** ✅ PASS

Текст опубликован, `#извк` присутствует, 👍 ставится.

## TC-23 — Фото

**Связано:** US-10  
**Статус:** ❌ FAIL

```text
Фото «без имени» не удалось скачать и пропущено.
```

Связано: `BUG-008`.

## TC-24 — Документ

**Связано:** US-10  
**Статус:** ❌ FAIL

```text
Документ «ava123.jpg» недоступно для скачивания и пропущено.
```

Связано: `BUG-009`.

## TC-25 — Видео

**Связано:** US-10  
**Статус:** ❌ FAIL

```text
Видео «Видео недоступно» не удалось скачать и пропущено.
```

Связано: `BUG-010`.

## TC-26 — Wall post

**Связано:** US-14  
**Статус:** ❌ FAIL

Wall destination был настроен. Создан пост `Тестовый пост`.

Результат:

- публикации в Telegram нет;
- заметной ошибки в консоли нет;
- дальнейший wall media test остановлен.

Связано: `BUG-011`.

---

# TC-033. Выбор удалённого Telegram-топика из устаревшего кеша

**Связано:** US-04, destination selection  
**Тип:** Negative / Recovery  
**Статус:** FAIL

## Предусловия

1. Топик `Важное` существовал и был сохранён в локальном кеше.
2. Он был назначен destination для автоматической пересылки сообщений VK-чата.
3. После этого топик был удалён непосредственно в Telegram.
4. Локальный список топиков ещё не обновлялся.

## Действие

Открыть:

```text
Настроить топик назначения автопересылки сообщений чата
```

и выбрать всё ещё отображаемый топик `Важное`.

## Ожидаемый результат

Система должна безопасно обработать рассинхронизацию кеша с Telegram:

1. proof-send обнаруживает, что topic больше не существует;
2. exception не выходит наружу;
3. пользователю показывается понятное сообщение;
4. список топиков автоматически обновляется через Telethon;
5. удалённый topic помечается недоступным/исчезнувшим;
6. пользователю сразу предлагается актуальный список destinations;
7. старое назначение не перезаписывается невалидным значением.

## Фактический результат

Proof-send завершился необработанной application exception:

```text
PublicationRejectedError:
Telegram server says - Bad Request: message thread not found
```

В traceback видно путь:

```text
destinations.py
→ SelectDestinationV2.execute(...)
→ send_test_into_topic(...)
→ publisher.send_text(...)
→ PublicationRejectedError
```

Пользовательского recovery-сценария не было.

## Дополнительное наблюдение

Ручное нажатие `Обновить список` после этого сработало правильно:

```text
Сообщения VK-чата: топик 21 больше не найден в чате
```

То есть refresh-механизм умеет обнаруживать исчезнувшие топики; его нужно связать с failure path выбора destination.

Связано: `BUG-012`.

---

# TC-034. General fallback после удаления настроенного destination

**Связано:** US-22  
**Тип:** Failure recovery  
**Статус:** PARTIAL FAIL

## Предусловия

- `Важное` назначен destination для автоматической пересылки VK-чата;
- топик `Важное` удалён в Telegram;
- автоматическая пересылка включена.

## Действие

Отправить подходящее для auto-forward сообщение из VK.

## Ожидаемый результат по текущему контракту

1. публикация уходит в General;
2. все owners получают уведомление:
   - какой топик недоступен;
   - что применён General fallback;
3. при успешной публикации VK-сообщению ставится 👍.

## Фактический результат

- ✅ General fallback сработал;
- ❌ уведомление owners не пришло;
- новая UX-идея: в самой публикации General также показывать warning о том, что исходный destination недоступен.

## Классификация

Отсутствие owner notification — **BUG**, потому что это уже существующий acceptance criterion.

Warning внутри самой публикации — **Change Request**, потому что текущий контракт этого не требует.

Связано: `BUG-013`, `CR-015`.

---

# 5. Реестр дефектов

## BUG-001 — Back из topic settings попадает в catch-all

**Priority:** Major  
**Компонент:** Telegram UI/FSM

### Expected

`← Назад` завершает вложенный flow и возвращает owner main menu.

### Actual

```text
Неизвестная команда. Воспользуйтесь кнопками меню.
```

### Acceptance Criteria

- Back не проходит в unknown-command handler;
- state очищается;
- главная клавиатура показывается;
- повторный вход в меню работает без `/cancel`.

---

## BUG-002 — `/start` показывает ложное «Чат зарегистрирован»

**Priority:** Minor/Major UX  
**Компонент:** Telegram root router

При уже зарегистрированном чате `/start` должен открывать главное меню, а не имитировать регистрацию.

---

## BUG-003 — Missing capabilities error сам вызывает Telegram API error

**Priority:** Critical/Major  
**Компонент:** Registration / capabilities

### Required fix

Если писать в целевую группу нельзя:

- не выполнять `message.answer()` туда;
- отправить missing capabilities активному owner в ЛС;
- сохранить registration mode;
- после выдачи прав позволить повторный `/register`.

---

## BUG-004 — Registration mode теряется/ломается после recoverable error

**Priority:** Major

### Acceptance Criteria

Registration mode завершается только:

1. успешной регистрацией;
2. явным `/cancel` инициатором.

Ошибка прав, посторонняя команда или временная API-ошибка не должны завершать flow.

---

## BUG-005 — Бот отвечает на `/asd` в группе

**Priority:** Major  
**Компонент:** Telegram filters/routing

В group context должны работать только явно разрешённые group handlers. Private catch-all туда не должен попадать.

---

## BUG-006 — Alias FSM неправильно возвращается после add/edit

**Priority:** Major UX  
**Компонент:** VK aliases FSM

После add/edit нужно сразу показывать обновлённый alias root. Back из alias root → main menu, а не Help.

---

## BUG-007 — Manual publication не содержит initiator

**Priority:** Major  
**Компонент:** Manual composition

Manual Telegram publication должна различать:

- автора исходного VK-сообщения;
- пользователя VK, который инициировал ручную пересылку.

---

## BUG-008 — Фото VK не скачивается

**Priority:** Critical  
**Компонент:** VK media pipeline

Live-debug цепочки:

```text
VK event
→ mapper
→ owner_id/id/access_key
→ photos.getById
→ URL
→ download
→ publication plan
→ Telegram
```

Текст `без имени` для фото также требует очистки UX, но это вторично.

---

## BUG-009 — Документ VK не скачивается

**Priority:** Critical

Проверить реальный payload, `docs.getById`, owner/id/access_key, URL и downloader.

---

## BUG-010 — Видео VK не скачивается

**Priority:** Critical

Проверить payload, `video.get`, access_key, `files/mp4_*`, mapping и downloader.

---

## BUG-011 — `wall_post_new` не приводит к публикации

**Priority:** Critical  
**Компонент:** VK Long Poll / wall pipeline

Проверять последовательно:

```text
Long Poll получает wall_post_new?
→ classifier
→ mapper
→ ForwardWallPost
→ readiness
→ destination
→ delivery ledger
→ publisher
```

Acceptance после фикса:

- текст;
- `#изстенывк`;
- ссылка на оригинал;
- вложения или per-item warning.

---

## BUG-012 — Удалённый topic остаётся выбираемым, а proof-send failure не обрабатывается

**Priority:** Major  
**Компонент:** Telegram destination wizard / topic cache / error handling

### Actual

Удалённый в Telegram топик остаётся в локальном кеше и отображается как доступный. При выборе proof-send падает:

```text
PublicationRejectedError:
Telegram server says - Bad Request: message thread not found
```

Ошибка уходит в общий aiogram error pipeline вместо нормального recovery flow.

### Required fix

При `message thread not found`:

1. перехватить `PublicationRejectedError`;
2. определить stale/unavailable destination;
3. автоматически выполнить refresh topics через Telethon;
4. обновить availability/cache;
5. сообщить owner, что выбранный топик больше недоступен;
6. показать актуальный список destinations;
7. оставить FSM в состоянии выбора;
8. не сохранять невалидный topic.

### Acceptance Criteria

- traceback не уходит наружу как необработанная ошибка пользовательского действия;
- исчезнувший topic после refresh нельзя выбрать как доступный;
- wizard продолжает работу без `/cancel` и нового `/start`;
- пользователь сразу может выбрать General или другой актуальный topic.

---

## BUG-013 — General fallback не уведомляет owners

**Priority:** Major  
**Компонент:** Auto-forward fallback / OwnerNotifier

### Actual

После удаления configured destination публикация успешно ушла в General, но обязательное уведомление owners не пришло.

### Why this is a bug

US-22 уже требует уведомить всех owners:

- какой topic оказался недоступен;
- что был использован General fallback.

Сам fallback сработал, значит отдельно нужно проверить notification path/wiring.

### Проверить

```text
ForwardVkMessage
→ fallback decision
→ OwnerNotifier
→ TelegramNotifierPort
→ broadcast owners
```

Также проверить:

- вызывается ли notifier;
- корректен ли `OWNER_IDS`;
- не подавляется ли нужный recipient;
- не проглатывается ли exception;
- не зависит ли broadcast ошибочно от другого terminal status path.

### Acceptance Criteria

При каждом фактическом General fallback:

- все owners получают notification;
- notification содержит прежний destination;
- явно указано использование General;
- failure отправки одному owner не мешает уведомлению остальных;
- успех публикации и 👍 не зависят от успеха broadcast.

---

# 6. Change Requests

## CR-001 — Больше DEBUG-логов

Добавить диагностические точки:

- raw VK event;
- classifier;
- message/wall mapper;
- attachment identity;
- media API lookup;
- URL resolution;
- download result;
- readiness decision;
- destination;
- publication planning;
- Telegram operation result;
- registration state transition;
- capability check;
- topic refresh diff.

Секреты не логировать.

---

## CR-002 — Единый UI/UX polish

- короче названия кнопок;
- больше визуальной иерархии;
- emoji в success/warning/error;
- переносы строк;
- единый стиль;
- не показывать Help при обычном возврате;
- отдельный текст `Главное меню`;
- привести Telegram/VK сообщения к продуктовым шаблонам.

---

## CR-003 — Переработать topic management

Варианты:

- заменить `Список настроек топиков` на `Обновить топики`;
- либо объединить refresh + destinations в одном экране.

После refresh показывать:

- список кешированных топиков;
- added/removed/unavailable;
- текущие назначения;
- `Изменений нет`, если diff пуст.

---

## CR-004 — Inline keyboard для Telegram destinations

Вместо ordinal input рассмотреть inline callback buttons.

Обязательно обработать:

- stale callback;
- удалённый topic;
- double click;
- callback другого owner;
- старое сообщение;
- Cancel/Back;
- General;
- proof-send failure.

---

## CR-005 — Proof-send также для General

Текущий контракт специально сохраняет General без proof-send.

Новый intent: General тоже должен подтверждаться реальной test publication.

Это изменение требований.

---

## CR-006 — Явный feedback отмены

После `/cancel` писать, например:

```text
Регистрация Telegram-чата отменена.
```

Аналогично унифицировать cancel для других FSM.

---

## CR-007 — Объяснить или убрать «Диагностику доставки»

Функция работает, но непонятна owner.

Если оставить:

- переименовать понятнее;
- добавить краткое объяснение;
- объяснить `ambiguous`, `failed_permanent`, review.

Если практической пользы нет — убрать кнопку из основного UI.

---

## CR-008 — Переработать VK Alias UI

- цветные кнопки;
- проверить inline/callback возможности VK;
- при Add/Edit показывать topic buttons/list;
- после success возвращаться в alias root;
- Back → main menu;
- Help только по явному запросу.

---

## CR-009 — Success manual forwarding с destination

Вместо:

```text
Сообщение отправлено.
```

использовать:

```text
✅ Сообщение отправлено в топик «General».
```

---

## CR-010 — Новый шаблон manual publication

Показывать:

- автора исходного сообщения;
- инициатора пересылки;
- исходный текст;
- вложения;
- служебные метки.

Пример смысла:

```text
👤 Автор: <VK profile>
📨 Переслал: <VK profile>

<текст>
```

---

## CR-011 — `#извк` для manual forwarding

Старый Product Spec явно закрепляет `#извк` для автоматических сообщений.

Новый intent: manual publication тоже получает `#извк`.

Оформить как уточнение требования, а не старый regression.

---

## CR-012 — Registration session принадлежит одному owner

Если owner A запустил регистрацию:

- owner B не может начать competing flow;
- `/register` принимается только от A;
- `/cancel` registration принимается только от A;
- recoverable error не освобождает lock;
- lock снимается success/cancel.

---

## CR-013 — Command scopes registration

Желаемый UX:

- mode OFF → `/register` никому не показывается;
- mode ON → `/register` виден только активному owner в нужном group context;
- после success/cancel scope очищается.

Требует проверки реальных Telegram command scopes (`INV-003`).

---

## CR-014 — Не глушить сетевой warning до root-cause

Для:

```text
Server closed the connection: 0 bytes read on a total of 4 expected bytes
```

сначала выяснить источник и влияние, только затем фильтровать.

---

# CR-015. Warning внутри публикации при General fallback

Новый продуктовый intent:

> Если сообщение пришлось отправить в General из-за исчезнувшего/закрытого destination, читатель самой публикации тоже должен видеть, что сработал fallback.

## Предлагаемый смысл

Например:

```text
⚠️ Исходный топик «Важное» недоступен.
Сообщение автоматически отправлено в General.
```

После этого — обычное содержимое публикации.

## Важно

Это **не BUG-013**.

`BUG-013` — отсутствие обязательного уведомления owners по существующему контракту.

`CR-015` — новое требование изменить саму fallback-публикацию.

## Нужно решить до реализации

- warning ставить сверху или снизу;
- входит ли warning в исходный текст или оформляется отдельным служебным блоком;
- добавлять ли его также для wall fallback;
- не должен ли warning нарушать правило «исходный VK-текст не переписывается».

Рекомендуемый вариант: исходный текст сохранять неизменным, а warning добавлять отдельным служебным блоком композиции.

---

# 7. Новые и изменяемые User Stories

## US-UPDATE-02 — Устойчивая регистрация Telegram-чата

**Как owner, я хочу, чтобы registration mode сохранялся до успешной регистрации или явной отмены, чтобы временная ошибка не заставляла начинать flow заново.**

### AC

- capability error не очищает state;
- посторонняя команда не очищает state;
- после исправления прав повторный `/register` работает без нового `/start`;
- flow завершается только success/cancel.

---

## US-UPDATE-03 — Missing capabilities через доступный канал

**Как owner, я хочу получить список недостающих прав даже тогда, когда бот не может писать в регистрируемую группу.**

### AC

- права определяются;
- если писать в group нельзя — сообщение идёт owner в ЛС;
- перечисляется каждое отсутствующее право;
- нет необработанного `TelegramBadRequest`;
- registration mode остаётся активным.

---

## US-NEW-01 — Эксклюзивная registration session

**Как owner, я хочу, чтобы одновременно только один owner управлял регистрацией Telegram-чата, чтобы два администратора не могли конкурировать за глобальное состояние.**

### AC

- первый owner получает registration lock;
- второй не может открыть competing session;
- register/cancel второго owner не меняют session первого;
- lock снимается success/cancel.

---

## US-UPDATE-04 — Прозрачный refresh топиков

**Как owner, я хочу видеть результат refresh, чтобы понимать, что система реально получила и сохранила.**

### AC

После refresh показываются:

- актуальный список;
- added;
- removed;
- unavailable;
- destinations;
- `Изменений нет`, если diff пуст.

---

## US-UPDATE-05 — Интерактивный выбор destination

**Как owner, я хочу выбирать destination кнопкой, а не вручную вводить номер.**

### AC

- General и named topics доступны как кнопки;
- unavailable topic безопасно отклоняется;
- stale callback безопасно отклоняется;
- Back/Cancel работают;
- текущий destination понятен;
- required proof-send выполняется.

---

## US-NEW-02 — Proof-send для любого destination

**Как owner, я хочу получать тестовую публикацию при назначении любого destination, включая General.**

### AC

Если новый контракт утверждён, destination считается сохранённым только после успешного proof-send.

---

## US-UPDATE-15 — Информативная manual forwarding

**Как пользователь VK, я хочу видеть понятное подтверждение и корректную метаинформацию в Telegram.**

### AC

- success сообщает destination;
- publication содержит original author;
- publication содержит initiator;
- текст и вложения сохраняются;
- `#извк` добавляется, если `CR-011` утверждён.

---

## US-UPDATE-17 — Удобное управление алиасами

**Как пользователь VK, я хочу управлять алиасами через понятный интерактивный интерфейс.**

### AC

- topic list/buttons показываются в Add/Edit;
- после success пользователь остаётся в alias root;
- новый alias виден сразу;
- Back из alias root → main menu;
- main menu не заменяется Help.

---

## US-NEW-03 — Единый визуальный стиль

**Как пользователь, я хочу быстро понимать результат операции по оформлению сообщений.**

### AC

Определены шаблоны:

- success;
- warning;
- error;
- main menu;
- selection;
- help;
- forwarded publication.

Кнопки короткие и однозначные.

---

## US-NEW-04 — Диагностическое логирование live-пайплайна

**Как оператор, я хочу проследить один event от получения до terminal outcome, чтобы быстро находить причину сбоя интеграции.**

### AC

- DEBUG trace покрывает ключевые этапы;
- correlation context достаточен для поиска;
- секреты не логируются.

---

# US-UPDATE-22. Прозрачный fallback при недоступном Telegram-топике

**Как owner и читатель Telegram, я хочу явно понимать, что целевой топик исчез и система использовала General, чтобы fallback не выглядел как обычная маршрутизация.**

## Acceptance Criteria

### AC-U22.1

Если настроенный auto-destination недоступен, публикация отправляется в General.

### AC-U22.2

Все owners получают уведомление:

- имя/идентификатор недоступного destination;
- факт General fallback.

### AC-U22.3

Если `CR-015` утверждён, сама Telegram-публикация содержит отдельный служебный warning о fallback.

### AC-U22.4

Исходный текст VK при этом не изменяется; warning является отдельным системным блоком.

### AC-U22.5

Успешный General fallback по-прежнему считается успешной доставкой и не отменяет 👍.

---

# US-NEW-05. Самовосстановление destination wizard при stale topic cache

**Как owner, я хочу, чтобы wizard автоматически восстанавливался после удаления Telegram-топика, чтобы мне не приходилось вручную обновлять кеш и перезапускать настройку.**

## Acceptance Criteria

1. Если proof-send возвращает `message thread not found`, система не падает.
2. Выполняется refresh topics.
3. Исчезнувший topic помечается unavailable/inactive.
4. Пользователь получает понятное сообщение.
5. Показывается актуальный список destinations.
6. FSM остаётся в выборе destination.
7. Невалидный topic не сохраняется.

---

# 8. Вопросы на исследование

## INV-001 — Источник `Server closed the connection...`

Определить:

- какая библиотека логирует;
- какой transport;
- происходит ли reconnect;
- теряются ли события;
- нужно ли менять retry/keepalive;
- допустимо ли потом понижать log level.

## INV-002 — Shutdown network errors

Проверить порядок:

```text
stop polling
→ close sessions
→ Telethon disconnect
→ engine dispose
```

Возможно, aiogram retry успевает стартовать уже во время shutdown.

## INV-003 — Telegram command addressing/scopes

Проверить официальное поведение:

- `/register` без `@BotUsername`;
- несколько ботов в группе;
- `/register@HexletVkBridgeBot`;
- `BotCommandScopeChatMember`;
- почему command hints появляются/исчезают.

## INV-004 — Inline/callback keyboard VK

Проверить в используемой версии VK API/VKBottle:

- inline keyboard;
- callback buttons;
- colors;
- payload limits;
- lifetime;
- DM behavior.

## INV-005 — Общая причина провала media pipeline

Поскольку одновременно провалились photo/document/video, сначала искать общую проблему выше Telegram send methods:

```text
payload → mapper → identity/access_key → VK API lookup → URL → downloader
```

## INV-006 — Где теряется `wall_post_new`

Проверить:

- настройки VK Long Poll events;
- raw consumer;
- classifier;
- mapper;
- readiness;
- use case;
- publisher.

---

# 9. Приоритет исправлений

## Этап A — Core live functionality

1. `BUG-011` — wall pipeline.
2. `BUG-008` — photo.
3. `BUG-009` — document.
4. `BUG-010` — video.
5. `BUG-003` — permissions error.
6. `BUG-004` — registration recovery.
7. `BUG-005` — group routing.
8. `BUG-012` — stale topic вызывает необработанный proof-send error.
9. `BUG-013` — General fallback не уведомляет owners.

## Этап B — FSM / contract correctness

1. `BUG-001` — Back topic settings.
2. `BUG-002` — `/start` text.
3. `BUG-006` — alias navigation.
4. `BUG-007` — manual initiator.

## Этап C — Product changes

- topic-management redesign;
- inline Telegram UI;
- General proof-send;
- alias UI;
- destination in success;
- new manual template;
- `#извк` manual;
- exclusive owner registration;
- command scopes.

## Этап D — UX / observability

- визуальный стиль;
- короткие кнопки;
- diagnostics UX;
- DEBUG logging;
- cleanup library noise после расследования.

---

# 10. План повторного тестирования

## Gate 1 — Startup

- [ ] fresh DB migrations
- [ ] restart
- [ ] graceful shutdown
- [ ] cursor restore
- [ ] нет новых fatal errors

## Gate 2 — Registration

- [ ] `/start`
- [ ] `/cancel`
- [ ] `/register` mode OFF → silence
- [ ] `/register` в DM → ignore
- [ ] missing rights
- [ ] owner получает список прав в ЛС
- [ ] state не теряется
- [ ] вернуть права
- [ ] повторный `/register` без нового `/start`
- [ ] второй owner не перехватывает flow
- [ ] `/asd` в group → silence
- [ ] success → main keyboard

## Gate 3 — Topics

- [ ] refresh
- [ ] cache/diff feedback
- [ ] Back
- [ ] `/start` из submenu
- [ ] General
- [ ] named topic
- [ ] General proof-send, если CR принят
- [ ] removed/stale topic
- [ ] выбрать удалённый topic из stale cache
- [ ] proof-send error перехватывается
- [ ] автоматически выполняется refresh topics
- [ ] FSM остаётся в выборе destination
- [ ] актуальный список показывается без `/cancel`

## Gate 4 — Toggles live

- [ ] @all ON/OFF
- [ ] hashtag ON/OFF
- [ ] wall ON/OFF
- [ ] second-owner notification

## Gate 5 — Manual VK

- [ ] number
- [ ] alias
- [ ] unknown alias
- [ ] cancel
- [ ] two forwarded messages
- [ ] original author
- [ ] initiator
- [ ] destination in success
- [ ] `#извк`, если утверждено
- [ ] photo
- [ ] document
- [ ] video

## Gate 6 — Aliases

- [ ] add
- [ ] edit
- [ ] delete
- [ ] duplicate
- [ ] case-insensitive duplicate
- [ ] spaces
- [ ] reserved word
- [ ] Back/navigation
- [ ] General alias

## Gate 7 — Auto message

- [ ] plain text → no forward
- [ ] hashtag
- [ ] @all
- [ ] @all + hashtag → one publication
- [ ] 👍
- [ ] duplicate event
- [ ] 1 photo
- [ ] 2 photos
- [ ] 5 photos
- [ ] document ≤50 MB
- [ ] document >50 MB
- [ ] video
- [ ] unsupported attachment

## Gate 8 — Wall

- [ ] text-only
- [ ] photo
- [ ] several photos
- [ ] document
- [ ] video
- [ ] `#изстенывк`
- [ ] original wall link
- [ ] wall toggle OFF
- [ ] duplicate event

## Gate 9 — Fallback / diagnostics

- [ ] удалить/закрыть configured topic
- [x] auto event → General — сам fallback уже подтверждён live
- [ ] owner notification всем owners — сейчас FAIL (`BUG-013`)
- [ ] warning внутри fallback-публикации, если принят `CR-015`
- [ ] 👍
- [ ] diagnostics entry
- [ ] details
- [ ] mark reviewed where applicable

---

# 11. Что ещё не протестировано

Не считать подтверждёнными:

- alias delete;
- реальное действие toggle OFF;
- `is_cropped`;
- `@all + hashtag` → ровно одна публикация;
- media groups;
- файл >50 MB;
- unsupported attachments;
- General fallback как механизм уже подтверждён; не подтверждены owner notification и полный fallback UX;
- ambiguous/failed_permanent;
- diagnostics details;
- mark reviewed;
- duplicate delivery / ledger;
- wall media;
- edit/delete non-sync;
- PM2 reboot;
- backup/restore;
- history gap;
- long-running stability.

---

# Итог

Проект уже прошёл полезный первый live-прогон: control plane в основном жив, но data plane пока нельзя считать готовым из-за media и wall failures.

Следующий цикл должен быть **fix cycle по live evidence**, а не общий refactor:

```text
reproduce
→ добавить диагностический evidence
→ локализовать root cause
→ regression test
→ fix
→ live retest
```

UX и новые User Stories лучше внедрять после закрытия Critical/Major regression.
