#
# This file is licensed under the Affero General Public License (AGPL) version 3.
#
# Copyright (C) 2025 New Vector, Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# See the GNU Affero General Public License for more details:
# <https://www.gnu.org/licenses/agpl-3.0.html>.
#

import logging
from typing import TYPE_CHECKING, Awaitable, Callable

from synapse.config.repository import MediaUploadLimit
from synapse.types import JsonDict
from synapse.util.async_helpers import delay_cancellation
from synapse.util.metrics import Measure

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)

GET_MEDIA_CONFIG_FOR_USER_CALLBACK = Callable[[str], Awaitable[JsonDict | None]]

IS_USER_ALLOWED_TO_UPLOAD_MEDIA_OF_SIZE_CALLBACK = Callable[[str, int], Awaitable[bool]]

GET_MEDIA_UPLOAD_LIMITS_FOR_USER_CALLBACK = Callable[
    [str], Awaitable[list[MediaUploadLimit] | None]
]

ON_MEDIA_UPLOAD_LIMIT_EXCEEDED_CALLBACK = Callable[
    [str, MediaUploadLimit, int, int], Awaitable[None]
]

# Called after a local user media object and its metadata have been deleted. The callback receives
# only the stable media ID; ownership and byte accounting remain the responsibility of the
# application that recorded the upload. Notification failures are logged and never undo a
# successful media deletion.
ON_MEDIA_DELETED_CALLBACK = Callable[[str], Awaitable[None]]

ON_MEDIA_UPLOADED_CALLBACK = Callable[[str, str, int], Awaitable[None]]


class MediaRepositoryModuleApiCallbacks:
    def __init__(self, hs: "HomeServer") -> None:
        self.server_name = hs.hostname
        self.clock = hs.get_clock()
        self._get_media_config_for_user_callbacks: list[
            GET_MEDIA_CONFIG_FOR_USER_CALLBACK
        ] = []
        self._is_user_allowed_to_upload_media_of_size_callbacks: list[
            IS_USER_ALLOWED_TO_UPLOAD_MEDIA_OF_SIZE_CALLBACK
        ] = []
        self._get_media_upload_limits_for_user_callbacks: list[
            GET_MEDIA_UPLOAD_LIMITS_FOR_USER_CALLBACK
        ] = []
        self._on_media_upload_limit_exceeded_callbacks: list[
            ON_MEDIA_UPLOAD_LIMIT_EXCEEDED_CALLBACK
        ] = []
        self._on_media_deleted_callbacks: list[ON_MEDIA_DELETED_CALLBACK] = []
        self._on_media_uploaded_callbacks: list[ON_MEDIA_UPLOADED_CALLBACK] = []

    def register_callbacks(
        self,
        get_media_config_for_user: GET_MEDIA_CONFIG_FOR_USER_CALLBACK | None = None,
        is_user_allowed_to_upload_media_of_size: IS_USER_ALLOWED_TO_UPLOAD_MEDIA_OF_SIZE_CALLBACK
        | None = None,
        get_media_upload_limits_for_user: GET_MEDIA_UPLOAD_LIMITS_FOR_USER_CALLBACK
        | None = None,
        on_media_upload_limit_exceeded: ON_MEDIA_UPLOAD_LIMIT_EXCEEDED_CALLBACK
        | None = None,
        on_media_deleted: ON_MEDIA_DELETED_CALLBACK | None = None,
        on_media_uploaded: ON_MEDIA_UPLOADED_CALLBACK | None = None,
    ) -> None:
        """Register callbacks from module for each hook."""
        if get_media_config_for_user is not None:
            self._get_media_config_for_user_callbacks.append(get_media_config_for_user)

        if is_user_allowed_to_upload_media_of_size is not None:
            self._is_user_allowed_to_upload_media_of_size_callbacks.append(
                is_user_allowed_to_upload_media_of_size
            )

        if get_media_upload_limits_for_user is not None:
            self._get_media_upload_limits_for_user_callbacks.append(
                get_media_upload_limits_for_user
            )

        if on_media_upload_limit_exceeded is not None:
            self._on_media_upload_limit_exceeded_callbacks.append(
                on_media_upload_limit_exceeded
            )

        if on_media_deleted is not None:
            self._on_media_deleted_callbacks.append(on_media_deleted)

        if on_media_uploaded is not None:
            self._on_media_uploaded_callbacks.append(on_media_uploaded)

    async def get_media_config_for_user(self, user_id: str) -> JsonDict | None:
        for callback in self._get_media_config_for_user_callbacks:
            with Measure(
                self.clock,
                name=f"{callback.__module__}.{callback.__qualname__}",
                server_name=self.server_name,
            ):
                res: JsonDict | None = await delay_cancellation(callback(user_id))
            if res:
                return res

        return None

    async def is_user_allowed_to_upload_media_of_size(
        self, user_id: str, size: int
    ) -> bool:
        for callback in self._is_user_allowed_to_upload_media_of_size_callbacks:
            with Measure(
                self.clock,
                name=f"{callback.__module__}.{callback.__qualname__}",
                server_name=self.server_name,
            ):
                res: bool = await delay_cancellation(callback(user_id, size))
            if not res:
                return res

        return True

    async def get_media_upload_limits_for_user(
        self, user_id: str
    ) -> list[MediaUploadLimit] | None:
        """
        Get the first non-None list of MediaUploadLimits for the user from the registered callbacks.
        If a list is returned it will be sorted in descending order of duration.
        """
        for callback in self._get_media_upload_limits_for_user_callbacks:
            with Measure(
                self.clock,
                name=f"{callback.__module__}.{callback.__qualname__}",
                server_name=self.server_name,
            ):
                res: list[MediaUploadLimit] | None = await delay_cancellation(
                    callback(user_id)
                )
            if res is not None:  # to allow [] to be returned meaning no limit
                # We sort them in descending order of time period
                res.sort(key=lambda limit: limit.time_period_ms, reverse=True)
                return res

        return None

    async def on_media_upload_limit_exceeded(
        self,
        user_id: str,
        limit: MediaUploadLimit,
        sent_bytes: int,
        attempted_bytes: int,
    ) -> None:
        for callback in self._on_media_upload_limit_exceeded_callbacks:
            with Measure(
                self.clock,
                name=f"{callback.__module__}.{callback.__qualname__}",
                server_name=self.server_name,
            ):
                # Use a copy of the data in case the module modifies it
                limit_copy = MediaUploadLimit(
                    max_bytes=limit.max_bytes,
                    time_period_ms=limit.time_period_ms,
                    info_uri=limit.info_uri,
                    can_upgrade=limit.can_upgrade,
                )
                await delay_cancellation(
                    callback(user_id, limit_copy, sent_bytes, attempted_bytes)
                )

    async def on_media_deleted(self, media_id: str) -> None:
        """Notify modules after deletion without making deletion depend on them."""
        for callback in self._on_media_deleted_callbacks:
            with Measure(
                self.clock,
                name=f"{callback.__module__}.{callback.__qualname__}",
                server_name=self.server_name,
            ):
                try:
                    await delay_cancellation(callback(media_id))
                except Exception:
                    logger.exception(
                        "media deletion callback failed for %s; deletion remains complete",
                        media_id,
                    )

    async def on_media_uploaded(
        self, user_id: str, media_id: str, size_bytes: int
    ) -> None:
        """Notify modules after upload without making upload depend on them."""
        for callback in self._on_media_uploaded_callbacks:
            with Measure(
                self.clock,
                name=f"{callback.__module__}.{callback.__qualname__}",
                server_name=self.server_name,
            ):
                try:
                    await delay_cancellation(callback(user_id, media_id, size_bytes))
                except Exception:
                    logger.exception(
                        "media upload callback failed for %s; upload remains complete",
                        media_id,
                    )
