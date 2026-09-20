# 핫딜 크롤러

뽐뿌, 에펨코리아, 어미새, 쿨엔조이, 아카라이브에서 Scrapy로 수집한 핫딜을 Django의 `Deal` 모델에 저장한다.

## 코드를 읽는 순서

1. [`run_queue.py`](run_queue.py): 사이트별 프로세스를 실행하고 동시 실행 수, 반복 주기, 실패 후 대기, 종료를 관리한다.
2. `<site>/crawler/crawler.py`: Django를 초기화한 뒤 해당 사이트의 Scrapy Spider를 실행한다.
3. `<site>/spider/`: 목록·상세 페이지를 요청하고 파싱한 데이터를 Item으로 전달한다.
4. `<site>/pipeline/`: 사이트별 날짜·가격·URL 변환과 갱신 필드를 정의한다.
5. [`pipelines.py`](pipelines.py): 공통 필드 구성, ORM 저장, 재수집 필드 갱신을 처리한다.

쿨엔조이는 Spider와 Pipeline이 각각 `coolnjoy/spider.py`, `coolnjoy/item_pipeline.py`에 있다. Item은 수집 필드의 스키마를 정의하고, [`utils/prices.py`](utils/prices.py)는 뽐뿌와 에펨코리아의 제목 가격 추출을 담당한다.

## Pipeline의 저장 규칙

`DealPipeline.process_item()`은 `get_defaults()`로 저장할 기본 필드를 만든 뒤, 글 ID로 레코드를 조회하거나 생성한다. 이어서 `get_updates()`의 필드를 적용하고 저장한다. 입력 Item은 그대로 반환한다.

- `get_defaults(item)`: 공통 기본 필드에 사이트별 변환 결과를 더한다. 기본적으로 최초 수집에만 적용된다.
- `get_updates(item)`: 추천·비추천·조회 수 등 매번 갱신할 필드를 반환한다.
- `update_existing_defaults = True`: 기본 필드도 재수집 때 갱신한다. 기존 동작대로 에펨코리아만 사용한다.

| 사이트 | 글 ID 접두사 | 재수집 시 갱신 범위 |
| --- | --- | --- |
| 뽐뿌 | `ppompu` | 추천·비추천·조회 수, 배송비 |
| 에펨코리아 | `fm` | 기본 필드, 추천·비추천·조회 수, 배송비, 커뮤니티명 |
| 어미새 | `eomisae` | 원문 URL, 추천·비추천·조회 수 |
| 쿨엔조이 | `coolnjoy` | 추천·조회 수 |
| 아카라이브 | `arca` | 원문 URL, 추천·비추천·조회 수 |

모든 사이트는 `update_at`과 유효한 판매처 링크도 갱신한다. 썸네일은 최초 생성 때만 원본 URL을 기록하고 이후에는 별도 이미지 작업이 저장한 URL을 보존한다. FMKOREA도 썸네일은 재수집 기본 필드 갱신에서 제외한다. 저장 시 변경 필드만 지정해 이미지 작업의 동시 갱신을 덮어쓰지 않는다. 기존 데이터와의 호환을 위해 `ppompu` 접두사, 커뮤니티명 대소문자, 통화·날짜 변환 규칙을 유지한다. 아카라이브 원문 작성 시각은 UTC로 해석한다.

상품 페이지에서 대표 이미지를 찾아 영속 정적 저장소에 보관하는 작업과 90일 TTL은 [상품 썸네일 운영 문서](../ops/product-thumbnails/README.md)를 참조한다. 이미지 수집·변환은 크롤러 실행과 분리해 웹 서버의 제한된 별도 작업에서 수행한다.

원문의 명시적 종료·삭제가 확인되면 `is_end=True`를 저장하고 가격 이력은 유지한다. 접속 차단·오류는 종료로 처리하지 않으며 404는 시간 간격을 둔 재확인 후 확정한다. 기존 글도 회차당 최대 5개씩 재확인한다. 판정 근거·주기·검증 결과는 [게시글 상태 운영 문서](../ops/deal-availability-20260920.md)를 참조한다.

## 실행

프로젝트 루트에서 Python 의존성과 Django의 DB 환경변수를 준비한 뒤 실행한다. 크롤러의 기본 설정 모듈은 `gadmin.admin.settings`이며 `DJANGO_SETTINGS_MODULE`로 바꿀 수 있다.

```bash
# 선택한 사이트를 한 번씩 수집
python -m crawlers.run_queue --once --sites ppomppu,eomisae

# 모든 사이트를 반복 수집
python -m crawlers.run_queue

# 사이트별 진입점을 직접 실행
python -m crawlers.ppomppu.crawler.crawler
```

주요 환경변수는 다음과 같다. 전체 목록은 `run_queue.py` 상단에 있다.

| 환경변수 | 역할 |
| --- | --- |
| `CRAWLER_SITES` | 수집할 사이트 목록, 쉼표로 구분 |
| `CRAWLER_MAX_CONCURRENT` | 전체 동시 실행 수 |
| `CRAWLER_MAX_SELENIUM` | Selenium 사이트의 동시 실행 수 |
| `CRAWLER_SELENIUM_SITES` | Selenium 제한을 적용할 사이트, 기본값 `fmkorea` |
| `CRAWLER_INTERVAL_SECONDS` | 성공한 수집 사이의 대기 시간, 기본 60초 |
| `CRAWLER_MAX_RUNTIME_SECONDS` | 실행당 제한 시간, 기본 3,600초 |
| `CRAWLER_STATUS_RECHECK_LIMIT` | 사이트별 회차당 기존 글 상태 재확인 수, 기본·상한 5, 0이면 중지 |
| `SELENIUM_BLOCK_MEDIA` | Chrome의 이미지·웹폰트·일반 영상/음원 파일 다운로드 제한, 기본 `1` |
| `SELENIUM_IDLE_BLANK_PAGE` | HTML·쿠키 확보 후 빈 페이지로 이동해 대기 중 페이지 실행 중단, 기본 `1` |

사이트별 주기·제한 시간은 `CRAWLER_INTERVAL_<SITE>_SECONDS`, `CRAWLER_MAX_RUNTIME_<SITE>_SECONDS`로 지정한다. `<SITE>`에는 `PPOMPPU`처럼 대문자 사이트명을 넣는다.

Selenium 자원 제한은 브라우저 세션을 유지하면서 적용한다. `SELENIUM_BLOCK_MEDIA`는 이미지 로딩을 차단하고 웹폰트·영상·음원의 일반 파일 확장자를 제한한다. 확장자가 없는 스트리밍 요청까지 제한하지는 않는다. HTML의 이미지 URL 속성, JavaScript, CSS는 그대로 사용한다. 이미지 로딩에 의존하는 사이트는 `SELENIUM_BLOCK_MEDIA=0`으로 되돌릴 수 있다. 빈 페이지 전환에 의존성 문제가 있으면 `SELENIUM_IDLE_BLANK_PAGE=0`으로 되돌린다. 같은 이름의 Scrapy 설정이 있으면 환경변수보다 우선한다. 별도 FlareSolverr 서비스에는 이 설정이 적용되지 않는다.

아카라이브의 FlareSolverr 경로는 스파이더·도메인별 세션 하나를 재사용한다. 응답 HTML·쿠키를 확보한 뒤 `about:blank`로 이동하고, 수집 종료 시 세션을 제거한다. 프로세스가 비정상 종료돼도 같은 이름의 세션을 회수하며 사용 중인 세션은 10분 TTL로 재생성한다. 미들웨어 우선순위 650으로 Scrapy 쿠키 처리(700) 전에 쿠키를 전달한다. 일반 HTTP가 두 번 차단되면 그 회차에서는 재사용 브라우저를 사용해 매 페이지의 실패 요청을 줄인다. 실패 응답은 503으로 남기고 재시도는 한 번으로 제한한다. `flare/` 통계로 일반 요청 성공·브라우저 요청·문서 해제·오류를 구분한다.

운영의 성공 후 대기 시간은 아카라이브 600초, FM코리아 180초, 뽐뿌 600초다. 사이트별 환경변수 `CRAWLER_INTERVAL_<SITE>_SECONDS`로 설정하며 나머지는 기본 60초를 유지한다. 한 회차의 페이지 범위는 줄이지 않는다. 실제 재수집 간격에는 회차 실행 시간과 공용 큐 대기 시간이 추가된다.

운영 적용 시 기존 컨테이너 설정과 이미지를 백업하고, 실행 중인 수집이 끝난 뒤 변경 이미지를 적용한다. 적용 전후 같은 시간 구간의 CPU 사용량, 사이트별 수집 건수와 소요 시간을 비교한다. 수집 오류가 늘면 위 설정을 끄거나 기존 이미지로 복구한다. 단위 테스트는 실제 사이트 수집 성공과 CPU 감소율을 보장하지 않는다.

현재 배포 워크플로는 크롤러에 1 CPU·8GiB, 실행 가능한 1GiB tmpfs `/tmp`, Docker local 로그 20MiB × 5개, `unless-stopped` 재시작 정책을 적용한다. 로그는 `docker logs crawlers-bot`으로 확인한다. FlareSolverr의 별도 운영 설정·보호 타이머·검증 결과는 [서버 작업 기록](../ops/crawler-cpu-20260913.md)을 참조한다.

쿠키 전달 순서 수정, 브라우저 세션 재사용, 모델의 CPU 여유 확보와 실제 운영 측정은 [2026-09-20 효율화 기록](../ops/crawler-efficiency-20260920.md)을 참조한다.

## 회귀 테스트

프로젝트 루트에서 실행한다. Django와 표준 `unittest`를 사용하므로 아래 테스트에는 pytest가 필요하지 않다.

```bash
python -m django test \
  crawlers.tests.unit.test_pipelines \
  crawlers.tests.unit.test_run_queue \
  crawlers.tests.unit.test_selenium_resources \
  crawlers.tests.unit.test_flare_resources \
  crawlers.tests.unit.test_availability \
  crawlers.tests.unit.test_recovery_parsing \
  --settings=crawlers.tests.settings --verbosity=2
```

테스트는 사이트별 저장 필드, 제목 가격 추출, 잘못된 날짜 입력, 동시 실행 제한, 실패 후 대기와 종료 동작을 검증한다. 게시글 상태 테스트는 종료 표시의 범위, 오탐 방지, 삭제 재확인과 복구도 다룬다. 브라우저 실행과 네트워크 요청은 모의 처리하므로 실제 사이트의 현재 구조는 별도 운영 검증이 필요하다.

기존 파이프라인 테스트는 ORM 쓰기를 모의 처리한다. 상태 저장 테스트는 별도 메모리 SQLite에 최소 게시글 테이블과 실제 상태 모델을 생성해 상태 전이 SQL을 검증한다. 운영 DB와 외부 사이트에는 접속하지 않는다. 운영 PostgreSQL에서 길이 제한 없이 사용하는 `article_id`에 대한 SQLite의 `fields.E120` 검사만 테스트 설정에서 제외한다.
