#!/usr/bin/env python3
"""Recycle the bounded FlareSolverr tmpfs when full, preferring an idle browser."""
import json
import subprocess


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=15)


def main():
    container = json.loads(docker("inspect", "flaresolverr"))[0]
    if not container["State"]["Running"]:
        return
    if "/tmp" not in container["HostConfig"].get("Tmpfs", {}):
        raise RuntimeError("Expected the managed /tmp tmpfs; refusing to restart")

    usage = json.loads(docker(
        "exec", "flaresolverr", "python", "-c",
        "import json,os; s=os.statvfs('/tmp'); "
        "print(json.dumps({'blocks':1-s.f_bavail/s.f_blocks,"
        "'inodes':1-s.f_favail/s.f_files}))",
    ))
    utilization = max(usage.values())
    unhealthy = container["State"].get("Health", {}).get("Status") == "unhealthy"
    if utilization < 0.80 and not unhealthy:
        return

    processes = docker("top", "flaresolverr", "-eo", "comm").lower()
    browser_active = any(name in processes for name in ("chromium", "chromedriver", "chrome"))
    if browser_active and utilization < 0.95 and not unhealthy:
        print("Temporary storage is above 80%; waiting for the active browser to finish")
        return

    print(f"Restarting FlareSolverr: tmpfs={utilization:.1%}, unhealthy={unhealthy}", flush=True)
    subprocess.run(["docker", "restart", "--time", "30", "flaresolverr"],
                   check=True, timeout=60)


if __name__ == "__main__":
    main()
