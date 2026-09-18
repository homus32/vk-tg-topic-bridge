"""Presentation error mapping: known application errors -> plain-text owner replies.

TODO(finish): register via ``@router.error`` on the root presentation router; map
``MissingCapabilitiesError``/``ProvisioningError``/``ReadinessError`` and
``PublicationAmbiguousError``/``PublicationRejectedError`` to concise plain-text
messages (no tracebacks, no HTML). Unknown exceptions get a generic apology + log.
"""

from __future__ import annotations
