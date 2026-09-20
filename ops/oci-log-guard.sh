#!/usr/bin/env bash
# Run on instance-20251213-1303 with sudo; see oci-memory-guard.md.
set -euo pipefail
umask 077

phase=${1:-status}
if [[ $(hostname) != instance-20251213-1303 || $EUID -ne 0 ]]; then
    echo 'This script requires root on instance-20251213-1303.' >&2
    exit 1
fi

status() {
    journalctl --disk-usage
    systemd-analyze cat-config systemd/journald.conf | awk '/^[[:space:]]*[^#;[:space:]]/ {print}'
    systemctl list-timers --all --no-pager logrotate.timer systemd-tmpfiles-clean.timer
    df -h /
    swapon --show
}

case "$phase" in
    apply)
        backup_dir=$(mktemp -d /var/backups/geteverything-logs.XXXXXXXX)
        echo "Backup: $backup_dir"
        journalctl --list-boots --no-pager > "$backup_dir/boots.txt"
        journalctl --disk-usage > "$backup_dir/journal-usage-before.txt"
        if awk '$1 == -1 { found=1 } END { exit !found }' "$backup_dir/boots.txt"; then
            journalctl -b -1 -k --no-pager -o short-iso | gzip -1 > "$backup_dir/previous-boot-kernel.log.gz"
            journalctl -b -1 -u systemd-networkd --no-pager -o short-iso | gzip -1 > "$backup_dir/previous-boot-network.log.gz"
        fi
        journalctl -b -k --no-pager -o short-iso | gzip -1 > "$backup_dir/current-boot-kernel.log.gz"

        if ! command -v logrotate >/dev/null 2>&1; then
            timeout 180s env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l \
                apt-get -y --no-install-recommends --no-upgrade \
                -o Dpkg::Lock::Timeout=30 -o Acquire::Retries=2 \
                -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 \
                install logrotate
        fi

        journal_config=/etc/systemd/journald.conf.d/90-geteverything.conf
        timer_config=/etc/systemd/system/logrotate.timer.d/90-geteverything.conf
        for config in "$journal_config" "$timer_config" /etc/logrotate.d/btmp; do
            if [[ -e "$config" ]]; then
                cp -a --parents "$config" "$backup_dir/"
            else
                printf '%s\n' "$config" >> "$backup_dir/previously-absent.txt"
            fi
        done
        install -d -m 755 /etc/systemd/journald.conf.d /etc/systemd/system/logrotate.timer.d
        cat > "$journal_config" <<'EOF'
[Journal]
SystemMaxUse=200M
SystemKeepFree=1G
SystemMaxFileSize=16M
RuntimeMaxUse=16M
RuntimeMaxFileSize=4M
MaxFileSec=1day
MaxRetentionSec=14day
Compress=yes
EOF
        cat > /etc/logrotate.d/btmp <<'EOF'
/var/log/btmp {
    su root root
    missingok
    notifempty
    weekly
    maxsize 10M
    rotate 4
    compress
    compressoptions -1
    create
}
EOF
        cat > "$timer_config" <<'EOF'
[Timer]
OnCalendar=
OnCalendar=hourly
AccuracySec=1min
RandomizedDelaySec=5min
Persistent=true
EOF
        chmod 644 "$journal_config" "$timer_config" /etc/logrotate.d/btmp
        logrotate --debug /etc/logrotate.conf > "$backup_dir/logrotate-check.log" 2>&1 || {
            cat "$backup_dir/logrotate-check.log" >&2
            exit 1
        }
        systemctl daemon-reload
        systemd-analyze verify logrotate.timer logrotate.service
        timeout 30s systemctl restart systemd-journald.service
        journalctl --rotate --vacuum-size=200M --vacuum-time=14d
        systemctl enable logrotate.timer
        systemctl restart logrotate.timer
        timeout 60s systemctl start logrotate.service
        systemctl is-active systemd-journald.service logrotate.timer
        systemctl show logrotate.service -p Result -p ExecMainStatus
        status
        ;;
    status)
        status
        ;;
    *)
        echo 'Usage: oci-log-guard.sh {apply|status}' >&2
        exit 2
        ;;
esac
