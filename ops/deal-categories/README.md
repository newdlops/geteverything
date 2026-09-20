# 제목 기반 표준 분류

최신 분류 규칙과 미분류 1% 이하 작업은 [2026-09-19 운영 기록](rules-20260919.md)을 참고한다. 수량·단가·환율 처리는 [MEASUREMENTS.md](MEASUREMENTS.md)에 정리했다. 아래 초기 측정 수치와 이미지 식별자는 첫 분류 배포 시점의 기록이다.

커뮤니티의 원본 `deals.category`를 보존하면서 별도의 표준 카테고리를 만든다. 신규 수집과 제목·판매처·원본 카테고리 변경은 DB 트리거가 작업으로 기록하고, 크롤러와 분리된 워커가 규칙 분류를 먼저 실행한다. 외부 추론 API는 사용하지 않는다.

## 초기 적용 기록

2026-09-18 KST 운영 배포 완료. 준비일 기준 이미지 태그는 `categories-20260917`이다.

- 웹: `158.180.67.53`, Swarm `django_django`, 이미지 `my-django-app:categories-20260917`.
- 크롤러: `168.107.29.18`, 별도 서비스 `geteverything-categories.service`.
- DB: migration `deals.0009_deal_classifications`, 테이블 `deal_classifications`, `classification_state`.
- 규칙 결과만 자동 공개. 로컬 Qwen3.5 2B Q4_K_M 결과는 어드민 검토 후보로 저장한다.
- 기존 글은 규칙으로 백필한다. 규칙이 판단하지 못한 과거 글은 검토 대상으로 남기며 LLM 백필은 꺼져 있다.
- 기존 크롤러 컨테이너와 썸네일 워커를 재시작하지 않았다.

00:32 KST 확인 시 전체 42,945건 중 기존 글 4,000건을 스캔했다. 규칙 분류 완료는 신규 5건, 과거 글 1,878건이며, 과거 글 2,121건은 검토 대상, 신규 9건은 모델 대기 상태였다. 백필은 이 스냅샷 이후에도 계속된다. 모든 스캔 완료와 모든 글의 분류 완료는 서로 다르다.

실제 뽐뿌 신규 글에서 `토퍼 매트리스 → 생활·주방 > 가구·침구`, `루테인 → 뷰티·건강 > 영양제`, `치킨피자 → 식품·음료 > 가공·간편식`이 수집 요청 후 약 0.08~0.83초에 처리됐다. 애매한 제목은 강제로 분류하지 않았다. 다섯 커뮤니티의 수집 갱신과 썸네일 서비스가 계속 동작하는 것을 확인했다.

## 분류와 사용 방법

표준 대분류는 14개이며 상품이 명확한 경우 세부 분류를 붙인다.

| 코드 | 표시 이름 |
| --- | --- |
| computer | PC·주변기기 |
| mobile | 모바일 |
| electronics | 가전·디지털 |
| games | 게임·소프트웨어 |
| food | 식품·음료 |
| home | 생활·주방 |
| fashion | 패션·잡화 |
| beauty | 뷰티·건강 |
| baby | 출산·육아 |
| pet | 반려동물 |
| sports | 스포츠·레저·취미 |
| auto | 자동차·차량용품 |
| culture | 도서·문화 |
| services | 상품권·혜택·서비스 |

정의는 `gadmin/categories/taxonomy.py`, 제목 규칙은 `rules.py`와 `vocabulary.py`에 있다. 제목 정규화는 가격·배송 표현을 정리하되 모델명과 용량은 유지한다. `context.py`는 제목이 불충분할 때 정확한 판매처 호스트·일부 게시판 정보를 보조 근거로 사용한다. 원본 커뮤니티 카테고리도 잘못 지정될 수 있으므로 제목의 상품 근거가 우선한다. 실제 서로 다른 상품군이 충돌하거나 상품을 알 수 없으면 미분류로 남긴다.

[어드민의 게시물 표준 분류](http://158.180.67.53:8001/admin/deals/dealclassification/)에서 제목 검색, 상태·방식·카테고리·사이트 필터, 모델 제안 확인, 수동 지정을 할 수 있다. 저장한 수동 분류는 이후 수집·백필·진행 중인 모델 응답보다 우선한다. 다시 자동 처리하려면 목록에서 선택 후 **선택한 글을 자동 분류로 되돌리고 다시 처리** 액션을 실행한다. 한 번에 최대 200건이다.

`GET /api/deals/` 응답에 `standard_category`와 `classification_status`가 추가됐다. 원래 `category`는 그대로다. 확정 전 `standard_category`는 `null`이며 모델 후보는 공개 API에 포함되지 않는다. `GET /api/deals/?standard_category=food`는 식품 대분류와 하위 분류를 함께 조회한다. 알 수 없는 코드는 HTTP 400이다.

## 작업 처리

1. `deals` INSERT 또는 제목·사이트·원본 카테고리·판매처·상품 링크 변경 시 트리거가 같은 트랜잭션에서 작업을 기록한다. 조회수만 갱신하면 재분류하지 않는다.
2. 워커는 신규 작업(priority 0)을 과거 작업(priority 10)보다 먼저 처리한다. 120초 작업 임대와 `SKIP LOCKED`로 중복 작업을 줄인다.
3. 규칙 결과는 바로 저장한다. 신규 글 중 애매한 제목만 로컬 모델 큐로 이동한다. 모델 요청은 별도 스레드 하나에서 실행해 규칙 처리를 막지 않는다.
4. 결과 저장 시 요청 revision·입력 제목·수동 지정 여부를 다시 확인한다. 오래된 응답은 새 제목이나 수동 분류를 덮어쓰지 못한다.
5. 백필은 15초마다 최대 100건, 역사 작업의 대기열이 200건 미만일 때만 추가한다. 커서를 DB에 저장해 재시작 후 이어간다. `rules_complete`는 과거 글의 규칙 검토가 끝났다는 뜻이다.

규칙 결과의 캐시 키는 정규화 제목·사이트·원본 카테고리·판매처·상품 링크 호스트와 분류기 버전을 포함한다. 수동 결과는 다른 글에 전파하지 않는다. 모델이 자원 보호로 내려가 있는 동안은 60초 뒤 다시 시도하며 제목의 실패 횟수를 소모하지 않는다. 잘못된 모델 출력은 최대 3회 후 `error`로 남는다.

## 서버 자원 제한

| 구성 | CPU 상한 | 메모리 상한 | 실행 조건 |
| --- | --- | --- | --- |
| 분류 워커 | 0.15 CPU | 192 MiB | 상시 실행 |
| 로컬 모델 | 0.20 CPU, 동시 요청 1개 | 3 GiB, 추가 swap 없음 | 자원 여유와 대기 작업이 있을 때 |

`geteverything-category-model-guard.timer`는 30초마다 상태를 확인한다. 모델 한도는 0.20 CPU이며, 2026-09-20에는 브라우저 작업 효율화와 함께 여유 자원을 확보하도록 시작·중지 기준을 조정했다. 2 vCPU 호스트에서 CPU 60% 미만·가용 메모리 4 GiB 이상인 관측이 두 번 연속이면 시작하고, CPU 80% 이상·가용 메모리 3 GiB 미만 또는 처리할 작업이 없으면 중지한다. 60~80% 사이에서는 현재 상태를 유지해 반복 시작·중지를 줄인다. 작업 수요에는 카테고리와 상품 추출 대기열을 모두 포함한다. 모델이 쉬는 동안에도 작업은 DB에 남고 규칙 분류·가격 처리는 계속된다.

[상품 식별·가격 이력](../product-identity/README.md)은 같은 로컬 엔진으로 동작한다. 상품 추출은 제목 근거·브랜드·모델·수량 구분을 검증하고 자동 상품임을 표시한다. 위의 카테고리 자동 공개 금지 정책은 유지한다. 느린 구조화 응답은 최대 240초, 작업 임대는 300초이며 모델 요청 중에도 새 글의 규칙·가격 계산은 계속된다.

컨테이너는 낮은 CPU 가중치, 읽기 전용 루트 파일시스템, 비특권 사용자, 제한된 프로세스 수를 사용한다. Docker 로그는 각각 2 MiB × 2개로 순환한다. 모델은 `127.0.0.1:8094`에서만 요청을 받는다. 클라이언트도 숫자 loopback 주소만 허용하고 환경 프록시·리다이렉트를 거부한다. 공개 모델 파일을 내려받는 과정과 실제 추론은 별개이며 상품 제목은 외부 API로 보내지 않는다.

## 로컬 모델 평가와 공개 기준

최근 미분류 개선 규칙과 재처리 기록은 [2026-09-18 규칙 보완](rules-20260918.md)에 정리했다. 아래 초기 평가 수치와 구분한다.

실제 크롤러 서버의 ARM CPU에서 llama.cpp, Q4_K_M, 0.25 CPU, context 2048, 비추론 모드로 평가했다. 규칙에 걸리지 않은 제목을 다수 포함한 어려운 표본이며, 작은 표본의 수치를 전체 운영 정확도로 해석하면 안 된다. 2B 실험은 각 600초 예산 안에 완료한 건수다.

| 모델·프롬프트 | 검토 라벨 일치 | 건당 시간 중앙값 | 최대 관측 메모리 |
| --- | --- | --- | --- |
| Qwen3.5 0.8B, root-1 | 17/40 (42.5%) | 7.04초 | 751 MiB |
| Qwen3.5 2B, root-1 | 19/35 (54.3%) | 16.54초 | 1,478 MiB |
| Qwen3.5 2B, root-2 | 20/34 (58.8%) | 15.50초 | 1,482 MiB |

세 평가에서 OOM은 없었으나 자동 공개 기준인 95%에 못 미쳤다. **2B는 검토 후보 제안만 하며 자동 공개하지 않는다.** 프롬프트를 개선한 평가도 정확도 기준을 통과한 것은 아니다. 자동 공개를 바꾸기 전에는 사람이 검증한 별도 미사용 표본으로 사이트·카테고리별 오류, 기권율, 처리 속도와 크롤링 영향을 다시 평가해야 한다.

규칙 회귀 표본 500건(사이트별 100건)에서는 415건을 분류하고 85건을 기권했다. 분류한 415건이 검토 라벨과 일치했다. **라벨은 코딩 어시스턴트가 검토했고 규칙 개선에도 사용했으므로, 사람 인증 정답이나 독립적인 운영 정확도 측정이 아니다.** 실제 과거 데이터는 제목 품질과 분포가 달라 자동 분류 비율도 달라진다.

평가 재현:

```sh
PYTHONPATH=. python ops/deal-categories/evaluate.py
python -m django test gadmin.categories.tests --settings=gadmin.categories.tests.settings --noinput
python -m unittest discover -s ops/deal-categories -p 'test_*.py'
```

모델 파일과 엔진은 버전 및 SHA-256으로 고정했다. 정확한 식별자는 `verification-20260918.json`에 기록했다. 크롤러의 `/root/category-model-benchmark-20260917/results.json`, `/root/category-model-benchmark-v2-20260917/results.json`에는 원시 결과가 있다.

## 운영과 배포

서버 설정 파일은 `/etc/geteverything-categories/runtime.json`과 `worker.env`이며 root만 읽는다. 환경 파일에 있는 DB 접속 정보를 로그나 문서에 출력하지 않는다. 모델 파일은 `/var/lib/geteverything-categories/models`, 수요와 자원 상태는 같은 디렉터리 아래 `state/demand.json`, `guard.json`에 있다.

현재 정책:

```text
CATEGORY_LLM_ENABLED=1
CATEGORY_LLM_AUTO_PUBLISH=0
CATEGORY_LLM_BACKFILL=0
```

크롤러 서버에서 상태 확인:

```sh
sudo systemctl status geteverything-categories.service
sudo systemctl status geteverything-category-model-guard.timer
sudo docker exec geteverything-category-worker python -m gadmin.categories.worker --status
sudo cat /var/lib/geteverything-categories/guard.json
sudo journalctl -u geteverything-categories.service -n 30 --no-pager
```

일반 코드 업데이트는 웹에서 migration을 먼저 적용한 뒤 크롤러 체크아웃에서 `sudo python3 ops/deal-categories/deploy.py`로 한다. `.github/workflows/deploy.yaml`에도 같은 순서를 추가했다. 기존 크롤러 이미지를 기반으로 별도 워커 이미지를 만들고, 규칙 테스트·DB 스키마 확인 후 워커만 재시작한다. 현재 모델 공개 정책은 유지한다. 처음 설치할 때는 위 root 전용 설정과 모델 파일, state 디렉터리가 필요하다. 초기 적용본은 크롤러 `/root/category-worker-20260917/source`에 보관돼 있다.

처리를 중지하려면 먼저 모델 guard 타이머와 분류 서비스를 중지하고 모델 컨테이너를 정지한다. 기존 크롤러·썸네일 서비스는 별도다.

```sh
sudo systemctl disable --now geteverything-category-model-guard.timer
sudo systemctl stop geteverything-category-model-guard.service
sudo systemctl disable --now geteverything-categories.service
sudo docker stop --time 5 geteverything-category-model
```

DB 요청은 남아 있어 재개할 수 있다. 이미 저장된 표준 분류도 보존된다. 워커 업데이트 이전 설정은 `/root/category-worker-backups/`에 있다. 웹 초기 적용 전 이미지는 `my-django-app:thumbnail-crawl-jobs-20260917`, 당시 Swarm 설정은 웹 서버 `/root/category-web-20260917/service.before.json`에 보관했다. 새 API를 사용하는 동안 분류 테이블을 삭제하거나 migration을 되돌리지 않는다.

## 검증 범위

- 분류 18개, 기존 썸네일 42개, 크롤러 관련 16개, 자원 보호 4개: 총 80개 테스트 통과.
- 운영 웹 이미지 안에서 분류 18개와 썸네일 42개를 다시 검증했다.
- PostgreSQL의 분리된 임시 스키마와 롤백 트랜잭션에서 트리거의 제목 변경·무변경·수동 보호·원자성을 검증했다.
- 로컬 Chromium에서 390/768/1440px 화면, 검색·빈 결과·상태 필터·수동 수정·자동 재처리와 가로 넘침을 확인했다. 운영 어드민 로그인 후 화면을 직접 검사한 것은 아니다.
- 운영 API 정상 응답·카테고리 조회·잘못된 코드 400·CSS 200, 실제 신규 수집 후 분류, 워커 무재시작·OOM 없음, 모델 자원 보호 중지를 확인했다.
- 향후 지속적인 수집 성공이나 분류 정확도를 보장하는 검증은 아니며, 미분류·검토 대상을 별도로 관찰해야 한다.
