"""Multipart resume preserves additional checksums; source rehash remains separate."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "aws" / "source_upload.py"
spec = importlib.util.spec_from_file_location("source_upload_under_test", SCRIPT)
upload = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upload)


def part(number, data, **extra):
    return {"PartNumber": number, "Size": len(data), "ETag": '"' + hashlib.md5(data).hexdigest() + '"', **extra}


class S3:
    def __init__(self, parts):
        self.parts = parts
        self.uploads = [{"Key": "object", "UploadId": "interrupted", "ChecksumAlgorithm": "CRC32",
                         "ChecksumType": "COMPOSITE"}]
        self.sent = []
        self.completed = None
        self.omit_new_checksum = False

    def get_paginator(self, operation):
        outer = self
        class Pager:
            def paginate(self, **kwargs):
                assert kwargs["ExpectedBucketOwner"] == "111122223333"
                if operation == "list_multipart_uploads":
                    return [{"Uploads": outer.uploads}]
                assert operation == "list_parts"
                # Multiple pages demonstrate retained part/checksum pagination.
                return [{"Parts": [p]} for p in outer.parts]
        return Pager()

    def upload_part(self, **kwargs):
        self.sent.append(kwargs)
        assert kwargs["ChecksumAlgorithm"] == "CRC32"
        result = part(kwargs["PartNumber"], kwargs["Body"])
        if not self.omit_new_checksum:
            result["ChecksumCRC32"] = "new-checksum"
        return result

    def complete_multipart_upload(self, **kwargs):
        self.completed = kwargs


def send(tmp_path, api):
    path = tmp_path / "invented.txt"
    path.write_bytes(b"aaaabbbbcc")
    return upload.upload_source(api, path, "invented-bucket", "object", "111122223333", {}, chunk_bytes=4)


def test_crc32_preserved_for_reused_and_new_parts(tmp_path):
    api = S3([part(1, b"aaaa", ChecksumCRC32="first"), part(2, b"bbbb", ChecksumCRC32="second")])
    result = send(tmp_path, api)
    assert result == {"resumed": True, "reused_parts": 2, "total_parts": 3}
    assert [p["PartNumber"] for p in api.sent] == [3]
    assert api.completed["ChecksumType"] == "COMPOSITE"
    assert [p["ChecksumCRC32"] for p in api.completed["MultipartUpload"]["Parts"]] == ["first", "second", "new-checksum"]


def test_old_part_without_required_checksum_reuploaded(tmp_path):
    api = S3([part(1, b"aaaa")])
    assert send(tmp_path, api)["reused_parts"] == 0
    assert [p["PartNumber"] for p in api.sent] == [1, 2, 3]


def test_checksum_missing_from_new_response_cannot_complete(tmp_path):
    api = S3([])
    api.omit_new_checksum = True
    with pytest.raises(ValueError, match="lacks the original"):
        send(tmp_path, api)
    assert api.completed is None


def test_changed_old_parts_replaced_and_trailing_parts_excluded(tmp_path):
    api = S3([part(1, b"WRNG", ChecksumCRC32="wrong"), part(4, b"trailing", ChecksumCRC32="stale")])
    assert send(tmp_path, api)["reused_parts"] == 0
    assert [p["PartNumber"] for p in api.completed["MultipartUpload"]["Parts"]] == [1, 2, 3]


def test_ambiguous_uploads_preserved_without_mutation(tmp_path):
    api = S3([])
    api.uploads *= 2
    with pytest.raises(ValueError, match="Ambiguous"):
        send(tmp_path, api)
    assert not api.sent and api.completed is None
