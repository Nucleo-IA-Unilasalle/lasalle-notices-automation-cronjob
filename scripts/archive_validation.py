"""Bounded, in-memory inspection for ZIP attachments.

Archive members are never extracted to the workspace.  This module is a
small safety boundary for future sources that publish an official ZIP instead
of a directly renderable PDF: it validates ZIP metadata before reading a
member, retains only PDF bytes with a PDF magic header, and returns stable
evidence suitable for source diagnostics.
"""

from __future__ import annotations

import hashlib
import io
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath


PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC_PREFIXES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_SUPPORTED_COMPRESSION_TYPES = frozenset(
    {
        zipfile.ZIP_STORED,
        zipfile.ZIP_DEFLATED,
        zipfile.ZIP_BZIP2,
        zipfile.ZIP_LZMA,
    }
)


@dataclass(frozen=True)
class ArchiveLimits:
    """Resource limits applied before archive members are read."""

    max_compressed_bytes: int = 15_000_000
    max_uncompressed_bytes: int = 50_000_000
    max_members: int = 100
    max_member_compressed_bytes: int = 10_000_000
    max_member_uncompressed_bytes: int = 15_000_000
    max_compression_ratio: float = 100.0

    def __post_init__(self) -> None:
        int_limits = (
            self.max_compressed_bytes,
            self.max_uncompressed_bytes,
            self.max_members,
            self.max_member_compressed_bytes,
            self.max_member_uncompressed_bytes,
        )
        if any(value <= 0 for value in int_limits):
            raise ValueError("archive limits must be positive")
        if self.max_compression_ratio <= 0:
            raise ValueError("max_compression_ratio must be positive")


@dataclass(frozen=True)
class ArchiveMemberEvidence:
    """Deterministic inspection evidence for one archive member."""

    filename: str
    compressed_size: int
    uncompressed_size: int
    outcome: str
    sha256: str | None = None

    def to_dict(self) -> dict[str, object]:
        evidence: dict[str, object] = {
            "filename": self.filename,
            "compressed_size": self.compressed_size,
            "uncompressed_size": self.uncompressed_size,
            "outcome": self.outcome,
        }
        if self.sha256 is not None:
            evidence["sha256"] = self.sha256
        return evidence


@dataclass(frozen=True)
class ExtractedPdf:
    """A transient, validated PDF member for a caller's OCR step."""

    filename: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class ArchiveInspection:
    """Result of ZIP inspection without exposing archive members as URLs."""

    outcome: str
    rejection_reason: str | None
    members: tuple[ArchiveMemberEvidence, ...]
    pdf_members: tuple[ExtractedPdf, ...]

    @property
    def accepted(self) -> bool:
        """Whether the archive passed all safety checks."""
        return self.outcome == "accepted"

    def to_evidence(self) -> dict[str, object]:
        """Return JSON-compatible, stable evidence without PDF contents."""
        return {
            "outcome": self.outcome,
            "rejection_reason": self.rejection_reason,
            "pdf_member_count": len(self.pdf_members),
            "members": [member.to_dict() for member in self.members],
        }


def has_pdf_magic(data: bytes) -> bool:
    """Return whether bytes can be treated as a PDF before OCR validation."""
    return data.startswith(PDF_MAGIC)


def inspect_zip_archive(
    data: bytes,
    *,
    limits: ArchiveLimits | None = None,
) -> ArchiveInspection:
    """Safely inspect a ZIP attachment entirely in memory.

    A rejected archive has no extracted members. Non-PDF regular files are
    streamed only to calculate evidence hashes; they are never retained or
    written. A ``.pdf`` member that lacks the PDF magic header is recorded as
    invalid and is not made available for OCR.
    """
    limits = limits or ArchiveLimits()
    if len(data) > limits.max_compressed_bytes:
        return _rejected("archive_compressed_size_exceeded")
    if not data.startswith(_ZIP_MAGIC_PREFIXES):
        return _rejected("invalid_archive_magic")

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_members:
                return _rejected("archive_member_count_exceeded")

            ordered_infos = sorted(infos, key=_member_sort_key)
            preflight = _preflight_members(ordered_infos, limits)
            if isinstance(preflight, ArchiveInspection):
                return preflight

            evidence: list[ArchiveMemberEvidence] = []
            pdf_members: list[ExtractedPdf] = []
            for info in ordered_infos:
                filename = _normalized_member_name(info.filename)
                if info.is_dir():
                    evidence.append(_member_evidence(info, filename, "ignored_directory"))
                    continue

                # Check content as well as the extension: a nested ZIP named
                # ``document.pdf`` must not be downgraded to a mere bad PDF.
                if _member_is_nested_archive(archive, info):
                    return _rejected(
                        "nested_archive",
                        evidence + [_member_evidence(info, filename, "rejected_nested_archive")],
                    )
                if not filename.lower().endswith(".pdf"):
                    evidence.append(
                        _member_evidence(
                            info,
                            filename,
                            "ignored_non_pdf",
                            sha256=_hash_member_bounded(archive, info, limits),
                        )
                    )
                    continue

                member_data = _read_member_bounded(archive, info, limits)
                digest = hashlib.sha256(member_data).hexdigest()
                if not has_pdf_magic(member_data):
                    evidence.append(
                        _member_evidence(
                            info,
                            filename,
                            "rejected_invalid_pdf_magic",
                            sha256=digest,
                        )
                    )
                    continue

                evidence.append(_member_evidence(info, filename, "validated_pdf", sha256=digest))
                pdf_members.append(ExtractedPdf(filename, member_data, digest))
    except (EOFError, OSError, RuntimeError, zipfile.BadZipFile):
        return _rejected("archive_read_failed")

    outcome = "accepted" if pdf_members else "no_valid_pdf"
    return ArchiveInspection(
        outcome=outcome,
        rejection_reason=None,
        members=tuple(evidence),
        pdf_members=tuple(pdf_members),
    )


def _preflight_members(
    infos: list[zipfile.ZipInfo], limits: ArchiveLimits
) -> ArchiveInspection | None:
    total_uncompressed = 0
    seen_names: set[str] = set()
    evidence: list[ArchiveMemberEvidence] = []
    for info in infos:
        filename = _normalized_member_name(info.filename)
        rejection = _member_rejection_reason(info, filename, limits)
        if rejection is not None:
            return _rejected(rejection, evidence + [_member_evidence(info, filename, f"rejected_{rejection}")])
        if filename in seen_names:
            return _rejected(
                "duplicate_member_name",
                evidence + [_member_evidence(info, filename, "rejected_duplicate_member_name")],
            )
        seen_names.add(filename)
        total_uncompressed += info.file_size
        if total_uncompressed > limits.max_uncompressed_bytes:
            return _rejected(
                "archive_uncompressed_size_exceeded",
                evidence + [_member_evidence(info, filename, "rejected_archive_uncompressed_size_exceeded")],
            )
        evidence.append(_member_evidence(info, filename, "preflight_ok"))
    return None


def _member_rejection_reason(
    info: zipfile.ZipInfo, filename: str, limits: ArchiveLimits
) -> str | None:
    if not _is_safe_member_path(filename):
        return "unsafe_member_path"
    if info.flag_bits & 0x1:
        return "encrypted_archive"
    if _is_symlink(info):
        return "symlink_member"
    if not _is_regular_file_or_directory(info):
        return "unsupported_member_type"
    if info.compress_type not in _SUPPORTED_COMPRESSION_TYPES:
        return "unsupported_compression_type"
    if info.compress_size > limits.max_member_compressed_bytes:
        return "member_compressed_size_exceeded"
    if info.file_size > limits.max_member_uncompressed_bytes:
        return "member_uncompressed_size_exceeded"
    if info.file_size > 0:
        if info.compress_size == 0:
            return "compression_ratio_exceeded"
        if info.file_size / info.compress_size > limits.max_compression_ratio:
            return "compression_ratio_exceeded"
    return None


def _read_member_bounded(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, limits: ArchiveLimits
) -> bytes:
    # Preflight checks the advertised size. The extra byte catches malformed
    # metadata that would otherwise expand past the configured member cap.
    with archive.open(info) as stream:
        content = stream.read(limits.max_member_uncompressed_bytes + 1)
        if len(content) > limits.max_member_uncompressed_bytes or stream.read(1):
            raise zipfile.BadZipFile("member exceeded configured uncompressed limit")
    return content


def _hash_member_bounded(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, limits: ArchiveLimits
) -> str:
    """Hash a non-PDF member without retaining its content in memory."""
    digest = hashlib.sha256()
    total = 0
    with archive.open(info) as stream:
        while chunk := stream.read(64 * 1024):
            total += len(chunk)
            if total > limits.max_member_uncompressed_bytes:
                raise zipfile.BadZipFile("member exceeded configured uncompressed limit")
            digest.update(chunk)
    return digest.hexdigest()


def _member_is_nested_archive(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bool:
    if info.filename.lower().endswith(".zip"):
        return True
    with archive.open(info) as stream:
        prefix = stream.read(4)
    return prefix in _ZIP_MAGIC_PREFIXES


def _member_sort_key(info: zipfile.ZipInfo) -> tuple[str, int, int, int]:
    return (
        _normalized_member_name(info.filename),
        info.CRC,
        info.file_size,
        info.compress_size,
    )


def _normalized_member_name(filename: str) -> str:
    return filename.replace("\\", "/")


def _is_safe_member_path(filename: str) -> bool:
    if not filename or "\x00" in filename or re.match(r"^[A-Za-z]:", filename):
        return False
    if filename.startswith(("/", "\\")):
        return False
    path = PurePosixPath(filename)
    return ".." not in path.parts


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _is_regular_file_or_directory(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    return file_type in (0, stat.S_IFREG, stat.S_IFDIR)


def _member_evidence(
    info: zipfile.ZipInfo,
    filename: str,
    outcome: str,
    *,
    sha256: str | None = None,
) -> ArchiveMemberEvidence:
    return ArchiveMemberEvidence(
        filename=filename,
        compressed_size=info.compress_size,
        uncompressed_size=info.file_size,
        outcome=outcome,
        sha256=sha256,
    )


def _rejected(
    reason: str, members: list[ArchiveMemberEvidence] | None = None
) -> ArchiveInspection:
    return ArchiveInspection(
        outcome="rejected",
        rejection_reason=reason,
        members=tuple(members or []),
        pdf_members=(),
    )
