# GET EVERYTHING PROJECT


# 프로젝트 구조

프로젝트는 크게 AWS Lambda와 Django 프레임워크로 구성되어 있다.
Django프레임워크는 ORM과 Admin을 담당하고 Lamda는 크롤링을 담당한다.
빌드는 Bazel을 이용해서 monorepo형식을 취한다.

### 1. Django

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

### 3. Lambda


### 4. Bazel

        
### 5. Scrapy

[Scrapy 메뉴얼](https://scrapy.org/)
