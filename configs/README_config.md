# Paper Radar Learning Configs

이 폴더는 기존 `fundamental_ml.yaml`과 `robotics.yaml` 스키마를 그대로 유지하면서,
학습 중심 논문 탐색을 위한 여러 개의 config를 주제별로 분리해 둔 묶음입니다.

포함 파일:

- `broad_ml.yaml`: 전체를 넓게 훑는 상위 config
- `ml_theory.yaml`: 일반화, sample complexity, PAC-Bayes, 이론 중심
- `optimization_training_dynamics.yaml`: optimizer, scaling law, loss landscape
- `representation_self_supervised.yaml`: self-supervised / embedding / latent representation
- `generative_modeling.yaml`: diffusion / flow / autoregressive / latent variable
- `llm_foundations_pretraining.yaml`: transformer, pretraining, long-context, tokenization
- `llm_posttraining_alignment.yaml`: instruction tuning, reward model, DPO/RLHF
- `data_curation_quality.yaml`: data recipe, synthetic data, contamination, deduplication
- `reasoning_in_context.yaml`: in-context learning, reasoning, verifiers, test-time compute
- `mechanistic_interpretability.yaml`: SAE, circuit, tracing, activation steering
- `probabilistic_causal.yaml`: Bayesian, causal, uncertainty, conformal prediction
- `reinforcement_learning.yaml`: RL, offline RL, bandits, model-based RL
- `trustworthy_robust_ml.yaml`: robustness, privacy, fairness, calibration, safety eval
- `multimodal_foundation_models.yaml`: VLM, speech-language, cross-modal learning
- `efficient_ml_systems.yaml`: distillation, quantization, MoE systems, inference/training efficiency
- `meta_learning_automl.yaml`: meta-learning, NAS, AutoML, test-time adaptation

참고:

- 주요 대학 / 주요 연구소 OpenAlex affiliation catalog와 통합된 `paper_radar_config_outstanding_scholars.yaml` 설명은 `README_catalogs.md`를 참고하세요.

추천 사용법:

1. 먼저 broad config로 1주 정도 신호를 봅니다.
2. 그중 관심도가 높은 3~5개 세부 config만 daily job으로 고정합니다.
3. 현재 starter 코드의 `actionability_score`는 로보틱스 쪽 키워드에 유리하므로, non-robot config에서는 `actionability: 0.0` 또는 낮은 값이 더 자연스러울 수 있습니다.

