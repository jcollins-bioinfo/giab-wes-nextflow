import hashlib
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('source_upload', Path(__file__).resolve().parents[1] / 'scripts/aws/source_upload.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeS3:
    def __init__(self, uploads, parts):
        self.uploads, self.parts, self.sent, self.completed = uploads, parts, [], None
    def get_paginator(self, op):
        rows = self.uploads if op == 'list_multipart_uploads' else self.parts
        field = 'Uploads' if op == 'list_multipart_uploads' else 'Parts'
        class Pages:
            def paginate(self, **kw):
                return [{field: rows[:1]}, {field: rows[1:]}]
        return Pages()
    def upload_part(self, **kw):
        self.sent.append((kw['PartNumber'], kw['Body']))
        return {'ETag': '"' + hashlib.md5(kw['Body']).hexdigest() + '"'}
    def complete_multipart_upload(self, **kw):
        self.completed = kw['MultipartUpload']['Parts']


def test_resume_reuses_verified_part_replaces_mismatch_and_finishes_tail(tmp_path):
    path = tmp_path / 'source'; path.write_bytes(b'aaaabbbbcc')
    s3 = FakeS3([{'Key': 'exact', 'UploadId': 'old'}], [
        {'PartNumber': 1, 'Size': 4, 'ETag': '"' + hashlib.md5(b'aaaa').hexdigest() + '"'},
        {'PartNumber': 2, 'Size': 4, 'ETag': '"wrong"'}])
    result = module.upload_source(s3, path, 'bucket', 'exact', 'account', {}, chunk_bytes=4)
    assert result == {'resumed': True, 'reused_parts': 1, 'total_parts': 3}
    assert s3.sent == [(2, b'bbbb'), (3, b'cc')]
    assert [p['PartNumber'] for p in s3.completed] == [1, 2, 3]


def test_ambiguous_uploads_fail_without_mutation(tmp_path):
    s3 = FakeS3([{'Key': 'exact', 'UploadId': 'a'}, {'Key': 'exact', 'UploadId': 'b'}], [])
    with pytest.raises(ValueError, match='Ambiguous'):
        module.upload_source(s3, tmp_path / 'source', 'bucket', 'exact', 'account', {})
    assert not s3.sent and s3.completed is None
