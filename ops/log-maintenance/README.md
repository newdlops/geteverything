# 크롤링 서버 로그 보관

대상은 `168.107.29.18` (`instance-20251207-1802`)이다. 로그 파일 증가로 인한 디스크 고갈을 제한한다. 프로세스 자체의 메모리 누수·OOM은 별도로 진단해야 한다. 이번 작업 동안 커널의 새 OOM 기록은 없었다.

## 운영 정책

| 대상 | 정책 |
| --- | --- |
| 실행 중 크롤러·FlareSolverr | 기존 Docker `local`, 파일당 20MiB × 5 유지 |
| 뽐뿌 VPN 컨테이너 | 기존 Docker `local`, 2MiB × 3 유지 |
| journald | 디스크 200MiB, 메모리 로그 16MiB, 14일, 여유 공간 1GiB 기준 |
| 크롤러 `*.log` (로그 디렉터리와 바로 아래 하위 디렉터리) | 5분마다 검사, 일별 또는 20MiB 초과 시 회전, 회전본 5개, 14일, 압축 |
| syslog·auth 등 기존 rsyslog 규칙 | 시간마다 검사, 일별 또는 20MiB 초과 시 회전, 기존 reopen 훅 유지 |
| btmp | 시간마다 검사, 주별 또는 10MiB 초과 시 회전, 압축본 4개 |

파일 로그는 검사 사이에 기준을 초과할 수 있고, 14일 만료본은 해당 파일이 회전할 때 정리된다. `copytruncate`는 파일을 다시 여는 기능이 없는 크롤러용이며 복사·절단 사이의 극히 짧은 구간에 일부 로그가 유실될 수 있다. journald 속도 제한은 폭주 시 일부 메시지를 생략한다. Docker가 관리하는 활성 로그는 직접 절단·삭제하지 않는다. [Docker 로그 관리 문서](https://docs.docker.com/engine/logging/drivers/local/)

`geteverything-log-maintenance.timer`가 약 5분마다 `maintain.py --apply`를 실행한다. 정리 서비스는 메모리 64MiB, CPU 10%, 실행 시간 90초로 제한하고 `flock`으로 중복 실행을 막는다. DB, 컨테이너 볼륨, 임의 파일을 삭제하거나 실행 중 컨테이너를 재시작하지 않는다.

## 수동 확인·실행

서버에서 실행한다. 기본 모드는 실제 삭제 없는 점검이다.

```sh
sudo python3 /usr/local/lib/geteverything-log-maintenance/maintain.py
sudo systemctl start geteverything-log-maintenance.service
sudo journalctl -u geteverything-log-maintenance.service -n 20 --no-pager
sudo systemctl list-timers geteverything-log-maintenance.timer
```

설치 경로는 다음과 같다. 서버에 파일을 배치한 뒤 `logrotate --debug`로 검증하고 `systemctl daemon-reload` 및 타이머 활성화를 수행한다. 기존 설정은 먼저 보관한다.

| 소스 | 서버 위치 |
| --- | --- |
| `maintain.py` | `/usr/local/lib/geteverything-log-maintenance/maintain.py` |
| `logrotate.conf` | `/etc/geteverything-log-maintenance/logrotate.conf` |
| `journald.conf` | `/etc/systemd/journald.conf.d/90-geteverything.conf` |
| `geteverything-log-maintenance.*` | `/etc/systemd/system/` |

상태·잠금 디렉터리 `/var/lib/geteverything-log-maintenance`는 root 소유 0700이다. journald 설정 반영에는 `systemd-journald`만 재시작한 뒤 `journalctl --rotate`를 실행한다. 기존 logrotate 타이머의 `OnCalendar`를 `hourly`로 덮어쓰고 rsyslog·btmp 규칙에 위 크기 제한을 넣었다. 원래 소유자·권한·reopen 훅은 유지했다.

## 2026-09-15 정리 결과

- 5월부터 중지된 `crawlers-bot-before-recovery-20260913`의 **10.43GiB** 로그를 **1.66GiB** gzip으로 보관했다. 스트리밍 압축 후 전체를 다시 읽어 SHA-256과 원본 크기를 검증했다.
- 원본 해시: `5b13eae401ded9b77e0b8870dbf2c35e807a21e5d4c513ac5b914c0a53df556d`.
- 보호된 보관 위치: `/var/backups/geteverything-logs/legacy-20260915`. 압축 로그, 원래 Docker 설정, 재생성 설정, 결과 JSON을 보관한다. 이 일회성 복구 자료는 자동 정리 대상이 아니다.
- Docker commit으로 파일시스템 변경을 보존하고, 동일 이름·설정·바인드 마운트와 회전 제한을 가진 **중지된** 복구 컨테이너를 다시 만들었다. 이후 Docker API로 예전 중지 컨테이너만 제거했다. `--force`, `--volumes`, 전역 prune은 사용하지 않았다.
- 복구 이미지 `crawler-rollback:before-recovery-20260915`: `sha256:7c84639ecd433452e74d979e60da51808fd143d794a00e020494be9d3adc6865`. 바인드 마운트 데이터는 이미지에 포함되지 않으며 기존 `/home/crawler/logs`를 그대로 사용한다.
- 남은 디스크 공간 **약 14.7GiB → 25.6GiB**. 03:58 KST 측정에서 시스템 로그 약 220MiB, 컨테이너 로그 약 45.5MiB였다.
- 크롤러·FlareSolverr·VPN의 기존 시작 시각, 재시작 0회, OOM 없음이 유지됐다. 다섯 사이트가 최근 30분 내 DB를 갱신했고 뽐뿌도 **03:53:34 KST**에 갱신됐다.
- 마지막 정리 CPU 시간 0.074초, 로그 스냅샷 CPU 시간 0.162초였다. 실제 메모리 최고 사용량은 systemd가 제공하지 않아 측정했다고 주장하지 않는다.

`archive_legacy.py`는 위 정확한 예전 컨테이너 ID만 허용하는 일회성 스크립트다. 기본은 점검이며 `--apply`에서만 변경한다. 이미 정리된 서버에서는 ID가 달라 재실행을 거부한다. 서버 `/root/log-maintenance-20260915`에 원래 설정·커널 로그 일부·최종 검증 결과가 있다.

## 정리 정책 되돌리기

`geteverything-log-maintenance.timer`를 비활성화하고, `/root/log-maintenance-20260915`의 `.before` 파일로 변경한 rsyslog·btmp 설정을 복원한다. 이번에 새로 만든 journald·logrotate 타이머 drop-in을 제거한 뒤 daemon-reload 및 해당 서비스·타이머를 재시작한다. 이미 회전·정리된 시스템 로그는 복원되지 않는다. 예전 Docker 로그는 위 압축본에서 열람할 수 있다.
