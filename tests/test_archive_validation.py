"""Safety and evidence tests for ZIP attachment inspection."""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile

import pytest

from archive_validation import ArchiveLimits, has_pdf_magic, inspect_zip_archive


PDF_BYTES = b"%PDF-1.7\nexample edital\n"


def _zip_bytes(
    members: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return buffer.getvalue()


def _encrypted_zip_bytes() -> bytes:
    data = bytearray(_zip_bytes([("edital.pdf", PDF_BYTES)]))
    local = data.index(b"PK\x03\x04")
    central = data.index(b"PK\x01\x02")
    data[local + 6] |= 0x01
    data[central + 8] |= 0x01
    return bytes(data)


def test_valid_pdf_member_is_extracted_in_memory_with_hash_evidence():
    result = inspect_zip_archive(_zip_bytes([("edital.pdf", PDF_BYTES)]))

    assert result.accepted is True
    assert result.pdf_members[0].filename == "edital.pdf"
    assert result.pdf_members[0].content == PDF_BYTES
    assert result.pdf_members[0].sha256 == hashlib.sha256(PDF_BYTES).hexdigest()
    assert result.to_evidence()["members"] == [
        {
            "filename": "edital.pdf",
            "compressed_size": len(PDF_BYTES),
            "uncompressed_size": len(PDF_BYTES),
            "outcome": "validated_pdf",
            "sha256": hashlib.sha256(PDF_BYTES).hexdigest(),
        }
    ]


def test_unrelated_files_are_not_extracted_but_valid_pdf_is_retained():
    result = inspect_zip_archive(
        _zip_bytes([("readme.txt", b"supplier notes"), ("edital.pdf", PDF_BYTES)])
    )

    assert result.accepted is True
    assert [member.filename for member in result.pdf_members] == ["edital.pdf"]
    assert [member.outcome for member in result.members] == [
        "validated_pdf",
        "ignored_non_pdf",
    ]
    assert result.members[1].sha256 == hashlib.sha256(b"supplier notes").hexdigest()


def test_expanded_archive_content_is_bounded_before_extraction():
    result = inspect_zip_archive(
        _zip_bytes([("edital.pdf", PDF_BYTES)]),
        limits=ArchiveLimits(max_uncompressed_bytes=10),
    )

    assert result.outcome == "rejected"
    assert result.rejection_reason == "archive_uncompressed_size_exceeded"
    assert result.pdf_members == ()


def test_compressed_archive_and_member_limits_are_enforced():
    archive = _zip_bytes([("edital.pdf", PDF_BYTES)])

    archive_result = inspect_zip_archive(
        archive,
        limits=ArchiveLimits(max_compressed_bytes=len(archive) - 1),
    )
    member_result = inspect_zip_archive(
        archive,
        limits=ArchiveLimits(max_member_uncompressed_bytes=len(PDF_BYTES) - 1),
    )

    assert archive_result.rejection_reason == "archive_compressed_size_exceeded"
    assert member_result.rejection_reason == "member_uncompressed_size_exceeded"


def test_high_compression_ratio_is_rejected_before_member_reading():
    result = inspect_zip_archive(
        _zip_bytes([("edital.pdf", b"A" * 2_000)], compression=zipfile.ZIP_DEFLATED),
        limits=ArchiveLimits(max_compression_ratio=2),
    )

    assert result.outcome == "rejected"
    assert result.rejection_reason == "compression_ratio_exceeded"


def test_excessive_member_count_is_rejected():
    result = inspect_zip_archive(
        _zip_bytes([("one.pdf", PDF_BYTES), ("two.pdf", PDF_BYTES)]),
        limits=ArchiveLimits(max_members=1),
    )

    assert result.rejection_reason == "archive_member_count_exceeded"


@pytest.mark.parametrize("filename", ["../edital.pdf", "/tmp/edital.pdf", "C:\\temp\\edital.pdf"])
def test_zip_slip_paths_are_rejected(filename: str):
    result = inspect_zip_archive(_zip_bytes([(filename, PDF_BYTES)]))

    assert result.outcome == "rejected"
    assert result.rejection_reason == "unsafe_member_path"


@pytest.mark.parametrize("filename", ["attachments.zip", "attachment.pdf"])
def test_nested_archive_is_rejected_without_extraction(filename: str):
    nested = _zip_bytes([("inner.pdf", PDF_BYTES)])
    result = inspect_zip_archive(_zip_bytes([(filename, nested)]))

    assert result.outcome == "rejected"
    assert result.rejection_reason == "nested_archive"
    assert result.pdf_members == ()


def test_encrypted_archive_is_rejected_from_zip_metadata():
    result = inspect_zip_archive(_encrypted_zip_bytes())

    assert result.outcome == "rejected"
    assert result.rejection_reason == "encrypted_archive"


def test_symlink_member_is_rejected():
    link = zipfile.ZipInfo("edital-link.pdf")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16

    result = inspect_zip_archive(_zip_bytes([(link, b"edital.pdf")]))

    assert result.outcome == "rejected"
    assert result.rejection_reason == "symlink_member"


def test_fake_pdf_extension_is_not_available_for_ocr():
    result = inspect_zip_archive(_zip_bytes([("edital.pdf", b"not actually a PDF")]))

    assert result.outcome == "no_valid_pdf"
    assert result.pdf_members == ()
    member = result.to_evidence()["members"][0]
    assert member["outcome"] == "rejected_invalid_pdf_magic"
    assert member["sha256"] == hashlib.sha256(b"not actually a PDF").hexdigest()


def test_archive_evidence_is_stably_sorted_by_member_name():
    first = inspect_zip_archive(
        _zip_bytes([("z.pdf", PDF_BYTES), ("a.pdf", PDF_BYTES)])
    ).to_evidence()
    second = inspect_zip_archive(
        _zip_bytes([("a.pdf", PDF_BYTES), ("z.pdf", PDF_BYTES)])
    ).to_evidence()

    assert first == second
    assert [member["filename"] for member in first["members"]] == ["a.pdf", "z.pdf"]


def test_direct_pdf_magic_remains_renderable_without_archive_handling():
    assert has_pdf_magic(PDF_BYTES) is True
    assert has_pdf_magic(b"<html>not a pdf</html>") is False


def test_invalid_limits_are_rejected_early():
    with pytest.raises(ValueError, match="positive"):
        ArchiveLimits(max_members=0)
