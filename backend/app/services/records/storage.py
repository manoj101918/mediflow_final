"""Report files in the private Supabase Storage bucket `patient-reports`.

Only the backend (service role) touches the bucket; browsers get short-lived signed URLs.
The Supabase client is synchronous, so callers run these methods in a worker thread.
"""

from functools import lru_cache
from typing import Protocol
from uuid import UUID

from supabase import Client, create_client

from app.core.config import get_settings

BUCKET = "patient-reports"

EXTENSIONS = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}


def report_path(clinic_id: UUID, patient_id: UUID, report_id: UUID, mime_type: str) -> str:
    """{clinic_id}/{patient_id}/{report_id}.{ext}"""
    return f"{clinic_id}/{patient_id}/{report_id}.{EXTENSIONS[mime_type]}"


class ReportStorage(Protocol):
    """Blocking storage operations (run them with anyio.to_thread)."""

    def upload(
        self, path: str, data: bytes, content_type: str, *, upsert: bool = False
    ) -> None: ...

    def download(self, path: str) -> bytes: ...

    def signed_url(self, path: str, expires_in: int) -> str: ...

    def remove(self, path: str) -> None: ...


class SupabaseReportStorage:
    def __init__(self, client: Client) -> None:
        self._bucket = client.storage.from_(BUCKET)

    def upload(self, path: str, data: bytes, content_type: str, *, upsert: bool = False) -> None:
        # upsert: regenerated files (lab report PDFs) replace the previous version.
        self._bucket.upload(
            path, data, {"content-type": content_type, "upsert": "true" if upsert else "false"}
        )

    def download(self, path: str) -> bytes:
        return self._bucket.download(path)

    def signed_url(self, path: str, expires_in: int) -> str:
        return str(self._bucket.create_signed_url(path, expires_in)["signedUrl"])

    def remove(self, path: str) -> None:
        self._bucket.remove([path])


@lru_cache
def get_report_storage() -> ReportStorage:
    settings = get_settings()
    return SupabaseReportStorage(
        create_client(settings.supabase_url, settings.supabase_service_role_key.get_secret_value())
    )
