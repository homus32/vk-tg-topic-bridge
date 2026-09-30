"""Централизованная политика ключей stdlib ``logging.extra``.

Группы ниже описывают диагностические области и наблюдаемые источники вызовов;
это не исключительное владение ключами. Один ключ может использоваться в
нескольких модулях. Пути ниже указаны относительно ``src/vk_topic_bridge/``.

Модули приложения могут передавать существующие ключи, но не должны изменять
группы или регистрировать ключи динамически. Новый ключ добавляется только при
наличии конкретного диагностического сценария, проверке формы и чувствительности
значения, указании источников и наличии регрессионного теста.
Этот список фильтрует только имена полей, но не очищает значения. Например,
``reason``, ``missing``, ``source_key``, ``lookup_method`` и ``url_host`` требуют
отдельной проверки содержимого в местах формирования.
"""

# События VK и опрос сообщества. Источник вызовов: bootstrap/vk_consumer.py;
# group_id также используется в application/forwarding и infrastructure/vk/api.py.
_VK_EVENT_POLLING_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "from_id",
        "group_id",
        "peer_id",
        "poller",
        "update_count",
    }
)

# Межсистемная корреляция. Наблюдаемые источники: application/forwarding,
# application/manual/publish_manual.py, bootstrap/vk_consumer.py и
# presentation/telegram/routers/registration.py.
_CROSS_SYSTEM_CORRELATION_FIELDS = frozenset(
    {
        "active_owner_id",
        "chat_id",
        "conversation_message_id",
        "destination_topic_id",
        "delivery_id",
        "message_id_count",
        "owner_id",
        "post_id",
        "route",
        "source_key",
        "source_type",
    }
)

# Доставка, ручная публикация и уведомления владельцев. Наблюдаемые источники:
# application/forwarding, application/manual/publish_manual.py,
# application/notifications/owner_notifier.py и application/admin.
_DELIVERY_NOTIFICATION_FIELDS = frozenset(
    {
        "failed_count",
        "message_count",
        "operation",
        "operation_count",
        "operation_kind",
        "outcome",
        "owner_count",
        "reason",
        "sent_count",
        "status",
        "text_length",
        "topic_count",
        "warning_count",
    }
)

# Подготовка и загрузка медиа. Наблюдаемые источники:
# application/forwarding/media_prep.py, infrastructure/vk/mapper.py и
# infrastructure/vk/media_downloader.py.
_MEDIA_PREPARATION_FIELDS = frozenset(
    {
        "attachment_count",
        "attachment_index",
        "attachment_kind",
        "direct_url_present",
        "download_result",
        "filename_present",
        "files_present",
        "media_count",
        "media_id",
        "planned_media_count",
        "player_present",
        "size_bytes",
        "url_host",
        "variant_count",
        "written_bytes",
    }
)

# Регистрация и проверка возможностей. Наблюдаемые источники:
# presentation/telegram/routers/registration.py, application/admin/register_chat.py
# и infrastructure/telegram/publisher.py.
_REGISTRATION_CAPABILITY_FIELDS = frozenset(
    {
        "missing",
        "state_after",
        "state_before",
    }
)

# Диагностика VK API, поиска медиа и преобразования ответов. Наблюдаемые
# источники: infrastructure/vk/api.py, infrastructure/vk/mapper.py и
# infrastructure/vk/media_downloader.py.
_VK_API_MAPPING_FIELDS = frozenset(
    {
        "access_key_present",
        "api_adapter",
        "http_status",
        "lookup",
        "lookup_method",
        "method",
        "resolution_source",
        "token_type",
        "vk_error_class",
        "vk_error_code",
    }
)
