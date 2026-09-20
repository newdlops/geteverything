import asyncio
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from crawlers import run_queue


class RunQueueTests(IsolatedAsyncioTestCase):
    async def test_once_obeys_total_and_selenium_concurrency_limits(self):
        active = 0
        active_selenium = 0
        peak_active = 0
        peak_selenium = 0
        completed = []

        async def run_spider(site, **kwargs):
            nonlocal active, active_selenium, peak_active, peak_selenium
            active += 1
            active_selenium += site.uses_selenium
            peak_active = max(peak_active, active)
            peak_selenium = max(peak_selenium, active_selenium)
            await asyncio.sleep(0)
            active -= 1
            active_selenium -= site.uses_selenium
            completed.append(site.name)
            return 0

        overall_sem = asyncio.Semaphore(2)
        selenium_sem = asyncio.Semaphore(1)
        stop_event = asyncio.Event()
        running = {}
        sites = [
            run_queue.SiteConfig(name=str(index), interval_seconds=60, max_runtime_seconds=60, uses_selenium=index % 2 == 0)
            for index in range(6)
        ]
        with patch.object(run_queue, "_run_spider_once", side_effect=run_spider):
            results = await asyncio.wait_for(asyncio.gather(*(
                run_queue._run_spider_once_with_limits(
                    site,
                    project_root=Path("."),
                    child_env={},
                    stop_event=stop_event,
                    overall_sem=overall_sem,
                    selenium_sem=selenium_sem,
                    running=running,
                )
                for site in sites
            )), timeout=2)

        self.assertEqual(results, [0] * len(sites))
        self.assertCountEqual(completed, [site.name for site in sites])
        self.assertEqual(peak_active, 2)
        self.assertEqual(peak_selenium, 1)

    async def test_recurring_runs_obey_limits_and_reset_failure_backoff_after_success(self):
        for uses_selenium in (False, True):
            with self.subTest(uses_selenium=uses_selenium):
                stop_event = asyncio.Event()
                overall_sem = asyncio.Semaphore(1)
                selenium_sem = asyncio.Semaphore(1)
                exit_codes = iter([0, 1, 1, 0, 1])
                delays = []

                async def run_spider(site, **kwargs):
                    self.assertTrue(overall_sem.locked())
                    self.assertEqual(selenium_sem.locked(), uses_selenium)
                    return next(exit_codes)

                async def sleep_or_stop(event, seconds):
                    self.assertFalse(overall_sem.locked())
                    self.assertFalse(selenium_sem.locked())
                    delays.append(seconds)
                    if len(delays) == 5:
                        event.set()

                with (
                    patch.object(run_queue, "_run_spider_once", side_effect=run_spider) as run,
                    patch.object(run_queue, "_sleep_or_stop", side_effect=sleep_or_stop),
                    patch.object(run_queue.random, "uniform", return_value=1.0),
                    patch.object(run_queue, "_log"),
                ):
                    await asyncio.wait_for(run_queue._site_loop(
                        run_queue.SiteConfig("test", 60, 60, uses_selenium),
                        project_root=Path("."),
                        child_env={},
                        stop_event=stop_event,
                        overall_sem=overall_sem,
                        selenium_sem=selenium_sem,
                        running={},
                        jitter_seconds=0,
                        backoff_base_seconds=15,
                        backoff_max_seconds=600,
                    ), timeout=2)

                self.assertEqual(run.call_count, 5)
                self.assertEqual(delays, [60, 30, 60, 60, 30])

    async def test_shutdown_during_run_skips_interval_and_backoff(self):
        stop_event = asyncio.Event()

        async def run_spider(site, **kwargs):
            stop_event.set()
            return 130

        with (
            patch.object(run_queue, "_run_spider_once", side_effect=run_spider),
            patch.object(run_queue, "_sleep_or_stop") as sleep,
        ):
            await asyncio.wait_for(run_queue._site_loop(
                run_queue.SiteConfig("test", 60, 60, False),
                project_root=Path("."),
                child_env={},
                stop_event=stop_event,
                overall_sem=asyncio.Semaphore(1),
                selenium_sem=asyncio.Semaphore(1),
                running={},
                jitter_seconds=0,
                backoff_base_seconds=15,
                backoff_max_seconds=600,
            ), timeout=2)

        sleep.assert_not_called()
