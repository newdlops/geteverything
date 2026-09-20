# Interim checkpoint backup

- source host: `168.107.29.18`
- training run: `0436aaa9f41666a002ff`
- captured: 2026-09-21 (KST)
- captured training step: `282/984`
- purpose: 서버 손실에 대비한 중간 재개 지점
- status at capture: `training`

이 백업은 최종 품질 평가나 운영 반영을 의미하지 않는다. 최종 adapter와 평가 결과는 학습 종료 후 같은 run 아래에 추가한다.

## Final evaluation snapshot

- final status: `rejected` (not promoted; no active adapter)
- completed steps: `984/984`; best step: `738`
- validation loss: `0.5506716` baseline → `0.1242860` best
- held-out exact correctness: `12/62` baseline → `31/62` candidate
- valid outputs: `39/62` baseline → `52/62` candidate
- false merges: `7` baseline → `2` candidate; regressions: `2`
- pair false splits: `31` baseline → `24` candidate
- p95 generation latency: `33.28s` baseline → `33.395s` candidate

The adapter changed real weights and improved loss and pair recall, but the promotion gate correctly rejected it because the accuracy floor, valid-output, regression, and false-merge checks did not pass. `evaluation.json` and `generation-progress.json` contain the complete gate output and per-example results.
