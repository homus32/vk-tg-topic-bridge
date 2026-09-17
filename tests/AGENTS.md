# Agent Instructions — tests

## Команды
| Задача | Команда |
|--------|---------|
| Все тесты, кроме e2e | `make test` |
| Только smoke | `uv run --locked pytest tests/unit/test_smoke.py` |

## Правила
- `tests/e2e/` исключены из `make test` через `-m "not e2e"`; требуют реальных credentials и запускаются явно.
- Unit-тесты: без сети и без реальной SQLite; ports заменяются fakes/stubs.
- Acceptance-тесты именуются по US/AC (пример: `test_us07_ac073_all_and_hashtag_create_one_publication`).
- Network-dependent тесты запрещены.
- Test strategy: `docs/05-architecture-and-engineering.md` §19.
