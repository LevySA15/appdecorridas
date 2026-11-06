"""Fotos dos documentos do motoqueiro (selfie, CNH, documento da moto).

Ficam em disco, numa pasta fora do git, legíveis só pelo dono do servidor. A chave devolvida é
`<id do dono>/<tipo>-<16 letras e números aleatórios>.<ext>`: o tipo de arquivo vem do **conteúdo**
(não do nome que o celular mandou) e a chave nunca é montada a partir de texto livre.
"""
from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

KINDS = ("selfie", "cnh", "crlv")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

_OWNER = re.compile(r"[A-Za-z0-9_-]{1,40}")
_KEY = re.compile(r"([A-Za-z0-9_-]{1,40})/(selfie|cnh|crlv)-[0-9a-f]{16}\.(jpg|png|webp)")
_MEDIA = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class UploadError(Exception):
    """Arquivo recusado. A mensagem é para o motoqueiro."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def sniff_image(data: bytes) -> tuple[str, str]:
    """Devolve (extensão, tipo de mídia) pelo começo do arquivo. Só JPEG, PNG e WebP."""
    if not data:
        raise UploadError(422, "empty_file", "O arquivo está vazio. Tire a foto de novo.")
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", _MEDIA["jpg"]
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", _MEDIA["png"]
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", _MEDIA["webp"]
    raise UploadError(415, "not_an_image", "Envie uma foto (JPEG, PNG ou WebP).")


@dataclass(frozen=True)
class StoredDocument:
    key: str
    modified_at: float      # época Unix da última mudança do arquivo


class DocumentStore(Protocol):
    def save(self, owner_id: str, kind: str, data: bytes) -> str: ...

    def read(self, key: str) -> tuple[bytes, str]: ...

    def exists(self, key: str) -> bool: ...

    def list_all(self) -> list[StoredDocument]:
        """Todas as fotos guardadas (só as nossas: envio pela metade e arquivos estranhos ficam de fora)."""

    def delete(self, key: str) -> None:
        """Apaga a foto. Chave inexistente ou inválida não dá erro e não toca em nada."""

    def delete_stale_partials(self, now: float, older_than_s: float = 3600.0) -> int:
        """Apaga os envios pela metade (`*.part`) parados há mais de `older_than_s` e devolve quantos. Só olha as
        pastas de dono válidas; envio recente fica (pode estar sendo gravado agora)."""


class LocalDocumentStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path | None:
        match = _KEY.fullmatch(key)
        return self.root / match.group(1) / key.split("/", 1)[1] if match else None

    def save(self, owner_id: str, kind: str, data: bytes) -> str:
        if not _OWNER.fullmatch(owner_id):
            raise ValueError("dono inválido")
        if kind not in KINDS:
            raise ValueError("tipo de documento inválido")
        ext, _ = sniff_image(data)
        key = f"{owner_id}/{kind}-{secrets.token_hex(8)}.{ext}"
        path = self._path(key)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        temp = path.with_suffix(path.suffix + ".part")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp, path)           # aparece inteiro ou não aparece
        return key

    def exists(self, key: str) -> bool:
        path = self._path(key)
        return path is not None and path.is_file()

    def read(self, key: str) -> tuple[bytes, str]:
        path = self._path(key)
        if path is None or not path.is_file():
            raise LookupError(f"documento {key} não encontrado")
        return path.read_bytes(), _MEDIA[path.suffix[1:]]

    def list_all(self) -> list[StoredDocument]:
        found: list[StoredDocument] = []
        if not self.root.is_dir():
            return found
        for owner in sorted(self.root.iterdir()):
            if not owner.is_dir():
                continue
            for path in sorted(owner.iterdir()):
                key = f"{owner.name}/{path.name}"
                if _KEY.fullmatch(key) and path.is_file():
                    found.append(StoredDocument(key, path.stat().st_mtime))
        return found

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path is not None:
            path.unlink(missing_ok=True)

    def delete_stale_partials(self, now: float, older_than_s: float = 3600.0) -> int:
        deleted = 0
        if not self.root.is_dir():
            return deleted
        for owner in sorted(self.root.iterdir()):
            if not owner.is_dir() or not _OWNER.fullmatch(owner.name):
                continue
            for path in sorted(owner.glob("*.part")):
                try:
                    if path.is_file() and path.stat().st_mtime <= now - older_than_s:
                        path.unlink(missing_ok=True)
                        deleted += 1
                except OSError:
                    continue            # um arquivo teimoso não impede os outros; amanhã tem outra volta
        return deleted
