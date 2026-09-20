# OCI 메모리 부족 분석 및 운영 설정

대상은 `158.180.67.53` / `instance-20251213-1303`이며 Ubuntu 24.04,
`VM.Standard.E2.1.Micro`, 실제 사용 가능 RAM 약 954MiB 구성이다.
2026-09-13 일반 재부팅으로 SSH와 핫딜 API를 복구한 뒤 메모리 보호 설정을 적용했다.

## OOM 분석

커널 기록상 OOM 시각은 **2026-05-19 08:10:21~34 UTC**이다.
`global_oom`, `CONSTRAINT_NONE`, `Total swap = 0kB`가 기록되어 있다.
컨테이너별 상한에 걸린 사건이 아니라 호스트 전체의 메모리 부족이다.

당시 익명 메모리가 약 **710MiB**였고, 스왑이 없어 이를 디스크로 옮길 수 없었다.
DMA32 영역의 여유 메모리도 커널의 최소 확보 기준 아래로 내려갔다.
uWSGI 워커 4개와 관리/HTTP 프로세스, Docker, `fwupd`, `apt-get` 등
정기 갱신 작업이 같은 1GiB 메모리를 사용하고 있었다.

| 당시 프로세스 | RSS |
| --- | ---: |
| uWSGI 6개 프로세스 합계 | 약 323MiB |
| fwupd | 약 174MiB |
| dockerd | 약 83MiB |
| apt-get | 약 40MiB |
| containerd | 약 28MiB |

RSS 합계에는 공유 메모리 중복이 포함될 수 있으므로 표를 합산해 실제 사용량으로 해석하면 안 된다.
메모리 할당 중 OOM을 호출한 `agent`는 약 15MiB였고, 커널이 종료 대상으로 선택한 것은
`fwupd`였다. 호출한 프로세스나 종료된 프로세스 하나만을 원인으로 단정할 수 없다.
복구 후에도 `fwupd`의 정상 작업 중 메모리 최고치가 약 213MiB로 관측됐다.
현재 증거는 작은 RAM, 스왑 부재, 동시 실행 작업의 합산 부담을 가리키며 특정 코드의
메모리 누수가 입증된 것은 아니다.

`ens3` DHCP 주소 설정 실패는 2026-05-18 21:22:56 UTC에 먼저 기록됐다.
따라서 OOM이 네트워크 장애를 직접 일으켰다고 확정할 수 없다.
재부팅 후 디스크 사용률은 22%, 여유 공간은 약 35GiB였다.
장애 직전 디스크 사용량 측정값은 확보하지 못했으며, 확인한 로그에는 용량 고갈 증거가 없었다.

## 적용 설정

| 대상 | 설정 |
| --- | --- |
| 호스트 | `/swapfile` 2GiB, 모드 0600, `/etc/fstab` 등록 |
| fwupd | `MemoryHigh=128M`, `MemoryMax=256M`, `MemorySwapMax=256M` |
| Django | 워커 2개, `max-requests=1000`, `reload-on-rss=128` |
| Django 컨테이너 | 메모리 상한 320MiB, 예약 96MiB, HTTP 헬스체크 |
| Portainer agent | 메모리 상한 96MiB, 예약 16MiB |
| Portainer | 메모리 상한 128MiB, 예약 32MiB |
| Traefik | 메모리 상한 128MiB, 예약 24MiB |
| 컨테이너 로그 | 컨테이너당 `json-file`, 10MiB × 3개 |
| 관측 | 1분마다 가용 메모리, 스왑 사용량, 메모리 PSI 기록 |

`vm.swappiness`는 기존 값 60을 유지한다. 스왑은 일시적인 부담을 흡수하는 장치이며
RAM을 대체하지 않는다. 가용 메모리 150MiB 미만 또는 스왑 75% 초과 시
`geteverything-memory` 태그로 **서버 저널에 경고**를 기록하고 상위 프로세스와
컨테이너 cgroup 상태를 함께 남긴다. 외부 이메일/메신저 알림은 설정하지 않았다.

운영 이미지의 uWSGI 2.0.28에서 지원하는 옵션을 사용했다.
이미지를 다시 빌드하거나 작업 중인 크롤러 리팩토링을 배포하지 않았다.
설정 갱신 전 실행 이미지와 로컬 이미지 태그의 일치 여부를 확인한다.

## 점검과 재적용

저장소 루트에서 `OCI_KEY`를 해당 서버의 로컬 SSH 개인키 경로로 지정한다.

```sh
ssh -i "$OCI_KEY" ubuntu@158.180.67.53 'sudo bash -s -- status' < ops/oci-memory-guard.sh
```

호스트 설정은 fstab과 systemd 설정에, 컨테이너 설정은 Docker Swarm 서비스에 저장되어
서버 재부팅 후에도 유지된다. **Portainer나 별도 stack 원본으로 재배포하면 서비스 설정을
덮어쓸 수 있다.** 이 저장소에는 해당 stack 원본이 없으므로 원본에 같은 설정을 반영하거나
재배포 후 아래 단계를 실행해야 한다. 버전 관리되는 `gadmin/uwsgi.ini.template`을 수정했고,
Git에서 제외된 로컬 생성 파일 `gadmin/uwsgi.ini`에도 동일한 워커 설정을 반영했다.

```sh
ssh -i "$OCI_KEY" ubuntu@158.180.67.53 'sudo bash -s -- host' < ops/oci-memory-guard.sh
ssh -i "$OCI_KEY" ubuntu@158.180.67.53 'sudo bash -s -- django' < ops/oci-memory-guard.sh
ssh -i "$OCI_KEY" ubuntu@158.180.67.53 'sudo bash -s -- support' < ops/oci-memory-guard.sh
```

서비스 갱신은 순차 진행하며, 실패 시 Docker의 자동 롤백을 사용한다.
스크립트는 롤백을 성공한 적용으로 간주하지 않고 실패를 반환한다.
명령이 시간 제한으로 종료되면 재실행 전에 `docker service ps`와 `UpdateStatus`를 확인한다.

모니터의 운영 설치 경로는 `/usr/local/sbin/geteverything-memory-watch`와
`/etc/systemd/system/geteverything-memory-watch.{service,timer}`이다.
대응하는 원본 파일은 이 디렉터리에 있다.

```sh
sudo journalctl -t geteverything-memory --since '1 hour ago'
sudo systemctl list-timers geteverything-memory-watch.timer
sudo systemctl show fwupd.service -p MemoryHigh -p MemoryMax -p MemorySwapMax
sudo docker service inspect django_django --format '{{json .Spec.TaskTemplate.Resources}}'
curl --fail --max-time 15 http://158.180.67.53:8001/api/deals/
```

가용 메모리 부족 경고나 스왑 사용량 증가가 반복되면 기록에서 원인을 좁히고 RAM 증설을
검토한다. 제한값은 실제 관측을 바탕으로 조정해야 하며 모든 부하에서 OOM이 사라진다는
보장은 아니다.

## 로그 자동 정리

스왑 파일은 2GiB로 고정되어 있으며 커널이 내부 페이지를 관리한다. 스왑 사용량이
남아 있다는 이유로 `swapoff`/`swapon`을 주기적으로 실행하지 않는다. 스왑 해제는
메모리에 다시 부담을 주며, 로그 삭제는 디스크 여유를 확보하는 작업이므로 OOM
방지와 구분해야 한다. `drop_caches`나 Docker 볼륨 일괄 삭제도 자동 정리에 포함하지 않는다.

추가 점검에서 시스템 저널은 약 549MiB, `/var/log/btmp`는 약 125MiB였다.
Ubuntu Minimal에 `/etc/logrotate.d` 규칙은 있었지만 `logrotate` 실행 프로그램과
타이머는 설치되지 않아 해당 로그들이 자동 회전하지 않았다.

`oci-log-guard.sh`는 별도 상주 프로세스 대신 journald와 logrotate의 기본 기능을 사용한다.

| 대상 | 정리 기준 |
| --- | --- |
| 시스템 저널 | 총 200MiB, 보관 14일, 파일당 16MiB/1일 회전, 디스크 1GiB 여유 기준 |
| 임시 메모리 저널 | 총 16MiB, 파일당 4MiB |
| 일반 OS 로그 | logrotate를 매시간 실행해 각 패키지의 회전 규칙 확인 |
| 실패한 로그인 기록 `btmp` | 매주 또는 10MiB 초과 시 회전, 이전 파일 4개 압축 보관 |
| Docker stdout/stderr | 기존 컨테이너별 10MiB × 3개 자동 회전 유지 |

logrotate의 매시간 실행에는 최대 약 6분의 지연이 있다. 파일은 점검 사이에 설정 크기를
넘을 수 있다. 저널도 활성 파일을 바로 삭제하지 않으므로 200MiB는 파일 회전 단위로
관리하는 기준이며, 14일치 로그가 모두 보장되는 것은 아니다. 다른 OS 로그는 기존
패키지별 보관 주기를 유지한다. Oracle agent 자체 로그 회전은 변경하지 않는다.

```sh
ssh -i "$OCI_KEY" ubuntu@158.180.67.53 'sudo bash -s -- apply' < ops/oci-log-guard.sh
ssh -i "$OCI_KEY" ubuntu@158.180.67.53 'sudo bash -s -- status' < ops/oci-log-guard.sh
```

설정 변경 전 `/var/backups/geteverything-logs.*`에 기존 설정과 이전 부팅의
커널·네트워크 기록, 현재 커널 기록을 root 전용 권한으로 보관한다. 보관 기간을 넘긴
전체 저널은 정리되므로 장애 기록 보관이 필요하면 정리 전에 별도로 내보내야 한다.
스크립트는 logrotate가 없을 때 해당 패키지와 필수 의존성만 설치한다.
Docker나 웹 서비스를 재시작하지 않으며, Docker 로그 파일을 직접 삭제하지 않는다.

2026-09-13 운영 적용에서 logrotate와 필수 라이브러리 libpopt0를 설치했다.
설정 검사와 최초 회전 실행은 성공했고, 매시간 타이머의 활성화와 다음 실행 예약을 확인했다.
저널 사용량은 약 549MiB에서 16MiB로, 기존 125MiB의 `btmp`는 5.1MiB의
압축 보관 파일로 줄었다. 새 `btmp`는 기존 권한 `0660 root:utmp`를 유지했다.
디스크 사용률은 27%에서 25%로 줄었으며 외부 API는 HTTP 200을 반환했다.
서비스 4개는 모두 `1/1`, Django는 `healthy`, 컨테이너별 `oom_kill`은 0이었다.
원본 설정과 장애 기록 백업은 `/var/backups/geteverything-logs.SopQoiho`에 있다.
압축 백업 무결성과 이전 커널 기록의 OOM 메시지 보존도 확인했다.

설정을 되돌릴 때는 백업의 `etc/` 아래 파일을 원래 경로로 복원하고,
`previously-absent.txt`에 있는 이번 추가 설정 파일만 제거한다. 그 후
`systemctl daemon-reload`, `systemctl restart systemd-journald logrotate.timer`를 실행한다.
정리된 과거 로그는 설정 복원만으로 복구되지 않는다.

동작 기준은 [journald 설정 문서](https://man7.org/linux/man-pages/man5/journald.conf.5.html),
[logrotate 문서](https://man7.org/linux/man-pages/man8/logrotate.8.html),
[Docker 로그 회전 문서](https://docs.docker.com/engine/logging/drivers/json-file/)를 참고한다.

## 적용 후 검증

2026-09-13 검증에서 서비스 4개가 모두 `1/1`로 실행 중이었다.
실제 cgroup의 메모리 상한이 표의 설정값과 일치했고 모든 실행 중 컨테이너의
`oom_kill` 값은 0이었다. Django는 워커 2개와 `healthy` 상태를 확인했다.
사용 이미지는 변경 전과 동일한 `sha256:57d63eba1f6d6c6b4985560e08c5d25c63af27802e7eb5a11f114103dd9c2c1c`였다.

외부 `/api/deals/` 동시 조회 2건은 각각 HTTP 200, JSON 결과 30개를 반환했으며
응답 시간은 약 0.55초와 0.72초였다. 최종 관측값은 가용 RAM 약 462MiB,
스왑 사용량 약 202MiB, 디스크 여유 약 33GiB였다.
현재 부팅에서 추가 커널 OOM과 실패한 systemd 서비스는 없었다.
모니터가 실제로 여러 차례 실행되어 메모리와 PSI를 기록한 것도 확인했다.

스크립트 구문 검사와 systemd 유닛 검증을 통과했다. fstab 검사는 문법 오류 0건이었고,
스왑 파일이 일반 파일이라는 경고 1건이 있었으나 `swapon --show`에서 정상 활성화를 확인했다.
설정 적용 후 서버 전체를 다시 재부팅하거나 운영 서버에서 메모리를 강제로 소진하는
부하 실험은 수행하지 않았다.

## 되돌리기

변경 전 파일과 서비스 설정은 서버의 `/var/backups/geteverything-oom.*`에
root 전용 권한으로 저장된다. 백업에는 기존 서비스 환경변수가 포함될 수 있어 공개하면 안 된다.
호스트 최초 백업은 `geteverything-oom.XwHQPfIq`, Django 적용 직전 백업은
`geteverything-oom.qFE9xkO7`이다.
관리용 컨테이너의 최초 변경 전 백업은 `geteverything-oom.GnfjdP6e`이다.

방금 적용한 서비스 설정을 되돌릴 때는 해당 서비스에 대해
`sudo docker service update --rollback SERVICE`를 사용한다.
그 뒤 다른 변경이 있었다면 현재 버전과 백업을 비교해 복원해야 한다.

fwupd 제한의 기존 값은 모두 `infinity`였다. 제한 해제는 다음 명령으로 가능하다.

```sh
sudo systemctl set-property fwupd.service MemoryHigh=infinity MemoryMax=infinity MemorySwapMax=infinity
sudo systemctl disable --now geteverything-memory-watch.timer
```

스왑은 메모리가 충분히 확보된 때에만 `swapoff /swapfile`로 해제한다.
해제가 성공한 뒤 해당 fstab 항목과 파일을 제거한다. 메모리 부족 상태에서 강제로
스왑을 없애면 다시 OOM을 일으킬 수 있으므로 복구 스크립트는 이를 자동 수행하지 않는다.

관련 동작은 [Docker 메모리 제한 문서](https://docs.docker.com/engine/containers/resource_constraints/),
[uWSGI 옵션 문서](https://uwsgi-docs.readthedocs.io/en/latest/Options.html#reload-on-rss),
[Linux VM 문서](https://www.kernel.org/doc/html/latest/admin-guide/sysctl/vm.html#swappiness)를 참고한다.
