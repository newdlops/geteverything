from __future__ import annotations

"""
Multi-site crawler orchestrator.

Defaults are tuned for a small worker (e.g., 2 vCPU / 12GB):
- Limit total concurrent spiders (`CRAWLER_MAX_CONCURRENT`, default: 3 on 2 vCPU)
- Limit concurrent Selenium-based spiders (`CRAWLER_MAX_SELENIUM`, default: 1 on 2 vCPU)

Usage:
- Run forever (default sites): `python run_queue.py`
- Run selected sites forever: `CRAWLER_SITES=fmkorea,arca python run_queue.py`
- Run selected sites once: `python run_queue.py --once --sites fmkorea,arca`

Key environment variables:
- `CRAWLER_SITES`: comma-separated site list (e.g., "ppomppu,fmkorea")
- `CRAWLER_MAX_CONCURRENT`: total concurrent spiders (default depends on CPU)
- `CRAWLER_MAX_SELENIUM`: concurrent Selenium spiders cap (default depends on CPU)
- `CRAWLER_SELENIUM_SITES`: comma-separated selenium sites (default: "fmkorea,arca")
- `CRAWLER_INTERVAL_SECONDS`: default interval between successful runs
- `CRAWLER_INTERVAL_<SITE>_SECONDS`: per-site interval override
- `CRAWLER_MAX_RUNTIME_SECONDS`: default max runtime per run (seconds)
- `CRAWLER_MAX_RUNTIME_<SITE>_SECONDS`: per-site runtime override
- `CRAWLER_JITTER_SECONDS`: startup jitter to avoid spikes
- `CRAWLER_BACKOFF_BASE_SECONDS`: base backoff on failure
- `CRAWLER_BACKOFF_MAX_SECONDS`: max backoff on repeated failures

Shutdown:
- On SIGINT/SIGTERM, terminates running spiders (SIGTERM -> SIGKILL after grace).
"""

import argparse
import asyncio
import contextlib
import os
import random
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# DEFAULT_SITES: tuple[str, ...] = ("ppomppu", "fmkorea", "eomisae", "coolnjoy", "arca")
DEFAULT_SITES: tuple[str, ...] = ("arca","fmkorea")
DEFAULT_SELENIUM_SITES: set[str] = {"fmkorea", "arca"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(message: str, *, site: str | None = None) -> None:
    prefix = f"[{_now()}]"
    if site:
        prefix += f"[{site}]"
    print(f"{prefix} {message}", flush=True)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _default_max_concurrent(cpu_count: int) -> int:
    # 2 vCPU / 12GB 기준: 전체 3개(셀레니움 1 + 일반 2) 정도가 안정적.
    if cpu_count <= 2:
        return 3
    return min(8, cpu_count + 1)


def _default_max_selenium(cpu_count: int) -> int:
    # headless Chrome은 CPU/메모리 사용량이 커서 보수적으로 제한.
    if cpu_count <= 2:
        return 1
    return min(2, max(1, cpu_count // 2))


@dataclass(frozen=True)
class SiteConfig:
    name: str
    interval_seconds: int
    max_runtime_seconds: int
    uses_selenium: bool

    @property
    def module(self) -> str:
        return f"crawlers.{self.name}.crawler.crawler"


def _parse_sites(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_SITES)
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


def _build_site_configs(
    site_names: list[str],
    *,
    default_interval_seconds: int,
    default_max_runtime_seconds: int,
    selenium_sites: set[str],
) -> list[SiteConfig]:
    configs: list[SiteConfig] = []
    for site in site_names:
        interval_seconds = _env_int(f"CRAWLER_INTERVAL_{site.upper()}_SECONDS", default_interval_seconds)
        max_runtime_seconds = _env_int(f"CRAWLER_MAX_RUNTIME_{site.upper()}_SECONDS", default_max_runtime_seconds)
        configs.append(
            SiteConfig(
                name=site,
                interval_seconds=max(0, interval_seconds),
                max_runtime_seconds=max(60, max_runtime_seconds),
                uses_selenium=site in selenium_sites,
            )
        )
    return configs


def _project_root() -> Path:
    # 이 파일은 `crawlers/run_queue.py`에 있으므로, 패키지 루트는 상위 디렉터리.
    return Path(__file__).resolve().parent.parent


def _build_child_env(project_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    return env


async def _terminate_process(proc: asyncio.subprocess.Process, *, site: str, grace_seconds: int = 15) -> None:
    if proc.returncode is not None:
        return

    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=grace_seconds)
        return
    except asyncio.TimeoutError:
        pass

    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        return

    await proc.wait()
    _log("killed (grace timeout)", site=site)


async def _run_spider_once(
    site: SiteConfig,
    *,
    project_root: Path,
    child_env: dict[str, str],
    stop_event: asyncio.Event,
    running: dict[str, asyncio.subprocess.Process],
) -> int:
    if stop_event.is_set():
        return 0

    _log("start", site=site.name)
    started = time.monotonic()

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        site.module,
        cwd=str(project_root),
        env=child_env,
        start_new_session=(os.name != "nt"),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    running[site.name] = proc

    try:
        wait_task = asyncio.create_task(proc.wait())
        stop_task = asyncio.create_task(stop_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {wait_task, stop_task},
                timeout=site.max_runtime_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if stop_task in done:
                _log("shutdown requested -> terminate", site=site.name)
                await _terminate_process(proc, site=site.name)
                return 130

            if wait_task not in done:
                _log(f"timeout after {site.max_runtime_seconds}s -> terminate", site=site.name)
                await _terminate_process(proc, site=site.name)
                return 124

            return proc.returncode or 0
        finally:
            for task in (wait_task, stop_task):
                if not task.done():
                    task.cancel()
            for task in (wait_task, stop_task):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    finally:
        running.pop(site.name, None)
        elapsed = int(time.monotonic() - started)
        _log(f"end exit={proc.returncode} elapsed={elapsed}s", site=site.name)


async def _run_spider_once_with_limits(
    site: SiteConfig,
    *,
    project_root: Path,
    child_env: dict[str, str],
    stop_event: asyncio.Event,
    overall_sem: asyncio.Semaphore,
    selenium_sem: asyncio.Semaphore,
    running: dict[str, asyncio.subprocess.Process],
) -> int:
    async with overall_sem:
        if site.uses_selenium:
            async with selenium_sem:
                return await _run_spider_once(
                    site,
                    project_root=project_root,
                    child_env=child_env,
                    stop_event=stop_event,
                    running=running,
                )
        return await _run_spider_once(
            site,
            project_root=project_root,
            child_env=child_env,
            stop_event=stop_event,
            running=running,
        )


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: int) -> None:
    if seconds <= 0:
        return
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return


async def _site_loop(
    site: SiteConfig,
    *,
    project_root: Path,
    child_env: dict[str, str],
    stop_event: asyncio.Event,
    overall_sem: asyncio.Semaphore,
    selenium_sem: asyncio.Semaphore,
    running: dict[str, asyncio.subprocess.Process],
    jitter_seconds: int,
    backoff_base_seconds: int,
    backoff_max_seconds: int,
) -> None:
    # 시작 시에 살짝 분산(동시 스파이크 방지)
    if jitter_seconds > 0:
        await _sleep_or_stop(stop_event, random.randint(0, jitter_seconds))

    failures = 0
    while not stop_event.is_set():
        async with overall_sem:
            if site.uses_selenium:
                async with selenium_sem:
                    exit_code = await _run_spider_once(
                        site,
                        project_root=project_root,
                        child_env=child_env,
                        stop_event=stop_event,
                        running=running,
                    )
            else:
                exit_code = await _run_spider_once(
                    site,
                    project_root=project_root,
                    child_env=child_env,
                    stop_event=stop_event,
                    running=running,
                )

        if stop_event.is_set():
            return

        if exit_code == 0:
            failures = 0
            await _sleep_or_stop(stop_event, site.interval_seconds)
            continue

        failures += 1
        backoff = min(backoff_max_seconds, backoff_base_seconds * (2 ** min(failures, 6)))
        backoff = int(backoff * random.uniform(0.8, 1.2))
        _log(f"failed exit={exit_code} -> backoff {backoff}s (failures={failures})", site=site.name)
        await _sleep_or_stop(stop_event, backoff)


async def _shutdown_watcher(
    stop_event: asyncio.Event, running: dict[str, asyncio.subprocess.Process]
) -> None:
    await stop_event.wait()
    for site, proc in list(running.items()):
        _log("shutdown: terminate running process", site=site)
        await _terminate_process(proc, site=site)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawler orchestrator (multi-site)")
    parser.add_argument(
        "--sites",
        help="comma-separated site list (default: all)",
        default=os.getenv("CRAWLER_SITES", ""),
    )
    parser.add_argument("--once", action="store_true", help="run each selected site once and exit")
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()

    cpu_count = max(1, os.cpu_count() or 1)
    max_concurrent = _env_int("CRAWLER_MAX_CONCURRENT", _default_max_concurrent(cpu_count))
    max_selenium = _env_int("CRAWLER_MAX_SELENIUM", _default_max_selenium(cpu_count))
    default_interval_seconds = _env_int("CRAWLER_INTERVAL_SECONDS", 60)
    default_max_runtime_seconds = _env_int("CRAWLER_MAX_RUNTIME_SECONDS", 60 * 60)
    jitter_seconds = _env_int("CRAWLER_JITTER_SECONDS", 10)
    backoff_base_seconds = _env_int("CRAWLER_BACKOFF_BASE_SECONDS", 15)
    backoff_max_seconds = _env_int("CRAWLER_BACKOFF_MAX_SECONDS", 10 * 60)

    selenium_sites = set(os.getenv("CRAWLER_SELENIUM_SITES", "" ).split(",")) if os.getenv("CRAWLER_SELENIUM_SITES") else set(DEFAULT_SELENIUM_SITES)
    selenium_sites = {s.strip() for s in selenium_sites if s.strip()}

    site_names = _parse_sites(args.sites)
    sites = _build_site_configs(
        site_names,
        default_interval_seconds=default_interval_seconds,
        default_max_runtime_seconds=default_max_runtime_seconds,
        selenium_sites=selenium_sites,
    )

    project_root = _project_root()
    child_env = _build_child_env(project_root)

    _log(
        f"start cpu={cpu_count} max_concurrent={max_concurrent} max_selenium={max_selenium} sites={','.join([s.name for s in sites])}"
    )

    stop_event = asyncio.Event()
    running: dict[str, asyncio.subprocess.Process] = {}

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())

    overall_sem = asyncio.Semaphore(max(1, max_concurrent))
    selenium_sem = asyncio.Semaphore(max(1, max_selenium))

    if args.once:
        tasks: list[asyncio.Task[int]] = []
        async with asyncio.TaskGroup() as tg:
            for site in sites:
                tasks.append(
                    tg.create_task(
                        _run_spider_once_with_limits(
                            site,
                            project_root=project_root,
                            child_env=child_env,
                            stop_event=stop_event,
                            overall_sem=overall_sem,
                            selenium_sem=selenium_sem,
                            running=running,
                        )
                    )
                )
        exit_codes = [t.result() for t in tasks]
        return 0 if all(code == 0 for code in exit_codes) else 1

    async with asyncio.TaskGroup() as tg:
        tg.create_task(_shutdown_watcher(stop_event, running))
        for site in sites:
            tg.create_task(
                _site_loop(
                    site,
                    project_root=project_root,
                    child_env=child_env,
                    stop_event=stop_event,
                    overall_sem=overall_sem,
                    selenium_sem=selenium_sem,
                    running=running,
                    jitter_seconds=jitter_seconds,
                    backoff_base_seconds=backoff_base_seconds,
                    backoff_max_seconds=backoff_max_seconds,
                )
            )

    _log("stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
