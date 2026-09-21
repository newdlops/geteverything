# 2026-09-21 로컬 이어 학습 백업

- 실행: `45c2e1610dd82f007e62`, 프롬프트 `product-sft-4`, 학습 272건 / 검증 70건.
- 서버 285 step에서 인계; Mac GPU 472 step까지 수행 후 비정상 기울기로 보호 중지. 해당 step의 잘못된 기울기는 적용되지 않았다.
- Mac CPU 4스레드로 저장된 472 step에서 재개해 1,088 step 완료. 마지막 616 step과 손실 검증은 360.6초. 중앙값 0.45초/step.
- 검증 손실 0.16290054 → 0.02333193, 최선 체크포인트 1,088 step. 이는 상품 추출 정확도 평가 결과가 아니다.
- 서버에 가져와 GGUF 변환과 기존/후보 생성 평가를 실행 중. 운영 반영 여부는 최신 `evaluation.json` 및 서버 `active.json`으로 확인한다.
- `meta/executed-training-source.py`는 이번 실행에 사용한 GPU 시험 포함 소스다. 표준 실행 코드는 검증된 CPU 경로만 제공한다.
- 기반 모델과 캐시는 저장하지 않는다. 기반 모델의 고정 revision·체크섬은 `meta/downloaded.json`, 가중치·optimizer는 `best/`, `checkpoint/`로 복구한다.
