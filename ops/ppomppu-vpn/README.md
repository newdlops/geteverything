# 뽐뿌 서버 전용 무료 VPN 프록시

Oracle 크롤링 서버 `168.107.29.18`에서 VPN Gate의 공개 중계 서버를 자동 교체한다. PC나 SSH 터널을 계속 켜 둘 필요가 없다. 유료 서비스·별도 클라우드 인스턴스는 사용하지 않는다.

최신 검증: **2026-09-14 23:41과 2026-09-15 00:00 KST에 정규 뽐뿌 수집이 두 차례 연속 정상 종료됐다. 각 주기에서 DB 100건·101건 저장·갱신을 확인했다.** 목록 갱신·순환과 압축 요청 검사를 적용한 결과다. 건수에는 기존 게시글의 재갱신이 포함된다.

무료 VPN의 접근 성공과 가동 시간을 보장하는 구성은 아니다. 쓸 수 있는 경로가 없으면 뽐뿌 수집은 실패로 남고, 정해진 대기 시간 후 다른 경로를 확인한다. 다른 네 사이트는 기존 네트워크로 계속 수집한다.

## 구성

```text
crawlers-bot (host network)
  ├─ 뽐뿌 목록·상세 HTTPS → 127.0.0.1:18888
  │                         → Tinyproxy → 격리된 OpenVPN → 뽐뿌
  └─ 다른 사이트·DB → 기존 서버 네트워크
```

- `ppomppu-vpn` 컨테이너: 0.15 CPU, 메모리 128MiB, PID 64개, 읽기 전용 루트, `/tmp` tmpfs 32MiB, Docker 로그 2MiB × 3개.
- HTTP 프록시는 호스트의 `127.0.0.1:18888`에만 공개한다. Tinyproxy는 Docker 게이트웨이·로컬 접속과 `www.ppomppu.co.kr`, `m.ppomppu.co.kr`의 HTTPS CONNECT 443만 허용한다.
- 방화벽은 VPN 컨테이너 내부에만 적용한다. 새 웹 연결이 일반 `eth0` 출구를 사용하지 못하도록 제한한다. 서버 기본 경로와 DB 연결은 바꾸지 않는다.
- 사이트 도메인은 서버의 기존 DNS로 조회해 컨테이너 hosts에 넣는다. 컨테이너를 교체할 때 다시 조회하며, 사설·메타데이터 주소는 거부한다. 무료 VPN의 DNS 장애에 의존하지 않기 위한 설정이다.
- OpenVPN 서버 인증서와 `opengw.net` 이름을 검증한다. Scrapy도 `BrowserLikeContextFactory`로 뽐뿌 HTTPS 인증서를 검증한다. VPN에 DB 인증정보나 SSH 개인키를 전달하지 않는다.
- 공식 VPN 설정에서 주소·전송 방식·인증서 블록만 추출하고 클라이언트 설정을 직접 만든다. 제공받은 실행 스크립트나 임의 옵션은 실행하지 않는다.

## 교체 기준

1. VPN Gate 공식 목록을 **5분마다** 새로 받는다. 정상 연결 유지 중이나 후보 재시도 대기 중에도 갱신한다. 특정 두 국가로 제한하지 않고 공식 목록의 유효한 공개 IPv4 후보를 사용하며, 같은 IP의 중복 항목은 제거한다.
2. 갱신 시각·후보 수·국가별 수·추가/제외 수·응답 SHA256을 `/var/lib/ppomppu-vpn/catalog.json`과 `catalog_refreshed` 로그에 남긴다. 갱신 실패 시 24시간 이내 캐시만 사용하며 캐시를 새 목록으로 표시하지 않는다.
3. systemd 타이머가 약 1분마다 실제 뽐뿌 목록을 조회한다. 크롤러와 같은 압축 지원 헤더로 요청하고 gzip/deflate 본문을 해제한 뒤 HTTP 200과 `bbs_new1`을 모두 확인한다. **성공한 VPN은 유지**하고 두 번 연속 실패하면 교체한다.
4. 최근 30일의 시도 이력을 보관한다. **아직 시도하지 않은 후보를 먼저 순환**하고 전체 목록을 확인한 뒤에는 가장 오래전에 시도한 후보부터 재검사한다. 대기 시간이 끝났다는 이유만으로 점수가 높은 실패 후보를 계속 먼저 선택하지 않는다.
5. 한 번에 최대 세 곳을 확인한다. 서로 다른 `/24`를 선택하고 국가도 분산한다. 실패 IP는 한 시간 제외하며, 올바른 압축 요청에도 HTTP 403이면 해당 중계 주소의 `/24`도 한 시간 제외한다. 이는 개별 차단 정책을 확정한 것이 아니라 후보를 분산하는 규칙이다.
6. 한 회차에서 모두 실패하면 컨테이너를 제거한다. 미시험 후보가 남아 있으면 60초, 후보를 소진했거나 목록을 받을 수 없으면 600초 대기한다. 이력은 `/var/lib/ppomppu-vpn/state.json`에 저장해 서비스 재시작·목록 갱신에도 유지한다.

뽐뿌 요청은 동시 1개, 요청 간격 2초, 요청 제한 시간 20초, 재시도 최대 2회다. 목록과 상세 모두 `PPOMPPU_PROXY_URL`과 동일한 브라우저 헤더를 사용하고 `gzip, deflate`를 지원한다고 알린다. 목록 대신 오류 HTML을 받거나 처리된 아이템이 0개면 수집 성공으로 기록하지 않는다. DB 저장 여부는 별도 운영 DB 조회로 확인해야 한다.

큐에는 `CRAWLER_BACKOFF_MIN_PPOMPPU_SECONDS=600`을 설정해 실패 후에도 최소 10분 기다린다. 정상 실행 간격은 `CRAWLER_INTERVAL_PPOMPPU_SECONDS=600`이다. 다른 사이트는 이 최소 대기의 영향을 받지 않는다.

## 설치·재배포

이미 Docker가 설치된 Linux 서버에서 저장소 루트를 기준으로 실행한다.

```sh
sudo docker build -t ppomppu-vpngate:20260914 ops/ppomppu-vpn
sudo install -d -m 755 /etc/ppomppu-vpn
sudo install -d -m 700 /var/lib/ppomppu-vpn
sudo install -m 755 ops/ppomppu-vpn/guard.py /usr/local/sbin/ppomppu-vpn-guard.py
sudo install -m 644 ops/ppomppu-vpn/ppomppu-vpn-guard.service /etc/systemd/system/
sudo install -m 644 ops/ppomppu-vpn/ppomppu-vpn-guard.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ppomppu-vpn-guard.timer
```

크롤러에는 `PPOMPPU_PROXY_URL=http://127.0.0.1:18888`을 설정한다. 현재 운영 크롤러는 host 네트워크를 사용하므로 위 주소로 접속할 수 있다. GitHub 배포 워크플로에도 같은 환경변수를 반영했다. 프록시를 쓰지 않는 서버에서 이 설정만 켜면 뽐뿌 수집이 실패하므로 먼저 위 서비스를 설치해야 한다.

운영 확인:

```sh
sudo systemctl status ppomppu-vpn-guard.timer --no-pager
sudo journalctl -u ppomppu-vpn-guard.service --since '-30 minutes' --no-pager
sudo docker inspect ppomppu-vpn --format '{{.State.Status}} {{.HostConfig.PortBindings}}'
```

대기 중에는 VPN 컨테이너가 없는 것이 정상이다. `recovered`는 목록 접근 복구, `healthy`는 목록 확인 성공이며 전체 크롤링이나 DB 저장 건수를 뜻하지 않는다. `relay_failed`에는 403·시간 초과·VPN 초기화 실패 원인을 남긴다. `attempt_history`가 VPN 목록 갱신에 따른 순환 이력이고, `failed_until`과 `failed_prefix_until`은 임시 제외 목록이다.

## 적용 기록

- 2026-09-13 17:22:57 UTC: 무료 국내 VPN을 통해 공개 목록·상세를 받아 기존 운영 파이프라인으로 `ppompu733987`을 저장했다. DB PK는 `130059`다. 이 한 건은 수동 검증이며 자동 수집 실적과 구분한다.
- 이후 같은 시험 경로도 응답을 멈췄으며 다른 공개 중계 서버에서 403·시간 초과가 확인됐다. 이 때문에 고정 VPN 한 곳을 운영 경로로 유지하지 않고 실제 목록 확인과 교체를 구성했다.
- 2026-09-14 13:10:58 UTC: 운영 크롤러에 뽐뿌 Spider와 실행 함수 두 파일만 반영했다. 이미지 `crawler-image:ppomppu-vpn-20260914`, ID `sha256:0139b1660cf7f45045509f23a68c6631c913976e37f504bbb3500522752e21f8`.
- 기존 DB 환경값, CPU·메모리·tmpfs·로그 설정 보존을 대조했다. 빈 수집이 실제 운영 로그에서 `exit=1`로 기록되는 것을 확인했다.
- 13:50 UTC에 뽐뿌 실패 최소 대기를 추가했다. 최종 이미지 `crawler-image:ppomppu-vpn-20260914-v2`, ID `sha256:aacda3affd8e6cd4535f5ff88e1d0fffdbd9e31ff8706594d44a4d3427706870`이며 운영 큐의 한 줄만 추가로 수정했다.
- 적용 후 13:13:59~13:15:59 UTC의 2분 CPU: 평균 **79.486%**, 최대 **86.040%**, iowait 평균 0.004%. 5초 간격 24개 표본이며 상시 사용률을 보장하는 수치는 아니다.
- 최종 큐 반영 후 13:59:35~14:01:35 UTC의 2분 CPU는 평균 **78.795%**, 최대 **86.290%**였다. 운영 로그의 뽐뿌 `backoff 600s`를 확인했다.
- **14:02 UTC / 23:02 KST 최종 확인:** 자동 VPN 검사 21회 실패, 자동 목록 복구 0회, 뽐뿌 자동 DB 갱신 0건. 다른 네 사이트는 최종 배포 이후 DB 갱신을 확인했다. 자동 교체 타이머는 실행 중이며 정상 수집 복구를 보장하지 않는다.

### 목록 순환·검사 오류 수정

위 21회 실패 기록은 수정 전 상태 검사 결과다. 이후 같은 국내 VPN `121.179.32.138`에서 curl의 `Accept-Encoding: identity` 요청은 **403·571바이트**, `--compressed` 요청은 **200·정상 목록**을 반환하는 것을 비교했다. Python 요청도 압축 지원 헤더를 사용하면 200이었다. 따라서 앞선 결과를 모든 무료 VPN이 차단됐다는 근거로 해석하면 안 된다.

상태 검사에 gzip/deflate 요청·해제를 적용하고 이전 검사에서 생성한 제외 목록은 `probe_version=2` 전환 시 한 번 초기화했다. 크롤러의 상세 요청도 목록과 같은 헤더를 사용하도록 맞췄다. 별도로 목록 정기 갱신과 미시험 후보 우선 순환을 적용했다.

- 14:34 UTC 공식 목록: 유효 후보 98개, 10개 국가. 이전에 포함하지 않았던 후보를 포함해 24개 추가, 1개 제외를 기록했다.
- **14:36:46 UTC** Spider 한 파일을 운영 반영했다. 이미지 `crawler-image:ppomppu-refresh-20260914`, ID `sha256:2c9ee880b2bad1fa0b56b4df59ee9b418246258488d744d87bd8809cdb8be7a1`.
- **14:39:48 UTC** 운영 큐의 뽐뿌 목록·상세 200과 배포 후 DB 저장·갱신 68건을 확인했다. 수동 파서 저장이 아닌 정규 큐의 자동 수집이다.
- **14:41:07 UTC / 23:41:07 KST** 정규 수집이 262초 만에 `exit=0`으로 종료됐다. 최종 DB 반영은 **100개 행**이다. 14:40:23 UTC의 목록 자동 갱신에서 후보 4개 추가·4개 제외도 확인했다.
- **15:00:28 UTC / 2026-09-15 00:00:28 KST** 두 번째 정규 수집도 258초 만에 `exit=0`으로 종료됐다. 해당 주기에서 **101개 행**의 DB 저장·갱신을 확인했고, 두 주기에 걸친 고유 갱신 행은 103개다. 정상 종료 후 최소 600초를 기다린 뒤 공용 큐의 실행 자리를 배정받으므로 시작 시각 간격은 10분보다 길어질 수 있다.
- **15:02:31 UTC** 확인 시 다른 네 사이트도 DB 갱신을 계속했다. 수정 후 VPN 상태 검사 24회 성공, 목록 자동 갱신 4회, 중계 서버 교체 시도 실패 0회를 기록했다. 최신 목록은 8개 국가의 후보 96개이며 정상 VPN은 유지됐다. 타이머는 enabled·active이고 크롤러·FlareSolverr·VPN 컨테이너 모두 OOM·자체 재시작이 없었다.
- 뽐뿌 수집 중 14:39:45~14:41:45 UTC의 2분 CPU는 평균 50.152%, 최대 53.820%였다. 사이트 실행 조합에 따라 부하는 달라진다.
- 목록 순환·갱신·압축 응답·소유권 검사 16개, 뽐뿌 요청·실패 처리 6개 테스트가 통과했다.

전체 복구 및 최종 DB 확인 기록은 [서버 운영 기록](../crawler-cpu-20260913.md)에 이어서 기록한다. 서버의 `/root/ppomppu-vpngate-20260914/refresh-followup-verification.json`에 후속 주기 증빙을 보관했다.

## 중지·롤백

```sh
sudo systemctl disable --now ppomppu-vpn-guard.timer
sudo systemctl stop ppomppu-vpn-guard.service
```

컨테이너를 제거하기 전 `geteverything.ppomppu-vpn=1` 라벨을 확인한다. 목록·상세 헤더 수정 전 컨테이너는 `crawlers-bot-before-refresh-20260914`이며, 이전 guard·목록·상태 백업은 `/root/ppomppu-vpngate-20260914/rotation-refresh-before`에 있다. VPN 적용 전 컨테이너는 `crawlers-bot-before-vpn-20260914`, 실패 최소 대기 변경 전 컨테이너는 `crawlers-bot-before-vpn-backoff-20260914`다. 기존 상태 검사로 되돌리면 압축 요청 차이로 정상 VPN을 다시 실패 판정할 수 있다.

로컬 소스와 워크플로 변경은 아직 커밋·푸시하지 않았다. 서버 변경과 GitHub 재배포 반영은 구분해야 한다.

## 참고

- [VPN Gate 공식 OpenVPN 안내](https://www.vpngate.net/en/howto_openvpn.aspx)
- [VPN Gate 공개 서비스 FAQ](https://www.vpngate.net/en/about_faq.aspx)
- [VPN Gate 연결 로그 정책](https://www.vpngate.net/en/about_abuse.aspx)
- [Tinyproxy 1.11.3 공식 설정 예제](https://raw.githubusercontent.com/tinyproxy/tinyproxy/1.11.3/etc/tinyproxy.conf.in)
