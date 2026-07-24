from __future__ import annotations

import base64
import hashlib
import unittest
from datetime import datetime, timezone

import boto3
from botocore.stub import Stubber

from scripts.private_feed_common import (
    PreconditionFailed,
    S3ObjectStore,
    StorageOperationError,
)


class S3ObjectStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = boto3.client(
            "s3",
            endpoint_url="https://account.r2.cloudflarestorage.com",
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
            region_name="auto",
        )
        self.stubber = Stubber(self.client)
        self.store = S3ObjectStore(self.client, "private-bucket")

    def tearDown(self) -> None:
        self.stubber.assert_no_pending_responses()

    def expected_put(self, *, if_none_match: bool = False):
        data = b"immutable bytes"
        arguments = {
            "Bucket": "private-bucket",
            "Key": "snapshots/run/object",
            "Body": data,
            "ContentType": "application/octet-stream",
            "CacheControl": "private, no-cache, max-age=0",
            "ContentMD5": base64.b64encode(
                hashlib.md5(data, usedforsecurity=False).digest()
            ).decode("ascii"),
            "Metadata": {"sha256": "digest"},
        }
        if if_none_match:
            arguments["IfNoneMatch"] = "*"
        return data, arguments

    def test_conditional_put_uses_integrity_header_and_private_cache(self) -> None:
        data, expected = self.expected_put(if_none_match=True)
        self.stubber.add_response(
            "put_object",
            {"ETag": '"upload-etag"'},
            expected,
        )
        self.stubber.add_response(
            "head_object",
            {
                "ETag": '"stored-etag"',
                "ContentLength": len(data),
                "LastModified": datetime(2026, 7, 24, tzinfo=timezone.utc),
                "ContentType": "application/octet-stream",
                "Metadata": {"sha256": "digest"},
            },
            {
                "Bucket": "private-bucket",
                "Key": "snapshots/run/object",
            },
        )

        with self.stubber:
            stored = self.store.put(
                "snapshots/run/object",
                data,
                content_type="application/octet-stream",
                metadata={"sha256": "digest"},
                if_none_match=True,
            )
        self.assertEqual(stored.etag, '"stored-etag"')
        self.assertEqual(stored.metadata["sha256"], "digest")

    def test_precondition_failure_is_reported_as_a_concurrency_error(self) -> None:
        data, expected = self.expected_put(if_none_match=True)
        self.stubber.add_client_error(
            "put_object",
            service_error_code="PreconditionFailed",
            service_message="condition did not match",
            http_status_code=412,
            expected_params=expected,
        )

        with self.stubber, self.assertRaises(PreconditionFailed):
            self.store.put(
                "snapshots/run/object",
                data,
                content_type="application/octet-stream",
                metadata={"sha256": "digest"},
                if_none_match=True,
            )

    def test_partial_delete_failure_is_not_silently_accepted(self) -> None:
        self.stubber.add_response(
            "delete_objects",
            {
                "Deleted": [{"Key": "snapshots/run/good"}],
                "Errors": [
                    {
                        "Key": "snapshots/run/bad",
                        "Code": "AccessDenied",
                        "Message": "denied",
                    }
                ],
            },
            {
                "Bucket": "private-bucket",
                "Delete": {
                    "Objects": [
                        {"Key": "snapshots/run/good"},
                        {"Key": "snapshots/run/bad"},
                    ]
                },
            },
        )

        with self.stubber, self.assertRaisesRegex(
            StorageOperationError,
            "deletion failures",
        ):
            self.store.delete_keys(
                ["snapshots/run/good", "snapshots/run/bad"]
            )


if __name__ == "__main__":
    unittest.main()
