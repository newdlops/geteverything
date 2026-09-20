# Product identity model backups

학습 산출물의 복구용 백업이다. 대형 기반 모델과 재생성 가능한 frozen cache는 저장하지 않는다.

- `checkpoint/`: 학습 중단 시 재개할 수 있는 LoRA와 optimizer 상태
- `meta/`: 당시 데이터셋·학습 상태·시도 설정
- 최종 학습이 끝나면 같은 run 디렉터리에 `best/`, `adapter.gguf`, `evaluation.json`, `manifest.json`을 추가한다.

`.safetensors`, `.pt`, `.gguf`는 Git LFS로 관리한다. 백업에는 비밀번호, 환경변수, SSH 키를 넣지 않는다.
