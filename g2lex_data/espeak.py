from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Self

_AUDIO_OUTPUT_SYNCHRONOUS = 2
_ESPEAK_CHARS_UTF8 = 1
_ESPEAK_PHONEMES_IPA = 0x02
_ESPEAK_PHONEMES_TIE = 0x80
_ESPEAK_IPA3_MODE = _ESPEAK_PHONEMES_IPA | _ESPEAK_PHONEMES_TIE | (0x200D << 8)


class _VoiceStruct(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("languages", ctypes.c_char_p),
        ("identifier", ctypes.c_char_p),
    ]


@dataclass(frozen=True, slots=True)
class EspeakIdentity:
    version: str
    git_revision: str
    library_path: Path
    library_sha256: str
    data_path: Path
    data_sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(_sha256_file(child).encode("ascii"))
    return digest.hexdigest()


def _library_path() -> Path:
    configured = os.environ.get("ESPEAK_NG_LIBRARY")
    candidates = [Path(configured)] if configured else []
    found = ctypes.util.find_library("espeak-ng")
    if found:
        candidates.append(Path(found))
    binary = shutil.which("espeak-ng")
    if binary:
        root = Path(binary).resolve().parents[1]
        candidates.extend((root / "lib" / "libespeak-ng.so", root / "lib" / "libespeak-ng.so.1"))
    candidates.extend((Path("libespeak-ng.so"), Path("libespeak-ng.so.1")))
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    raise RuntimeError(
        "eSpeak-NG shared library was not found; install the espeak optional dependency"
    )


def _data_parent(library_path: Path) -> Path | None:
    configured = os.environ.get("ESPEAK_NG_DATA")
    if configured:
        data_path = Path(configured).expanduser().resolve()
        return data_path.parent if data_path.name == "espeak-ng-data" else data_path
    binary = shutil.which("espeak-ng")
    if binary:
        candidate = Path(binary).resolve().parents[1] / "share"
        if (candidate / "espeak-ng-data").is_dir():
            return candidate
    candidate = library_path.parents[1] / "share"
    return candidate if (candidate / "espeak-ng-data").is_dir() else None


class EspeakBackend:
    def __init__(
        self,
        *,
        library_path: Path | None = None,
        data_path: Path | None = None,
        git_revision: str = "unknown",
        expected_version: str | None = None,
    ) -> None:
        self._library_path = (library_path or _library_path()).resolve()
        self._closed = False
        initialize_path = data_path or _data_parent(self._library_path)
        if initialize_path and initialize_path.name == "espeak-ng-data":
            initialize_path = initialize_path.parent
        self._library = ctypes.CDLL(str(self._library_path))
        self._library.espeak_Initialize.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        self._library.espeak_Initialize.restype = ctypes.c_int
        parent = str(initialize_path).encode("utf-8") if initialize_path else None
        if self._library.espeak_Initialize(_AUDIO_OUTPUT_SYNCHRONOUS, 0, parent, 0) <= 0:
            raise RuntimeError("failed to initialize eSpeak-NG")
        self._library.espeak_Info.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
        self._library.espeak_Info.restype = ctypes.c_char_p
        info_path = ctypes.c_char_p()
        version = self._library.espeak_Info(ctypes.byref(info_path))
        actual_version = (version or b"").decode("utf-8")
        actual_data_path = Path((info_path.value or b"").decode("utf-8"))
        if expected_version is not None and actual_version != expected_version:
            self.close()
            raise RuntimeError(
                f"eSpeak-NG version mismatch: expected {expected_version}, got {actual_version}"
            )
        if not actual_data_path.is_dir():
            self.close()
            raise RuntimeError(f"eSpeak-NG data directory is missing: {actual_data_path}")
        self._data_path = actual_data_path
        self._identity = EspeakIdentity(
            version=actual_version,
            git_revision=git_revision,
            library_path=self._library_path,
            library_sha256=_sha256_file(self._library_path),
            data_path=actual_data_path,
            data_sha256=_sha256_tree(actual_data_path),
        )
        self._closed = False
        self._voice: str | None = None
        self._library.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
        self._library.espeak_SetVoiceByName.restype = ctypes.c_int
        self._library.espeak_TextToPhonemes.argtypes = [
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.c_int,
            ctypes.c_int,
        ]
        self._library.espeak_TextToPhonemes.restype = ctypes.c_char_p
        self._library.espeak_Terminate.argtypes = []
        self._library.espeak_Terminate.restype = ctypes.c_int

    @property
    def identity(self) -> EspeakIdentity:
        return self._identity

    def voices(self) -> tuple[str, ...]:
        self._ensure_open()
        function = self._library.espeak_ListVoices
        function.argtypes = [ctypes.POINTER(ctypes.POINTER(_VoiceStruct))]
        function.restype = ctypes.POINTER(ctypes.POINTER(_VoiceStruct))
        result = function(None)
        names: list[str] = []
        index = 0
        while result[index]:
            name = result[index].contents.name
            if name:
                names.append(name.decode("utf-8"))
            index += 1
        return tuple(names)

    def set_voice(self, voice: str) -> None:
        self._ensure_open()
        if not voice:
            raise ValueError("voice must be non-empty")
        if self._library.espeak_SetVoiceByName(voice.encode("utf-8")) != 0:
            raise ValueError(f"unsupported eSpeak-NG voice: {voice}")
        self._voice = voice

    def _phonemize(self, text: str, mode: int) -> str:
        self._ensure_open()
        if self._voice is None:
            raise RuntimeError("set_voice must be called before phonemizing")
        if not isinstance(text, str) or not text:
            raise ValueError("text must be non-empty")
        text_pointer = ctypes.pointer(ctypes.c_char_p(text.encode("utf-8")))
        chunks: list[str] = []
        while text_pointer.contents.value is not None:
            result = self._library.espeak_TextToPhonemes(text_pointer, _ESPEAK_CHARS_UTF8, mode)
            if result:
                chunks.append(result.decode("utf-8"))
        return " ".join(chunks)

    def phonemize_ipa(self, text: str) -> str:
        return self._phonemize(text, _ESPEAK_PHONEMES_IPA)

    def phonemize_ipa3(self, text: str) -> str:
        return self._phonemize(text, _ESPEAK_IPA3_MODE)

    def close(self) -> None:
        if getattr(self, "_closed", True):
            return
        self._library.espeak_Terminate()
        self._closed = True

    def _ensure_open(self) -> None:
        if getattr(self, "_closed", True):
            raise RuntimeError("eSpeak-NG backend is closed")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


__all__ = ["EspeakBackend", "EspeakIdentity"]
