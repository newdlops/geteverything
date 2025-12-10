# run_queue.py
import asyncio
import os
import subprocess
import sys
from datetime import datetime

MAX_CONCURRENT = 5   # 동시에 돌릴 spider 수 (1코어면 2~3 정도가 안전)
MAX_QUEUE = 20       # 큐에 쌓일 수 있는 최대 job 수

# 여기서 job은 "어떤 spider를 돌릴지" 정도만 가진다고 가정
class Job:
    def __init__(self, site_name: str):
        self.site_name = site_name
        self.created_at = datetime.now()

    def __repr__(self):
        return f"<Job spider={self.site_name} created_at={self.created_at}>"

queue: asyncio.Queue[Job] = asyncio.Queue(maxsize=MAX_QUEUE)
running_jobs: set[str] = set()

async def run_spider(job: Job):
    print(f"[START] {job}")

    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")

    # 여기서 실제 scrapy 실행 (venv 경로/프로젝트 경로 맞춰서 수정)
    proc = await asyncio.create_subprocess_exec(
        "python", "-m", f"crawlers.{job.site_name}.crawler.crawler",
        # stdout=asyncio.subprocess.PIPE,
        # stderr=asyncio.subprocess.PIPE,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    stdout, stderr = await proc.communicate()
    print(f"[END] {job} exit={proc.returncode}")
    if proc.returncode != 0:
        print(f"[ERROR] {job} stderr={stderr.decode(errors='ignore')}")

async def worker(semaphore: asyncio.Semaphore):
    while True:
        job = await queue.get()
        running_jobs.add(job.site_name)
        async with semaphore:
            try:
                await run_spider(job)
            finally:
                running_jobs.discard(job.site_name)
                queue.task_done()

async def producer():
    """
    여기서 주기적으로 job을 집어넣는다고 가정.
    예: 각 사이트를 30분마다 한 번씩 돌리는 스케줄.
    """
    sites = [
        "ppomppu",
        "fmkorea",
        "eomisae",
        "coolnjoy",
        "arca",
    ]

    while True:
        for site_name in sites:
            if site_name in running_jobs:
                print(f"{site_name}은 실행중입니다.")
                continue
            job = Job(site_name)
            if any(job.site_name == q_job.site_name for q_job in queue._queue):
                print(f"{job.site_name}은 이미 큐에 있습니다.")
            try:
                # 큐가 꽉 차 있으면 QueueFull 예외 발생
                queue.put_nowait(job)
                print(f"[ENQUEUE] {job}")
            except asyncio.QueueFull:
                # *** 여기서 '무한정 쌓이지 않게' 정책을 정하면 됨 ***
                print(f"[SKIP] queue full, skip job: {job}")
                # 또는: 오래된 job 하나 빼고 새로 넣기 같은 전략도 가능
        # 한 번 사이트 전체 enqueue 후 1분 쉬기
        await asyncio.sleep(1 * 60)

async def main():
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    # 워커 여러 개 생성 (실제로는 MAX_CONCURRENT보다 적당히 크게 3~5 정도)
    workers = [asyncio.create_task(worker(semaphore)) for _ in range(5)]

    # producer도 태스크로 실행
    prod = asyncio.create_task(producer())

    await asyncio.gather(prod, *workers)

if __name__ == "__main__":
    asyncio.run(main())
