# Mac에서 학습하고 크롤러 서버에서 검증하기

M1 Pro 10코어·32GB Mac에서 서버와 동일한 Qwen3.5 2B 체크포인트,
PyTorch 2.8.0 / Transformers 5.3.0 / PEFT 0.18.1 / safetensors 0.6.2를 사용한다.
외부 AI API는 사용하지 않는다. 모델은 공식 저장소의 고정 revision과 체크섬으로 받는다.

학습 파일은 Git에서 제외되는 `.cache/product-training/`에 둔다.
기반 모델은 약 4.6GB이며 데이터·캐시·가상환경을 포함해 여유 공간 12GiB 이상을 확보한다.
서버 작업을 이어받을 때에는 데이터셋, 모델 revision, 프롬프트, recipe를 유지한다.
서버 트레이너를 정상 중지한 뒤 `checkpoint/`와 `best/`를 함께 복사한다.
`runs/<run_id>/cache/`도 복사하면 완료한 전처리를 재사용한다.

```sh
python ops/product-identity/prepare_training.py --root .cache/product-training
PYTHONPATH=. HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false \
  caffeinate -i .cache/product-training-venv/bin/python ops/product-identity/train.py \
  --root .cache/product-training --dataset .cache/product-training/dataset.json --threads 4
```

서버에서 복사한 `checkpoint.json`이 있으면 다운로드도 같은 revision을 사용한다.
서버 CPU 0.35코어에서 관측한 약 19초/step에 비해 Mac CPU 4스레드 시험은 약 0.4초/step이었다.
입력 길이와 다른 앱 사용량에 따라 달라지며 생성 평가 시간은 별도다.
GPU 시험은 일부 데이터에서 비정상 기울기로 중지됐으므로 이 작업에는 CPU 경로를 사용한다.
체크포인트는 4 step마다 저장하며 SIGTERM을 받으면 저장 후 중지한다.
Mac을 끄거나 덮개를 닫으면 중단될 수 있다. `caffeinate`는 학습 중 유휴 절전만 막는다.

완료 시 `status.json`의 상태가 `trained_awaiting_generation_eval`이어야 한다.
`best/`, `checkpoint/`, `result.json`, 정확히 일치하는 `dataset.json`과 완료 상태를 서버로 전송한다.
서버 기준 `adapter` 경로는 `/training/runs/<run_id>/best`로 맞춘다.
기존 서버 산출물과 상태를 백업한 뒤, 학습 서비스와 타이머가 실행 중이지 않을 때 가져온다.

```sh
sudo python3 /usr/local/lib/geteverything-product-training/runner.py --evaluate-only
```

이 경로는 데이터셋·기반 모델·실행 ID·어댑터 체크섬을 확인하고,
가중치 재학습 없이 GGUF 변환 → 기존/후보 생성 평가 → 기존 반영 조건 확인을 수행한다.
서버의 CPU·메모리 보호와 상품 추출 전용 반영 방식은 그대로 적용된다.
검증을 통과하기 전에는 운영 모델로 표시하지 않는다.
최종 어댑터와 복구 체크포인트는 기존 `backups/`의 Git LFS 백업 방식으로 보관한다.
