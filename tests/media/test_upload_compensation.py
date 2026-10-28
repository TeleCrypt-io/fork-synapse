from io import BytesIO
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from synapse.media.media_repository import MediaRepository


class UploadCompensationTest(IsolatedAsyncioTestCase):
    async def test_metadata_and_provider_outcomes(self) -> None:
        for scenario in ("absent", "commit-then-error", "read-fails", "cleanup-fails", "success"):
            with self.subTest(scenario=scenario):
                objects = {}
                rows = {}
                notifications = []

                class Storage:
                    async def store_file(self, content, info):
                        objects[info.file_id] = content.read()
                        return "/staging/test"

                    async def delete_files(self, infos):
                        if scenario == "cleanup-fails":
                            raise RuntimeError("delete failed")
                        for info in infos:
                            objects.pop(info.file_id, None)

                class Store:
                    async def get_is_hash_quarantined(self, digest):
                        return False

                    async def get_local_media(self, media_id):
                        if scenario == "read-fails":
                            raise RuntimeError("read failed")
                        return rows.get(media_id)

                    async def store_local_media(self, **kwargs):
                        if scenario in ("commit-then-error", "success"):
                            rows[kwargs["media_id"]] = SimpleNamespace(media_length=kwargs["media_length"])
                        if scenario != "success":
                            raise RuntimeError("insert failed")

                class Callbacks:
                    async def get_media_upload_limits_for_user(self, user_id):
                        return []

                    async def on_media_uploaded(self, **kwargs):
                        notifications.append(kwargs)

                repo = SimpleNamespace(
                    media_storage=Storage(), store=Store(), media_repository_callbacks=Callbacks(),
                    clock=SimpleNamespace(time_msec=lambda: 1), default_media_upload_limits=[],
                    server_name="example.test",
                )
                call = MediaRepository.create_or_update_content(
                    repo, "application/octet-stream", None, BytesIO(b"content"), 7,
                    SimpleNamespace(to_string=lambda: "@test:example.test"),
                )
                if scenario == "success":
                    await call
                    self.assertEqual(len(notifications), 1)
                else:
                    with self.assertRaises(RuntimeError) as caught:
                        await call
                    if scenario in ("cleanup-fails", "read-fails"):
                        self.assertIn(next(iter(objects)), str(caught.exception))
                        self.assertEqual(str(caught.exception.__cause__), "insert failed")
                    else:
                        self.assertEqual(str(caught.exception), "insert failed")
                self.assertEqual(len(objects), 0 if scenario == "absent" else 1)
                self.assertEqual(len(rows), 1 if scenario in ("commit-then-error", "success") else 0)
