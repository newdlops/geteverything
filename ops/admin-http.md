# 어드민의 80 포트 라우팅

운영 주소: `http://158.180.67.53/admin/`.

Traefik의 `http` 진입점에서 `django-admin-http` Swarm 라우터가
`django` 서비스의 내부 8000 포트로 요청을 전달한다. `/admin`과 `/admin/`,
정적 파일 `/static/`, 미디어 `/media/`, 편집기 `/summernote`와 `/summernote/`를
같은 호스트에서 제공한다. Django의 기존 로그인과 권한 검사를 사용한다.

재배포 설정은 `ops/storage-monitoring/docker-compose.web.yml`의
`services.django.deploy.labels`에 있다. 기존 배포 워크플로가 이 파일을 병합한다.
서버의 `/home/docker/django/docker-compose.yml`에도 같은 라벨을 유지한다.
`/install/`은 별도의 기존 라우터가 처리하며 8001 포트의 직접 접속도 유지된다.

적용 시에는 서버 Compose 파일을 백업하고 `docker stack config`로 검증한 뒤
`docker service update --label-add ... django_django`로 서비스 라벨만 갱신한다.
이미지 빌드나 `docker stack rm`은 필요하지 않다.

확인 항목:

- `/admin`의 슬래시 리디렉션과 `/admin/`의 로그인 리디렉션
- 로그인 HTML과 연결된 CSS·JavaScript 응답
- 같은 출처의 CSRF 토큰을 포함한 빈 로그인 제출의 필드 검증
- 비로그인 상태의 운영 화면 접근 시 로그인 요구
- 기존 `/install/` 및 8001 포트의 정상 응답

Traefik 라우팅 설정 참고:
[Docker Swarm 라우팅](https://doc.traefik.io/traefik/v3.6/reference/routing-configuration/other-providers/swarm/).
