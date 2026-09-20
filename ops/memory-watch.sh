#!/bin/sh
set -eu

set -- $(awk '
    /^MemAvailable:/ { available=$2 }
    /^SwapTotal:/ { total=$2 }
    /^SwapFree:/ { free=$2 }
    END { print available, total, free }
' /proc/meminfo)
available_kb=$1
swap_total_kb=$2
swap_used_kb=$((swap_total_kb - $3))
summary="available_mib=$((available_kb / 1024)) swap_used_mib=$((swap_used_kb / 1024)) swap_total_mib=$((swap_total_kb / 1024))"
printf '%s\n' "$summary"
if [ -r /proc/pressure/memory ]; then
    cat /proc/pressure/memory
fi

if [ "$available_kb" -lt 153600 ] || { [ "$swap_total_kb" -gt 0 ] && [ "$swap_used_kb" -gt $((swap_total_kb * 3 / 4)) ]; }; then
    logger -p daemon.warning -t geteverything-memory "Memory pressure: $summary"
    ps -eo pid,comm,rss --sort=-rss | head -n 11
    for group in /sys/fs/cgroup/system.slice/docker-*.scope; do
        [ -d "$group" ] || continue
        printf '%s\n' "${group##*/}"
        for metric in memory.current memory.swap.current memory.events; do
            if [ -r "$group/$metric" ]; then
                printf '%s: ' "$metric"
                tr '\n' ' ' < "$group/$metric"
                printf '\n'
            fi
        done
    done
fi
