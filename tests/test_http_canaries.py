from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from scripts.private_feed_common import (
    CanaryError,
    ConfigurationError,
    sha256_bytes,
    validate_basic_auth_material,
)
from scripts.publish_snapshot import (
    CANARY_USER_AGENT,
    HttpResult,
    _http_request,
    run_http_canaries,
)


class HttpCanaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.body = b"<rss></rss>"
        self.digest = sha256_bytes(self.body)
        self.manifest = {
            "run_id": "run-canary",
            "canary_path": "/feeds/canary.xml",
            "routes": {
                "/feeds/canary.xml": {
                    "object_path": "feeds/canary.xml",
                }
            },
            "objects": {
                "feeds/canary.xml": {
                    "content_type": "application/rss+xml; charset=utf-8",
                    "size": len(self.body),
                    "sha256": self.digest,
                    "last_modified": "2026-07-24T12:00:00Z",
                }
            },
        }
        self.feed_headers = {
            "cache-control": "private, no-cache, max-age=0, no-transform",
            "content-length": str(len(self.body)),
            "content-type": "application/rss+xml; charset=utf-8",
            "etag": f'"{self.digest}"',
            "last-modified": "Fri, 24 Jul 2026 12:00:00 GMT",
            "vary": "Authorization",
        }

    def responses(self) -> list[HttpResult]:
        unauthorized_headers = {
            "cache-control": "no-store",
            "content-type": "text/plain; charset=utf-8",
            "www-authenticate": 'Basic realm="Private feeds"',
        }
        return [
            HttpResult(
                401,
                unauthorized_headers,
                b"Authentication required.\n",
            ),
            HttpResult(
                401,
                unauthorized_headers,
                b"Authentication required.\n",
            ),
            HttpResult(200, self.feed_headers, self.body),
            HttpResult(200, self.feed_headers, b""),
            HttpResult(304, self.feed_headers, b""),
            HttpResult(
                200,
                {"content-type": "application/json; charset=utf-8"},
                json.dumps(
                    {"status": "ok", "run_id": "run-canary"}
                ).encode("utf-8"),
            ),
        ]

    def test_authenticated_and_anonymous_canaries_cover_http_metadata(self) -> None:
        with patch(
            "scripts.publish_snapshot._http_request",
            side_effect=self.responses(),
        ) as request:
            run_http_canaries(
                endpoint="https://pilot.example.workers.dev",
                username="reader",
                password="secret",
                manifest=self.manifest,
            )
        self.assertEqual(request.call_count, 6)
        self.assertEqual(
            request.call_args_list[1].kwargs["password"],
            "secret-invalid",
        )

    def test_http_request_uses_an_identifiable_user_agent(self) -> None:
        response = MagicMock()
        response.status = 401
        response.headers.items.return_value = [
            ("WWW-Authenticate", 'Basic realm="Private feeds"'),
        ]
        response.read.return_value = b"Authentication required.\n"
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        opener = MagicMock()
        opener.open.return_value = response

        with patch(
            "scripts.publish_snapshot.build_opener",
            return_value=opener,
        ):
            result = _http_request(
                endpoint="https://pilot.example.workers.dev",
                path="/feeds/canary.xml",
                method="GET",
                username=None,
                password=None,
                headers={
                    "If-None-Match": '"digest"',
                    "User-Agent": "Python-urllib/3.11",
                },
            )

        request = opener.open.call_args.args[0]
        self.assertEqual(
            request.get_header("User-agent"),
            CANARY_USER_AGENT,
        )
        self.assertEqual(request.get_header("If-none-match"), '"digest"')
        self.assertEqual(result.status, 401)

    def test_canary_rejects_body_hash_divergence(self) -> None:
        responses = self.responses()
        responses[2] = HttpResult(
            200,
            self.feed_headers,
            b"<rss>tampered</rss>",
        )
        with (
            patch(
                "scripts.publish_snapshot._http_request",
                side_effect=responses,
            ),
            self.assertRaisesRegex(CanaryError, "metadata or hash diverged"),
        ):
            run_http_canaries(
                endpoint="https://pilot.example.workers.dev",
                username="reader",
                password="secret",
                manifest=self.manifest,
            )

    def test_canary_accepts_chunked_worker_response_without_content_length(
        self,
    ) -> None:
        responses = self.responses()
        chunked_headers = dict(self.feed_headers)
        chunked_headers.pop("content-length")
        responses[2] = HttpResult(200, chunked_headers, self.body)
        responses[3] = HttpResult(200, chunked_headers, b"")
        responses[4] = HttpResult(304, chunked_headers, b"")

        with patch(
            "scripts.publish_snapshot._http_request",
            side_effect=responses,
        ):
            run_http_canaries(
                endpoint="https://pilot.example.workers.dev",
                username="reader",
                password="secret",
                manifest=self.manifest,
            )

    def test_canary_accepts_head_without_content_length(self) -> None:
        responses = self.responses()
        head_headers = dict(self.feed_headers)
        head_headers.pop("content-length")
        responses[3] = HttpResult(200, head_headers, b"")

        with patch(
            "scripts.publish_snapshot._http_request",
            side_effect=responses,
        ):
            run_http_canaries(
                endpoint="https://pilot.example.workers.dev",
                username="reader",
                password="secret",
                manifest=self.manifest,
            )

    def test_canary_rejects_incorrect_content_length_when_present(self) -> None:
        responses = self.responses()
        invalid_headers = dict(self.feed_headers)
        invalid_headers["content-length"] = "999"
        responses[2] = HttpResult(200, invalid_headers, self.body)

        with (
            patch(
                "scripts.publish_snapshot._http_request",
                side_effect=responses,
            ),
            self.assertRaisesRegex(CanaryError, "metadata or hash diverged"),
        ):
            run_http_canaries(
                endpoint="https://pilot.example.workers.dev",
                username="reader",
                password="secret",
                manifest=self.manifest,
            )

    def test_basic_auth_material_rejects_weak_or_ambiguous_values(self) -> None:
        validate_basic_auth_material(
            "feed-reader",
            "random-password-with-enough-entropy",
        )
        for username, password in (
            ("reader:other", "random-password-with-enough-entropy"),
            (" reader", "random-password-with-enough-entropy"),
            ("reader", "too-short"),
        ):
            with (
                self.subTest(username=username, password=password),
                self.assertRaises(ConfigurationError),
            ):
                validate_basic_auth_material(username, password)


if __name__ == "__main__":
    unittest.main()
