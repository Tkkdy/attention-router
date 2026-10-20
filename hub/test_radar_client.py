# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from radar_client import fetch_radar


class RadarClientTests(unittest.TestCase):
    def test_unconfigured_source_does_not_contact_network(self):
        with patch("urllib.request.urlopen") as request:
            with self.assertRaises(ValueError):
                fetch_radar(url="")
            request.assert_not_called()

    @staticmethod
    def _response(payload: dict) -> io.StringIO:
        return io.StringIO(json.dumps(payload))

    def test_current_singapore_date_is_required(self) -> None:
        payload = {
            "status": "SUCCESS",
            "run_date": "2000-01-01",
            "updated_at": "2000-01-01T00:00:00Z",
            "detail": "ok",
        }
        with patch("urllib.request.urlopen", return_value=self._response(payload)):
            with self.assertRaises(ValueError):
                fetch_radar(url="https://example.invalid/status.json", now=datetime(2026, 9, 28, 3, tzinfo=timezone.utc))

    def test_valid_current_result_is_typed_and_bounded(self) -> None:
        payload = {
            "status": "failed",
            "run_date": "2026-09-28",
            "updated_at": "2026-09-28T02:00:00Z",
            "detail": "Pipeline failed",
        }
        with patch("urllib.request.urlopen", return_value=self._response(payload)):
            result = fetch_radar(url="https://example.invalid/status.json", now=datetime(2026, 9, 28, 3, tzinfo=timezone.utc))
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(result.run_date, "2026-09-28")
        self.assertEqual(result.detail, "Pipeline failed")

    def test_wrong_typed_or_unrenderable_detail_is_rejected(self) -> None:
        base = {"status": "SUCCESS", "run_date": "2026-09-28", "updated_at": None}
        for detail in (42, "x" * 48, "中文"):
            with self.subTest(detail=detail):
                with patch(
                    "urllib.request.urlopen",
                    return_value=self._response({**base, "detail": detail}),
                ):
                    with self.assertRaises(ValueError):
                        fetch_radar(url="https://example.invalid/status.json", now=datetime(2026, 9, 28, 3, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
