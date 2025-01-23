# GET EVERYTHING PROJECT
핫딜을 찾아 여기저기 방황하지 않게 모든걸 긁어오는 말그대로 '겟 에브리띵'을 위한 프로젝트

## 프로젝트 구조

프로젝트는 크게 AWS Lambda와 Django로 구성되어 있다.
Django프레임워크는 ORM과 Admin을 담당하고 Lamda는 크롤링을 담당한다.
빌드는 Bazel을 이용해서 monorepo형식을 취한다.

### 1. Django
#### 1.1 콘솔 실행
spider나 코드의 수동 테스트를 위해서 파이썬 콘솔에서 실행한다.
```angular2html
python manage.py shell
```

#### 1.2 앱 추가
````angular2html
python manage.py startapp [app_name]
````

#### 1.3 모델 마이그레이션
````angular2html
python manage.py migrate
python manage.py makemigrations polls
````

#### 1.4 배포
배포는 docker 이미지로 uwsgi를 사용하도록 이미지를 배포한다
````angular2html
docker build -t my-django-app . --platform=linux/amd64
docker save -o django.tar my-django-app
docker load -i django.tar
````

### 2. AWS SAM
#### 2.1 설치
아래 링크를 참조하여 SAM CLI를 설치한다

[SAM설치 메뉴얼](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)


#### 2.2 프로젝트 설정



#### 2.2 Lambda 실행

##### 2.2.1 빌드
```
sam build --cached --parallel --use-containers

sam build
```

##### 2.2.2 로컬 실행
도커가 서비스에 띄워져 있어야 한다

```
sam local invoke --env-vars locals.json

sam local invoke

sam local start-api --env-vars locals.json --warm-containers EAGER

sam local start-api
```
#### 2.3 배포

최초 배포시
sam deploy --guided
이후
sam deploy

### 3. Lambda
크롤링은 항시 가동하는 서버가 켜져있기보다는 AWS Lambda를 통해서 이루어진다. 배포는 SAM으로 진행한다.

### 4. Bazel
django와 lambda를 아우르는 모노레포를 구성하기 위해서 Bazel을 도입중이다.(영원히 못할 가능성도 있지만...)
        
### 5. Scrapy
본 프로젝트의 크롤링은 Scrapy가 담당하고 있다. spider를 통해서 수집된 정보를 pipeline에서 django orm으로 디비에 저장한다.

[Scrapy 메뉴얼](https://scrapy.org/)
