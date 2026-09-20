# 어드민 저장 공간과 로그 이력

## 현재 로그 뷰어: 시간 조회와 무한 스크롤 (2026-09-16)

[운영 로그 화면](http://158.180.67.53:8001/admin/logs/)은 활성 staff이면서 슈퍼유저인 계정으로 접근한다. 아래 2026-09-15 로그 뷰어 설명은 이전 스냅샷 방식의 적용 기록이다.

- 시작·종료 시각은 한국 시간(KST)이다. 기본 조회는 최근 1시간이며 종료를 비우면 조회 시점까지 표시한다. 한 번에 지정할 수 있는 범위는 최대 7일이다. 출처, 문자열, 오류·경고 필터를 함께 사용한다.
- 최신순으로 200줄을 표시하고 로그 영역 아래로 스크롤하면 이전 200줄을 추가한다. 키보드 사용자를 위한 `이전 로그 더 보기` 버튼도 제공한다. 같은 시각의 로그는 ID로 구분하고 조회 시점의 상한을 고정한다. 새 로그는 새로 조회할 때 반영한다.
- 화면에는 최대 1,000줄만 유지한다. 과거 로그를 읽거나 조건을 수정하는 동안 자동 갱신은 일시정지한다. 추가 조회 실패 시 읽던 내용을 유지하며 다시 시도할 수 있다. 조건을 바꾸고 조회하면 목록을 초기화한다.
- 이력 DB는 서버별 최대 **64MiB**, 보관 기간은 최대 7일이며 먼저 도달하는 제한에 따라 오래된 항목을 정리한다. 실제 보관 범위를 화면에 표시한다. **2026-09-16 21:55 KST 기준 약 5시간분**이 보관됐다. 7일 보관을 보장하는 정책은 아니다. 원본 Docker·시스템 로그 보관 정책은 [로그 정리 문서](../log-maintenance/README.md)를 참조한다.
- 수집 시 알려진 민감값을 마스킹한다. 한 항목은 2,100자 이하이며 8KiB를 넘는 원본 메시지는 생략한다. 웹 요청은 로컬의 읽기 전용 SQLite만 조회하며 SSH나 Docker를 실행하지 않는다.

크롤러와 웹 서버에 `history.py`, 갱신된 `logs.py`·`export.py` 및 `geteverything-log-history.service/.timer`를 설치했다. 크롤러 원본 이력은 `/var/lib/geteverything-storage/log-history.sqlite3`, 웹 캐시는 기존 읽기 전용 마운트의 `snapshots/log-history.sqlite3`이다. 전용 SSH 키의 접속 IP·호스트 키 제한은 유지하며 `export.py`는 기존 용량·스냅샷 명령과 정확한 `history <정수 ID>`만 허용한다.

수집과 동기화는 약 1분 간격이다. 각 서비스는 메모리 64MiB, CPU 0.2개, 실행 시간 40초로 제한한다. 원본 명령은 출처당 1MiB·5초, 전송은 페이지당 최대 1,000줄·1MiB, 정기 실행당 최대 2페이지다. SQLite 캐시는 2MiB이며 웹 조회는 0.75초 제한을 둔다. DB 파일 상한 외에 쓰기 중 임시 롤백 저널이 생길 수 있다. 연결 실패 시 이전 캐시를 보존하고 지연을 표시한다. 초기 이력 가져오기는 제한된 별도 작업으로 완료했으며 기존 스냅샷 타이머는 롤백 호환을 위해 유지했다.

배포: **2026-09-16 19:37:51 KST**, `my-django-app:history-20260916`, 이미지 `sha256:f89c9bf0520641a6b3a71ce4648de1103f0703da046806d1fae4630691330003`. 웹 서비스의 자원·환경·네트워크·읽기 전용 마운트를 보존했다. 배포 기록은 웹 서버 `/root/log-history-web-20260916/web-deployment.json`, 수집기 백업은 두 서버의 `/root/log-history-20260916`에 있다. 이전 웹 화면으로 롤백할 때는 다음 명령을 사용한다. 이력 수집까지 중지하려면 크롤러와 웹의 `geteverything-log-history.timer`를 중지·비활성화하고 서비스를 중지한다. 기존 용량 측정·로그 정리 타이머는 유지한다.

```sh
sudo docker service update --no-resolve-image --image my-django-app:before-history-20260916 django_django
sudo docker image tag my-django-app:before-history-20260916 my-django-app:latest
```

검증: Django 24개와 수집기 19개 테스트를 통과했다. 실제 마스킹된 로그와 별도 테스트 계정으로 로컬 Chromium 390×844·768×1024·1440×900 화면을 확인했다. 추가 테스트 데이터 1,601줄로 무한 스크롤·중복 방지·1,000줄 화면 제한·마지막 페이지·시간 경계·필터 변경·요청 취소·키보드·실패와 재시도·로그인 만료·밝은/어두운 테마를 검증했고 JS 실행 오류는 없었다. 브라우저 증빙은 `/private/tmp/storage-preview-20260915/history`에 있다. 운영 사용자로 브라우저 로그인한 검증은 아니다.

운영 이미지에서는 실제 읽기 전용 이력으로 페이지 200 응답, 200줄씩 연속 두 페이지의 중복 없음과 저장 공간 화면을 검사했다. 배포 후 CSS·JS 바이트 해시를 대조했다. **21:55 KST**에 두 이력 타이머의 정상 실행, 3분 이내 수집·동기화, 용량 측정과 로그 정리의 정상 동작을 확인했다. 크롤러·FlareSolverr는 기존 시작 시각을 유지했고 세 관련 컨테이너 모두 실행 중이며 OOM·재시작 횟수는 0이었다. 해당 날짜의 크롤러·웹 커널 OOM 기록도 없었다. 5개 사이트 모두 최근 30분 내 DB 갱신이 있었으며 뽐뿌의 마지막 갱신은 **21:55:07 KST**였다. 소스는 아직 커밋·푸시하지 않았다.

## 저장 공간 측정

[운영 화면](http://158.180.67.53:8001/admin/storage/) — 관리자 홈과 사이드바의 **서버 운영 → 저장 공간**에서 접근한다. 활성 직원 계정으로 로그인해야 하며 읽기 전용 화면이다.

## 측정 항목과 화면

- DB 서버 `168.107.63.171`: `getev` DB 데이터 크기와 PostgreSQL 데이터·WAL·별도 테이블스페이스가 위치한 디스크의 전체·사용·가용 공간을 확인한다. 같은 파일시스템은 한 번만 표시한다.
- 크롤링 서버 `168.107.29.18`: 로그 디스크의 가용 공간, `/home/crawler/logs` 파일 로그, `/var/log` 시스템 로그, Docker 컨테이너 로그의 실제 할당 크기를 확인한다. Docker 로그는 중지된 컨테이너와 회전된 파일도 포함한다.
- 디스크 사용량과 실제 저장 가능한 공간을 구분한다. `f_bavail` 기준 가용 공간에서 시스템 예약 공간은 제외한다. DB 크기를 디스크 전체 크기에서 빼서 남은 공간으로 표시하지 않는다.
- 공간 또는 inode 여유가 10% 이하이면 `용량 주의`, 5% 이하이면 `공간 부족`을 표시한다. 측정 실패는 0으로 표시하지 않고, 연결 실패 시 마지막 값·측정 시각을 보존한다. 180초 이상 지난 값은 `갱신 지연`으로 표시한다.
- 각 서버의 systemd 타이머가 약 1분마다 측정한다. 웹 서버도 약 1분마다 결과를 가져온다. 수집 시점에 따라 화면 반영까지 두 주기의 지연이 생길 수 있다. `새로고침`은 저장된 최신 결과를 다시 읽으며 새 서버 검사를 강제로 실행하지 않는다.
- 화면은 60초마다 자동 갱신하고 숨겨진 탭에서는 쉬도록 했다. 요청 중 중복 갱신을 막고, 오류 시 기존 화면을 유지한다. 로그인 만료 시 자동 갱신을 멈추고 로그인 링크를 표시한다.

## 구성과 운영 제한

```text
DB 서버: 수집 타이머 → report.json ──────┐
                                      ├─ 전용 SSH 읽기 → 웹 서버 snapshots/*.json
크롤러: 수집 타이머 → report.json ───────┘                         │
                                                  어드민 컨테이너의 읽기 전용 마운트
```

수집기는 Python 표준 라이브러리와 서버에 이미 있는 `psql`, `du`, Docker CLI, OpenSSH를 사용한다. 웹 요청에서 SSH나 디렉터리 순회를 수행하지 않고 JSON 파일 두 개만 읽는다. 새 DB 테이블이나 스키마 변경은 없다.

- 공통 실행 파일: `/usr/local/lib/geteverything-storage/collect.py`
- 설정: `/etc/geteverything-storage/config.json` (root, 600)
- 소스 결과: `/var/lib/geteverything-storage/report.json`
- 웹 서버 결과: `/var/lib/geteverything-storage/snapshots/database.json`, `crawler.json`
- 서비스와 타이머: `geteverything-storage.service`, `geteverything-storage.timer`
- 웹 컨테이너: 위 `snapshots` 디렉터리만 같은 경로로 읽기 전용 마운트한다. `STORAGE_METRICS_DIR`로 다른 위치를 지정할 수 있다.
- 웹 서버 전용 키: `/etc/geteverything-storage/id_ed25519` (root만 읽기). 키는 웹 서버 내부에서 생성했으며 앱 이미지나 로컬 PC로 복사하지 않았다.
- 두 소스 서버의 해당 공개키는 `from="158.180.67.53,10.0.0.238",restrict,command="/bin/cat /var/lib/geteverything-storage/report.json"`으로 제한했다. 기존 SSH 키는 유지했다. 웹 서버에서는 사전에 확인한 서버 공개키를 `known_hosts`에 고정해 검증한다.
- CPU 제한 0.1 CPU, 메모리 96MiB, 낮은 실행·IO 우선순위, 서비스 제한 시간 50초를 설정했다. SQL은 읽기 전용이며 5초 제한, SSH는 연결 5초·전체 12초 제한·연결 시도 1회, `du`는 10초 제한이다. 다음 주기에 다시 시도하며 한 실행 안에서 무한 재시도하지 않는다.

## 설치·설정

세 서버에 공통 파일을 설치하고 역할별 설정을 작성한다. 현재 운영 서버에는 설치와 타이머 활성화를 완료했다.

```sh
sudo install -d -m 755 /usr/local/lib/geteverything-storage /var/lib/geteverything-storage /var/lib/geteverything-storage/snapshots
sudo install -d -m 700 /etc/geteverything-storage
sudo install -m 755 ops/storage-monitoring/collect.py /usr/local/lib/geteverything-storage/collect.py
sudo install -m 644 ops/storage-monitoring/geteverything-storage.service /etc/systemd/system/
sudo install -m 644 ops/storage-monitoring/geteverything-storage.timer /etc/systemd/system/
```

DB 서버 설정:

```json
{"source":"database","database_name":"getev","data_directory":"/var/lib/postgresql/16/main","state_directory":"/var/lib/geteverything-storage"}
```

크롤링 서버 설정:

```json
{"source":"crawler","log_directory":"/home/crawler/logs","state_directory":"/var/lib/geteverything-storage"}
```

웹 서버 설정:

```json
{
  "source":"hub",
  "state_directory":"/var/lib/geteverything-storage",
  "identity_file":"/etc/geteverything-storage/id_ed25519",
  "known_hosts_file":"/etc/geteverything-storage/known_hosts",
  "sources":[
    {"source":"database","target":"ubuntu@168.107.63.171"},
    {"source":"crawler","target":"ubuntu@168.107.29.18"}
  ]
}
```

새로 설치할 때는 웹 서버에서 전용 키를 생성하고 위의 고정 명령·접속 IP 제한으로 공개키를 소스 서버에 추가한다. 이미 신뢰하는 SSH 연결로 서버 공개키를 확인해 `known_hosts`에 기록한다. 개인키와 DB 비밀번호를 앱에 전달하지 않는다. 서버 주소가 바뀌면 설정과 키의 접속 IP 제한을 함께 갱신한다.

```sh
sudo systemctl daemon-reload
sudo systemctl start geteverything-storage.service
sudo systemctl enable --now geteverything-storage.timer
sudo journalctl -u geteverything-storage.service --since '-10 minutes' --no-pager
```

웹 서버의 기존 `/home/docker/django/docker-compose.yml`에는 읽기 전용 마운트를 추가했다. 저장소의 `docker-compose.web.yml`도 같은 마운트를 정의하고 GitHub 배포 워크플로에서 함께 사용한다. 새 서버에서는 수집기를 먼저 설치해야 한다.

## 2026-09-15 적용·검증

**01:05:45 KST**에 `django_django` 서비스 배포를 완료했다. 이미지 `my-django-app:storage-20260915`, ID `sha256:3dad0941a97df15ac536aff0ee645bc8cbd287e7e0125819027844b71274aea1`. 실행 중이던 웹 이미지에 모니터링 모듈과 필요한 설정만 추가했다. 기존 DB 환경값·자원 제한·네트워크·서비스 설정을 대조했고, 읽기 전용 마운트 외에는 보존됐다. 크롤러·FlareSolverr·DB는 재시작하지 않았다.

01:07 KST 확인값:

| 항목 | 값 |
| --- | ---: |
| DB 디스크 전체 / 가용 공간 | 95.8GiB / 89.4GiB |
| `getev` DB 데이터 | 약 649MiB |
| 크롤러 로그 디스크 전체 / 가용 공간 | 44.1GiB / 14.7GiB |
| 크롤러 파일 로그 | 36KiB |
| 시스템 로그 | 2.3GiB |
| 컨테이너 로그, 중지·회전 파일 포함 | 10.5GiB |

DB와 크롤러 수집기 마지막 실행은 모두 정상 종료했다. 해당 실행의 CPU 시간은 각각 약 0.10초였고, 서버에서 자동으로 측정 시각이 갱신되는 것을 확인했다. 이는 마지막 실행의 관측값이다.

기존 크롤러와 FlareSolverr는 원래 시작 시각을 유지하며 OOM·자체 재시작이 없었다. 다섯 사이트의 DB 갱신을 확인했고, 뽐뿌는 **01:05:59 KST**에도 갱신됐다.

검증 범위:

- Django 테스트 12개와 수집기 테스트 6개 통과. 인증·잘못된 데이터·예약 공간·디스크와 inode 경고·지연·부분 실패·연결 실패 시 값 보존·HTML 이스케이프를 확인했다.
- 실제 서버에서 복사한 용량 데이터와 분리된 SQLite 테스트 계정으로 Chromium에서 **390×844, 768×1024, 1440×900**을 확인했다. 가로 넘침 없이 표시됐고, 로그인→메뉴→화면, 키보드 새로고침과 초점 유지, 처리 중 비활성화, 연결 실패와 재시도, 빈 값·지연·긴 경로·로그인 만료를 검사했다. 밝은·어두운 테마를 시각적으로 확인했다.
- UI Design Workflow에 따라 기존 Django 디자인을 유지했고 Impeccable의 최종 다듬기와 Web Interface Guidelines를 적용했다. Impeccable 검사 결과는 빈 목록이었다. 브라우저 JS 실행 오류는 없었다. 콘솔의 두 오류는 기존 기본 favicon의 404와 의도적으로 끊은 네트워크 시험이었다.
- 운영 이미지에서도 실제 읽기 전용 마운트로 화면 렌더링 200과 두 서버 정상 상태를 확인했다. 운영 HTTP에서 CSS·JS의 바이트 해시를 배포 소스와 대조했다. 외부 `/admin/storage/`의 비로그인 요청은 로그인 페이지로 302 이동하고 `no-store`를 반환했다. 운영 사용자로 브라우저 로그인을 수행한 것은 아니다.
- `git diff --check` 통과. 서버 증빙은 웹 서버 `/root/storage-monitoring-20260915/web-deployment.json`, `final-verification.json`에 보관했다. 브라우저 증빙은 로컬 `/private/tmp/storage-preview-20260915`에 있다.

## 롤백

이전 웹 이미지는 `my-django-app:before-storage-20260915`이며 ID는 `sha256:57d63eba1f6d6c6b4985560e08c5d25c63af27802e7eb5a11f114103dd9c2c1c`다. 웹 서버 `/root/storage-monitoring-20260915`에 원래 서비스 JSON·설정·Compose 파일을 보관했다. 각 소스 서버의 같은 디렉터리에는 키 추가 전 `authorized_keys.before`가 있다.

```sh
sudo docker service update --no-resolve-image --image my-django-app:before-storage-20260915 django_django
sudo docker image tag my-django-app:before-storage-20260915 my-django-app:latest
```

측정까지 중지하려면 세 서버의 `geteverything-storage.timer`를 비활성화하고 서비스를 중지한다. 전용 키를 제거할 때는 `geteverything-storage-monitor-20260915` 항목만 제거하며 이후 추가된 다른 SSH 키를 덮어쓰지 않는다.

운영 서버에는 적용했으며 로컬 소스·배포 워크플로는 아직 커밋·푸시하지 않았다. 다음 GitHub 배포 전에 이 변경을 반영해야 한다.
## 이전 로그 뷰어 적용 기록 (2026-09-15)

운영 주소: **http://158.180.67.53:8001/admin/logs/**. 관리자 홈 → 서버 운영 → 크롤러 로그로도 이동한다. 활성 staff이면서 슈퍼유저인 계정만 페이지와 데이터 API에 접근한다. 일반 staff의 저장 공간 접근은 유지된다.

- 출처: 크롤러, FlareSolverr, 뽐뿌 VPN 관리, 로그 자동 정리. 최근 1시간에서 최대 300줄을 수집한다. 자동 정리는 최근 24시간이다.
- 문자열 검색(최대 120자), 오류·경고 필터, 100/300줄 선택, 수동 조회와 60초 자동 갱신 일시정지를 제공한다. 전체 과거 로그 검색은 아니다.
- 출처당 최대 64KiB, 명령당 3초, 긴 줄 2,048자, 전송 JSON 최대 1MiB로 제한한다. 끝나지 않는 명령과 상속된 파이프도 프로세스 그룹을 종료·회수한다. 원본 전체 읽기나 follow 모드는 없다.
- 알려진 비밀번호·토큰·인증 헤더·쿠키·URL 사용자 정보·개인키 형식을 원천 수집 시 마스킹하고 제어 문자를 제거한다. 비정형의 모든 민감 내용을 완전히 식별하는 기능은 아니므로 슈퍼유저에게만 제공한다. HTML은 항상 이스케이프한다.
- 웹 요청은 읽기 전용 파일만 읽는다. 별도 `geteverything-log-snapshot.timer`가 크롤러에서 수집하고 기존 storage hub가 전용 SSH 키로 `logs` 명령을 요청한다. 수집기는 CPU 10%, 메모리 64MiB, 25초 제한이며 기존 크롤링 큐와 독립적이다.
- 수집 실패 시 마지막 내용과 실제 수집 시각을 유지한다. 3분 지연·권한 만료·연결 실패·빈 로그·검색 결과 없음·출력 생략을 구분해 표시한다. 자동 갱신은 페이지가 보일 때만 수행하며 로그에 키보드 초점이 있거나 텍스트를 선택 중이면 건너뛴다.

크롤러에는 `logs.py`, `export.py`를 `/usr/local/lib/geteverything-storage/`에 배치하고 `geteverything-log-snapshot.service/.timer`를 설치한다. 전용 키의 기존 `from=…`, `restrict` 조건은 유지하고 강제 명령만 `/usr/bin/python3 /usr/local/lib/geteverything-storage/export.py`로 바꾼다. 기존 빈 SSH 명령은 `report.json`, 정확한 `logs`만 `logs.json`을 반환하며 다른 명령은 거부한다. 웹 서버에도 `logs.py`와 갱신된 `collect.py`를 배치하고 root 전용 설정에 `collect_logs: true`를 추가한다. DB 서버와 전용 개인키는 변경하지 않았다.

원본 마스킹 스냅샷은 크롤러의 `/var/lib/geteverything-storage/logs.json`, 웹 마운트 파일은 `snapshots/crawler-logs.json`이다. 기존 읽기 전용 마운트와 방화벽을 그대로 사용한다. 로그 보관 정책과 수동 정리 스크립트는 [로그 정리 문서](../log-maintenance/README.md)를 참조한다.

검증: Django 18개 + 수집기 12개 테스트 통과. 실제 마스킹된 서버 로그와 별도 SQLite 계정으로 Chromium의 390×844, 768×1024, 1440×900 화면을 확인하고 출처·검색·심각도·초점·갱신 중·실패와 재시도·자동 갱신 중지/재개·로그인 만료를 검사했다. 경계 상태에는 명시적인 테스트 데이터를 사용했다. 브라우저 JS 실행 오류는 없었다. Impeccable 최종 검사 결과는 `[]`였고 Web Interface Guidelines의 접근성·상태·테마·반응형 기준을 검토했다. 로그는 300줄로 제한되어 있으며 가변 줄바꿈과 줄 번호를 보존하기 위해 CSS 가상화는 사용하지 않는다.

브라우저 검증은 로컬의 실제 렌더링이며 운영 사용자로 로그인한 것은 아니다. 운영 이미지에서 실제 스냅샷 마운트로 두 용량 화면과 로그 300줄 렌더링을 검증하고, 배포 후 CSS·JS 바이트 해시를 확인했다.

웹 배포: **2026-09-15 03:39:06 KST**, `my-django-app:logs-20260915`, 이미지 `sha256:379bb13a0a80fb91ff777ee0082b74af5e24629ca6736f852af1f882103dceb0`. 서비스 리소스·환경·네트워크·마운트를 보존했다. `/root/log-viewer-web-20260915`에 배포 전 서비스 설정과 검증 기록이 있다. 롤백은 `my-django-app:before-logs-20260915` 이미지로 `django_django` 서비스를 업데이트하고 `latest` 태그도 복원한다. 소스·워크플로는 아직 커밋·푸시하지 않았다.
