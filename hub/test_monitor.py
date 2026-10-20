# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import DashboardService, monitor
from radar_client import RadarResult


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_failure_does_not_starve_radar(self) -> None:
        service = unittest.mock.Mock()
        service.sample_context = AsyncMock(side_effect=RuntimeError("foreground failed"))
        service.refresh_radar = AsyncMock()

        task = asyncio.create_task(monitor(service))
        await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertGreaterEqual(service.refresh_radar.await_count, 1)

    async def test_refresh_preserves_invalid_result_as_stale_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = DashboardService(Path(directory))
            with patch(
                "app.fetch_radar",
                return_value=RadarResult(
                    status="SUCCESS",
                    run_date="2026-09-28",
                    updated_at="2026-09-28T00:00:00Z",
                    detail="ok",
                ),
            ):
                await service.refresh_radar()
            fresh = service.state()["radar"]
            self.assertFalse(fresh["stale"])
            self.assertEqual(fresh["run_date"], "2026-09-28")

            with patch("app.fetch_radar", side_effect=ValueError("old source date")):
                await service.refresh_radar()
            stale = service.state()["radar"]
            self.assertTrue(stale["stale"])
            self.assertEqual(stale["status"], "SUCCESS")
            self.assertEqual(stale["run_date"], "2026-09-28")


if __name__ == "__main__":
    unittest.main()
