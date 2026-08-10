import io
import unittest
import urllib.error
from unittest import mock

from scripts import http_utils


class HttpRetryTests(unittest.TestCase):
    @mock.patch("scripts.http_utils.time.sleep")
    @mock.patch("scripts.http_utils.urllib.request.urlopen")
    def test_retries_transient_network_error(self, urlopen, sleep):
        response = mock.MagicMock()
        urlopen.side_effect = [urllib.error.URLError("temporary"), response]

        result = http_utils.urlopen_with_retry("https://example.test", timeout=5, base_delay=0.25)

        self.assertIs(result, response)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.25)

    @mock.patch("scripts.http_utils.time.sleep")
    @mock.patch("scripts.http_utils.urllib.request.urlopen")
    def test_uses_retry_after_for_rate_limit(self, urlopen, sleep):
        error = urllib.error.HTTPError(
            "https://example.test",
            429,
            "rate limited",
            {"Retry-After": "2"},
            io.BytesIO(b""),
        )
        response = mock.MagicMock()
        urlopen.side_effect = [error, response]

        result = http_utils.urlopen_with_retry("https://example.test", timeout=5)

        self.assertIs(result, response)
        sleep.assert_called_once_with(2.0)

    @mock.patch("scripts.http_utils.time.sleep")
    @mock.patch("scripts.http_utils.urllib.request.urlopen")
    def test_does_not_retry_non_transient_http_error(self, urlopen, sleep):
        error = urllib.error.HTTPError(
            "https://example.test",
            400,
            "bad request",
            {},
            io.BytesIO(b""),
        )
        urlopen.side_effect = error

        with self.assertRaises(urllib.error.HTTPError):
            http_utils.urlopen_with_retry("https://example.test", timeout=5)

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
