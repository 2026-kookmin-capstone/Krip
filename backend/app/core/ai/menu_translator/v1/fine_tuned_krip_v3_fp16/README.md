# fine_tuned_krip_v3_fp16

NLLB-200 기반 메뉴 번역 파인튜닝 모델 (FP16)

## 모델 로드 방식

모델 가중치(`model.safetensors`)는 용량 문제로 Git에 포함하지 않습니다.
HuggingFace Hub에 업로드되어 있으며, 코드 실행 시 자동으로 다운로드/캐싱됩니다.

- HuggingFace repo: `kyr778/krip-menu-translator-v3`
- 캐시 경로: `~/.cache/huggingface/hub/`
- 최초 실행 시에만 다운로드되며, 이후에는 캐시에서 로드됩니다.
