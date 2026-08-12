"""Dispatch fixed, one-time source-migration profiles."""

from __future__ import annotations

from pathlib import Path

try:
    from .migrate_cnn_duda_source import (
        PROFILE_NAME as DUDA_HERRIOT_PROFILE,
        approved_seed_objects as approved_duda_herriot_seed_objects,
    )
    from .migrate_folha_sources import (
        PROFILE_NAME as FOLHA_PROFILE,
        approved_seed_objects as approved_folha_seed_objects,
    )
    from .private_feed_common import ConfigurationError
except ImportError:  # pragma: no cover - direct script execution
    from migrate_cnn_duda_source import (  # type: ignore[no-redef]
        PROFILE_NAME as DUDA_HERRIOT_PROFILE,
        approved_seed_objects as approved_duda_herriot_seed_objects,
    )
    from migrate_folha_sources import (  # type: ignore[no-redef]
        PROFILE_NAME as FOLHA_PROFILE,
        approved_seed_objects as approved_folha_seed_objects,
    )
    from private_feed_common import ConfigurationError  # type: ignore[no-redef]


def approved_seed_objects(
    *,
    repo_root: Path,
    profile: str,
) -> dict[str, bytes]:
    if profile == DUDA_HERRIOT_PROFILE:
        return approved_duda_herriot_seed_objects(
            repo_root=repo_root,
            profile=profile,
        )
    if profile == FOLHA_PROFILE:
        return approved_folha_seed_objects(
            repo_root=repo_root,
            profile=profile,
        )
    raise ConfigurationError(
        f"unsupported source migration profile: {profile}"
    )
