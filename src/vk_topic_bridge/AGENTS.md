# Agent Instructions — src/vk_topic_bridge

## Слои
- Направление зависимостей: `presentation`/`infrastructure` → `application` → `domain`.
- `domain` и `application` не импортируют aiogram, VKBottle, Telethon, SQLAlchemy, SQLite, Loguru.
- SDK-модели конвертируются в собственные DTO на границе `infrastructure`/`presentation`.
- Спецификация слоёв: `docs/05-architecture-and-engineering.md` §2, §4.

## Пакет
- Layout — `src/`; имя пакета `vk_topic_bridge`.
- Package markers (`__init__.py`) не содержат runtime behavior.
- Строгий режим типизации для `domain`/`application` вводится отдельным планом после появления этих слоёв.
