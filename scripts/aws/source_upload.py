"""Resume a matching multipart upload; full destination rehash is still required."""
import hashlib

CHECKSUM_FIELDS = {"ChecksumCRC32", "ChecksumCRC32C", "ChecksumCRC64NVME", "ChecksumSHA1",
                   "ChecksumSHA256", "ChecksumSHA512", "ChecksumMD5", "ChecksumXXHASH64",
                   "ChecksumXXHASH3", "ChecksumXXHASH128"}


def upload_source(s3, path, bucket, key, account, metadata, chunk_bytes=16 << 20):
    uploads = [row for page in s3.get_paginator('list_multipart_uploads').paginate(
        Bucket=bucket, Prefix=key, ExpectedBucketOwner=account)
        for row in page.get('Uploads', []) if row['Key'] == key]
    if len(uploads) > 1:
        raise ValueError('Ambiguous interrupted uploads; private reconciliation required')
    if not uploads:
        from boto3.s3.transfer import TransferConfig
        s3.upload_file(str(path), bucket, key,
                       ExtraArgs={'ExpectedBucketOwner': account, 'Metadata': metadata},
                       Config=TransferConfig(max_concurrency=2, multipart_chunksize=chunk_bytes))
        return {'resumed': False}
    upload_id = uploads[0]['UploadId']
    algorithm = uploads[0].get('ChecksumAlgorithm')
    checksum_type = uploads[0].get('ChecksumType')
    checksum_key = 'Checksum' + algorithm if algorithm else None
    if checksum_key and checksum_key not in CHECKSUM_FIELDS:
        raise ValueError('Interrupted upload checksum algorithm is unsupported')
    existing = {part['PartNumber']: part for page in s3.get_paginator('list_parts').paginate(
        Bucket=bucket, Key=key, UploadId=upload_id, ExpectedBucketOwner=account)
        for part in page.get('Parts', [])}
    completed = []
    reused = 0
    with path.open('rb') as stream:
        for number, data in enumerate(iter(lambda: stream.read(chunk_bytes), b''), 1):
            part = existing.get(number, {})
            # ETag is only an optimization for individual old parts. It never
            # authenticates the source or replaces the mandatory final rehash.
            etag = '"' + hashlib.md5(data).hexdigest() + '"'
            if (part.get('Size') == len(data) and part.get('ETag') == etag
                    and (not checksum_key or part.get(checksum_key))):
                result = part
                reused += 1
            else:
                result = s3.upload_part(Bucket=bucket, Key=key, UploadId=upload_id,
                    PartNumber=number, Body=data, ExpectedBucketOwner=account,
                    **({'ChecksumAlgorithm': algorithm} if algorithm else {}))
            if checksum_key and not result.get(checksum_key):
                raise ValueError('Uploaded part lacks the original multipart checksum')
            completed.append({'PartNumber': number, 'ETag': result['ETag'],
                              **{name: value for name, value in result.items() if name in CHECKSUM_FIELDS}})
    if not completed:
        raise ValueError('Cannot complete an empty scientific source')
    s3.complete_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id,
        MultipartUpload={'Parts': completed}, ExpectedBucketOwner=account,
        **({'ChecksumType': checksum_type} if checksum_type else {}))
    return {'resumed': True, 'reused_parts': reused, 'total_parts': len(completed)}
