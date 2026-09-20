from django.db.models import Manager
from datetime import datetime
from django.db import models
from pgvector.django import VectorField, HnswIndex
from django.utils import timezone
import uuid
from gadmin.categories.taxonomy import CHOICES



class Deal(models.Model):
    article_id = models.CharField(verbose_name='글아이디', default=0)
    community_name = models.CharField(max_length=64, verbose_name='커뮤니티명', default='')
    origin_url = models.URLField(max_length=512, verbose_name='원글주소', blank=True, null=True)
    shop_url_1 = models.URLField(max_length=512, verbose_name='쇼핑몰 링크1', blank=True, null=True)
    shop_url_2 = models.URLField(max_length=512, verbose_name='쇼핑몰 링크2', blank=True, null=True)
    shop_name = models.CharField(max_length=64, verbose_name='쇼핑몰이름', blank=True, null=True)
    thumbnail = models.URLField(max_length=512, verbose_name='썸네일', blank=True, null=True)
    subject = models.CharField(max_length=512, verbose_name='제목', blank=True, null=True)
    subject_trgm_vector = VectorField(dimensions=1024, null=True, editable=False)
    category = models.CharField(max_length=32, verbose_name='카테고리', blank=True, null=True)
    price = models.IntegerField(verbose_name='가격', default=0)
    currency = models.CharField(max_length=32, verbose_name='단위', blank=True, null=True)
    delivery_price = models.IntegerField(verbose_name='배송료', default=0)
    numeric_evidence = models.JSONField('수집 가격 원문', null=True, blank=True, editable=False)
    recommend_count = models.IntegerField(verbose_name='추천수', default=0)
    dislike_count = models.IntegerField(verbose_name='비추수', default=0)
    view_count = models.IntegerField(verbose_name='조회수', default=0)
    create_at = models.DateTimeField(auto_now_add=True, verbose_name='크롤링 일자')
    write_at = models.DateTimeField(default=datetime(2024, 1, 1, 00, 00, 00), verbose_name='원글 작성일')
    update_at = models.DateTimeField(auto_now=True, verbose_name='업데이트일시')
    crawled_at = models.DateTimeField(default=datetime.now, verbose_name='크롤링 수집일')
    is_end = models.BooleanField(verbose_name='종료여부', default=False)

    objects = Manager()

    class Meta:
        db_table='deals'
        indexes = [
            # cosine 검색용 HNSW 인덱스
            HnswIndex(
                name="hotdeal_subject_trgm_vec_hnsw",
                fields=["subject_trgm_vector"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]


class DealAvailability(models.Model):
    deal = models.OneToOneField(Deal, primary_key=True, on_delete=models.CASCADE, related_name='availability')
    state = models.CharField(max_length=12, default='unknown', choices=[('unknown', '미확인'), ('active', '진행'), ('ended', '종료'), ('deleted', '원문 삭제')])
    last_outcome = models.CharField(max_length=12, default='unknown')
    evidence = models.CharField(max_length=200, blank=True, default='')
    checked_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    missing_since = models.DateTimeField(null=True, blank=True)
    missing_count = models.PositiveSmallIntegerField(default=0)
    next_check_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'deal_availability'


class DealClassification(models.Model):
    deal = models.OneToOneField(Deal, primary_key=True, on_delete=models.CASCADE, related_name='classification')
    category = models.CharField('표준 카테고리', max_length=32, choices=CHOICES, blank=True, default='')
    candidate = models.CharField('모델 제안', max_length=32, choices=CHOICES, blank=True, default='')
    status = models.CharField('처리 상태', max_length=16, default='pending', choices=[('pending', '규칙 분류 대기'), ('llm', '모델 분류 대기'), ('ready', '분류 완료'), ('review', '검토 필요'), ('error', '처리 실패')])
    source = models.CharField('분류 방식', max_length=16, blank=True, default='', choices=[('', '미분류'), ('rule', '상품 규칙'), ('llm', '로컬 모델'), ('manual', '수동 지정')])
    manual_override = models.BooleanField('수동 분류 유지', default=False)
    input_title = models.CharField('분류 대상 제목', max_length=512, blank=True, default='')
    title_hash = models.CharField(max_length=64, blank=True, default='')
    classifier_version = models.CharField('분류기 버전', max_length=160, blank=True, default='')
    reason = models.CharField('분류 근거', max_length=200, blank=True, default='')
    request_revision = models.BigIntegerField(default=1)
    priority = models.PositiveSmallIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField('재시도 횟수', default=0)
    requested_at = models.DateTimeField('요청 시각', default=timezone.now)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    classified_at = models.DateTimeField('분류 시각', null=True, blank=True)
    last_error = models.CharField('오류', max_length=120, blank=True, default='')

    class Meta:
        db_table = 'deal_classifications'
        verbose_name = '게시물 표준 분류'
        verbose_name_plural = '게시물 표준 분류'
        indexes = [models.Index(fields=['status', 'priority', 'next_attempt_at'], name='classification_due'), models.Index(fields=['category'], name='classification_category'), models.Index(fields=['title_hash', 'classifier_version'], name='classification_cache')]

    def __str__(self):
        return self.input_title or str(self.deal_id)


class ClassificationState(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    value = models.JSONField(default=dict)

    class Meta:
        db_table = 'classification_state'


class DealMeasurements(models.Model):
    deal = models.OneToOneField(Deal, primary_key=True, on_delete=models.CASCADE, related_name='measurements')
    input = models.JSONField('분석 입력', default=dict)
    result = models.JSONField('계산 결과', default=dict)
    status = models.CharField('처리 상태', max_length=16, default='pending', choices=[('pending','계산 대기'),('ready','단가 계산 완료'),('partial','정보 일부 확인'),('review','계산 보류'),('error','처리 실패')])
    parser_version = models.CharField('계산기 버전', max_length=32, default='', blank=True)
    request_revision = models.BigIntegerField(default=1)
    priority = models.PositiveSmallIntegerField(default=0)
    requested_at = models.DateTimeField('요청 시각', default=timezone.now)
    processed_at = models.DateTimeField('계산 시각', null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField('오류', max_length=120, default='', blank=True)

    class Meta:
        db_table = 'deal_measurements'
        verbose_name = '상품 수량·단가'
        verbose_name_plural = '상품 수량·단가'
        indexes = [models.Index(fields=['status','priority','lease_until'],name='measurements_due')]

    def __str__(self):
        return self.input.get('subject') or str(self.deal_id)


class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identity_key = models.CharField(max_length=64, unique=True, editable=False)
    name = models.CharField('상품명', max_length=240)
    brand = models.CharField('브랜드', max_length=100, blank=True, default='')
    model = models.CharField('모델', max_length=120, blank=True, default='')
    attributes = models.JSONField('규격·옵션', default=dict)
    category = models.CharField('표준 카테고리', max_length=32, choices=CHOICES, blank=True, default='')
    verified = models.BooleanField('운영자 확인', default=False)
    is_active = models.BooleanField('목록에 표시', default=True, db_default=True)
    merged_into = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='previous_identities', editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'products'
        verbose_name = '고유 상품'
        verbose_name_plural = '고유 상품'
        indexes = [models.Index(fields=['brand','model'], name='product_brand_model')]

    def __str__(self):
        return self.name


class DealProduct(models.Model):
    deal = models.OneToOneField(Deal, primary_key=True, on_delete=models.CASCADE, related_name='product_assignment')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True, related_name='assignments', verbose_name='연결 상품')
    input_title = models.CharField('입력 제목', max_length=512, default='', blank=True)
    extraction = models.JSONField('추출한 상품 정보', default=dict)
    candidates = models.JSONField('유사 상품 제안', default=list)
    status = models.CharField('상태', max_length=16, default='pending', choices=[('pending','상품 분석 대기'),('llm','모델 추출 대기'),('ready','연결 완료'),('review','연결 확인 필요'),('error','처리 실패')])
    source = models.CharField('처리 방식', max_length=16, default='', blank=True, choices=[('','미처리'),('rule','모델명·규격 규칙'),('llm','로컬 모델'),('learned','학습된 연결'),('manual','수동 연결'),('identifier','쇼핑몰 상품번호')])
    manual_override = models.BooleanField('수동 연결 유지', default=False)
    input_hash = models.CharField(max_length=64, default='', blank=True)
    processor_version = models.CharField('처리 버전', max_length=160, default='', blank=True)
    request_revision = models.BigIntegerField(default=1)
    identity_revision = models.BigIntegerField(default=1)
    price_revision = models.BigIntegerField(default=1)
    priority = models.PositiveSmallIntegerField(default=0)
    requested_at = models.DateTimeField(default=timezone.now)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField('처리 시각', null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField('처리 사유', max_length=160, default='', blank=True)

    class Meta:
        db_table = 'deal_products'
        verbose_name = '게시물 상품 연결'
        verbose_name_plural = '게시물 상품 연결'
        indexes = [models.Index(fields=['status','priority','next_attempt_at'], name='product_job_due'), models.Index(fields=['input_hash','processor_version'], name='product_extraction_cache')]

    def __str__(self):
        return self.input_title


class ProductSource(models.Model):
    deal = models.OneToOneField(Deal, primary_key=True, on_delete=models.CASCADE, related_name='product_source')
    input = models.JSONField(default=dict)
    revision = models.BigIntegerField(default=1)
    status = models.CharField(max_length=16, default='pending')
    priority = models.PositiveSmallIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField(default=0)
    requested_at = models.DateTimeField(default=timezone.now)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True)
    last_error = models.CharField(max_length=160, default='', blank=True)

    class Meta:
        db_table = 'product_sources'
        indexes = [models.Index(fields=['status', 'priority', 'next_attempt_at'], name='product_sources_due')]


class ProductReference(models.Model):
    source = models.ForeignKey(ProductSource, on_delete=models.CASCADE, related_name='references')
    key = models.CharField(max_length=64, db_index=True)
    namespace = models.CharField(max_length=40)
    scope = models.CharField(max_length=128, default='', blank=True)
    value = models.CharField(max_length=256)
    rank = models.PositiveSmallIntegerField(default=1)
    canonical_url = models.URLField(max_length=512)
    evidence = models.CharField(max_length=16, default='url')
    observed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'product_references'
        constraints = [models.UniqueConstraint(fields=['source', 'key'], name='product_reference_unique')]


class ProductPrice(models.Model):
    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name='price_observations')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, related_name='prices')
    identity_revision = models.BigIntegerField()
    price_revision = models.BigIntegerField()
    published_at = models.DateTimeField('게시물 작성일')
    observed_at = models.DateTimeField('가격 확인 시각', default=timezone.now)
    is_backfill = models.BooleanField(default=False)
    input = models.JSONField(default=dict)
    result = models.JSONField(default=dict)
    processed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'product_prices'
        constraints = [models.UniqueConstraint(fields=['deal','price_revision'], name='product_price_revision_unique')]
        indexes = [models.Index(fields=['product','published_at','id'], name='product_price_timeline'), models.Index(fields=['processed_at','id'], name='product_price_pending')]


class ProductMatchExample(models.Model):
    left_title = models.CharField('게시물 제목', max_length=512)
    right_title = models.CharField('비교 상품명', max_length=512)
    same_product = models.BooleanField('동일 상품')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True)
    extraction = models.JSONField(default=dict)
    origin = models.CharField('확인 출처', max_length=32, default='operator', choices=[('operator','운영자 확인'),('bootstrap_review','초기 검토 예제')])
    actor = models.CharField(max_length=150, default='', blank=True)
    example_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'product_match_examples'
        verbose_name = '상품 연결 학습 예제'
        verbose_name_plural = '상품 연결 학습 예제'


class ProductMatcherVersion(models.Model):
    version = models.CharField(primary_key=True, max_length=64)
    weights = models.JSONField(default=list)
    metrics = models.JSONField(default=dict)
    example_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'product_matcher_versions'
        verbose_name = '상품 매칭 학습 결과'
        verbose_name_plural = '상품 매칭 학습 결과'
