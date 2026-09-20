#!/usr/bin/env bash
# Run on instance-20251213-1303 with sudo; see oci-memory-guard.md.
set -euo pipefail
umask 077

phase=${1:-status}
if [[ $(hostname) != instance-20251213-1303 || $EUID -ne 0 ]]; then
    echo 'This script requires root on instance-20251213-1303.' >&2
    exit 1
fi

backup() {
    backup_dir=$(mktemp -d /var/backups/geteverything-oom.XXXXXXXX)
    echo "Backup: $backup_dir"
}

update_service() {
    local service=$1 limit=$2 reservation=$3
    shift 3
    docker service inspect "$service" > "$backup_dir/$service.json"
    echo "Updating $service: memory limit $limit, reservation $reservation"
    timeout 180s docker service update --detach=false --no-resolve-image \
        --limit-memory "$limit" --reserve-memory "$reservation" \
        --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 \
        --update-parallelism 1 --update-failure-action rollback \
        --update-monitor 20s "$@" "$service" > "$backup_dir/$service-update.log" 2>&1 || {
            tail -n 8 "$backup_dir/$service-update.log"
            return 1
        }
    local state
    state=$(docker service inspect --format '{{if .UpdateStatus}}{{.UpdateStatus.State}}{{end}}' "$service")
    if [[ "$state" != completed ]]; then
        echo "$service update state: $state; inspect $backup_dir/$service-update.log" >&2
        return 1
    fi
    echo "$service: update completed"
}

case "$phase" in
    host)
        backup
        cp -a /etc/fstab "$backup_dir/fstab"
        systemctl show fwupd.service -p MemoryHigh -p MemoryMax -p MemorySwapMax \
            > "$backup_dir/fwupd-properties.txt"
        if [[ -d /etc/systemd/system.control/fwupd.service.d ]]; then
            cp -a /etc/systemd/system.control/fwupd.service.d "$backup_dir/"
        fi
        if ! swapon --noheadings --show=NAME | awk '$1 == "/swapfile" { found=1 } END { exit !found }'; then
            if [[ -e /swapfile ]]; then
                echo 'An inactive /swapfile already exists; inspect it before proceeding.' >&2
                exit 1
            fi
            available_kb=$(df -Pk / | awk 'NR == 2 {print $4}')
            if (( available_kb < 4194304 )); then
                echo 'At least 4 GiB free disk space is required.' >&2
                exit 1
            fi
            install -m 600 /dev/null /swapfile
            fallocate -l 2G /swapfile
            mkswap /swapfile
            swapon /swapfile
        fi
        if ! awk '$1 == "/swapfile" && $3 == "swap" { found=1 } END { exit !found }' /etc/fstab; then
            printf '\n# geteverything: buffer temporary memory pressure on the 1 GiB host\n/swapfile none swap sw,nofail 0 0\n' >> /etc/fstab
        fi
        systemctl daemon-reload
        systemctl set-property fwupd.service MemoryHigh=128M MemoryMax=256M MemorySwapMax=256M
        swapon --show
        systemctl show fwupd.service -p MemoryHigh -p MemoryMax -p MemorySwapMax
        ;;
    django)
        backup
        container_id=$(docker ps -q --filter label=com.docker.swarm.service.name=django_django)
        [[ -n "$container_id" && "$container_id" != *$'\n'* ]]
        running_image=$(docker inspect --format '{{.Image}}' "$container_id")
        tagged_image=$(docker image inspect --format '{{.Id}}' my-django-app:latest)
        if [[ "$running_image" != "$tagged_image" ]]; then
            echo 'The local image tag changed; pin the running image before updating.' >&2
            exit 1
        fi
        uwsgi_help=$(docker exec "$container_id" uwsgi --help)
        for option in --processes --max-requests --reload-on-rss; do
            if [[ "$uwsgi_help" != *"$option "* ]]; then
                echo "The running uWSGI does not support $option." >&2
                exit 1
            fi
        done
        health_cmd='python -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8000/api/\", timeout=5).read(1)"'
        docker exec "$container_id" sh -c "$health_cmd"
        update_service django_django 320M 96M \
            --args 'uwsgi --ini uwsgi.ini --processes 2 --max-requests 1000 --reload-on-rss 128' \
            --update-order start-first \
            --health-cmd "$health_cmd" --health-interval 30s --health-timeout 10s \
            --health-retries 3 --health-start-period 30s --health-start-interval 5s
        ;;
    support)
        backup
        update_service portainer_agent 96M 16M --update-order stop-first
        update_service portainer_portainer 128M 32M --update-order stop-first
        update_service traefik_reverse-proxy 128M 24M --update-order stop-first
        ;;
    status)
        free -m
        swapon --show
        systemctl show fwupd.service -p MemoryCurrent -p MemoryPeak -p MemoryHigh -p MemoryMax -p MemorySwapMax
        docker service ls
        docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}'
        ;;
    *)
        echo 'Usage: oci-memory-guard.sh {host|django|support|status}' >&2
        exit 2
        ;;
esac
