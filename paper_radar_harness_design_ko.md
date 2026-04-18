# Paper Radar Harness 설계서 (ML / Robot AI)

이 문서는 "최근 출시된 주요 ML / Robot AI 논문을 자동으로 수집·선별·요약·배포"하는 harness의 실전 설계안이다.
핵심 원칙은 다음 세 가지다.

1. 검색은 넓게, 선별은 엄격하게.
2. 자유형 에이전트보다 검증 가능한 workflow를 우선한다.
3. 일간 레이더와 주간 딥다이브를 분리한다.

## 1. 목표

입력:
- 최근 arXiv / OpenReview 논문
- 선택적으로 Semantic Scholar / OpenAlex 메타데이터

출력:
- Daily Radar: 상위 5~10편의 짧은 요약
- Weekly Digest: 분야별 10~20편의 구조화 요약
- Archive: JSONL / SQLite / Postgres 저장

성공 조건:
- 최근성 유지
- robotics 관련성 우선
- 중복 제거 정확도
- 요약 포맷 일관성
- 후속 읽기 우선순위 제공

## 2. 권장 아키텍처

### 2.1 Ingestion Layer
- arXiv: 최신 preprint 수집
- OpenReview: venue/리뷰 메타데이터 수집
- Semantic Scholar: citation/relatedness 보강
- OpenAlex: topic / source / DOI / full-text availability 보강

### 2.2 MCP Layer
MCP 서버가 다음 도구를 노출한다.
- search_arxiv
- search_openreview
- enrich_with_semanticscholar
- enrich_with_openalex
- deduplicate_papers
- score_papers
- summarize_paper
- generate_digest
- export_digest

### 2.3 Harness Runner
Harness는 아래 순서를 강제한다.
1. 수집
2. 정규화
3. 하드 필터
4. 중복 제거
5. 점수화
6. 상위 논문만 LLM 요약
7. evaluator pass
8. digest 생성
9. 저장 / 배포

## 3. 왜 완전 자율 agent 대신 workflow-heavy harness인가

이 문제는 "무한 탐색"보다 "일관된 탐색 + 강한 필터링 + 안정된 출력"이 더 중요하다.
따라서 자유형 agent보다 다음 패턴이 더 잘 맞는다.

- Prompt chaining: 수집 → 필터 → 요약 → 검증
- Routing: ML 일반 / embodied / manipulation / humanoid 로 분기
- Evaluator-optimizer: 요약 초안 → 검증 → 수정
- 제한적 orchestrator: 주간 리포트 묶기

## 4. 데이터 모델

```python
@dataclass
class Paper:
    source: str                # arxiv / openreview / openalex / semanticscholar
    external_id: str
    title: str
    abstract: str
    authors: list[str]
    published_at: str | None
    updated_at: str | None
    url: str
    pdf_url: str | None
    venue: str | None
    categories: list[str]
    doi: str | None
    citations: int | None
    topics: list[str]
    review_signal: dict | None
    raw: dict
```

추가 저장 필드:
- normalized_title
- duplicate_key
- relevance_score
- novelty_score
- empirical_score
- source_signal_score
- final_score
- summary_ko
- summary_en
- read_priority
- notes

## 5. 추천 검색 범위

### 5.1 arXiv 카테고리
우선순위:
- cs.RO
- cs.LG
- cs.AI
- cs.CV

보조 키워드:
- robot learning
- manipulation
- dexterous
- visuomotor
- vision-language-action
- embodied
- world model
- imitation learning
- policy learning
- humanoid
- teleoperation
- sim2real

### 5.2 OpenReview venue 후보
- ICLR
- CoRL
- RSS (운영 방식에 따라 직접 사이트 병행)
- 기타 robotics/ML venue

## 6. 하드 필터 설계

### Daily Radar
- 최근 10일 이내
- 제목/초록/키워드 중 robotics relevance hit >= 1
- survey 제외 또는 점수 감점
- withdrawn/retracted 제외
- 중복 제목/DOI 제거

### Weekly Digest
- 최근 30일
- robotics track + supporting ML track 병렬 추출
- 구현 없는 position paper는 기본 감점
- benchmark/data/tool paper는 별도 버킷

## 7. 점수화 규칙

최종 점수:
`final = 0.25*relevance + 0.20*novelty + 0.15*empirical + 0.10*source_signal + 0.10*momentum + 0.10*recency + 0.10*actionability`

각 항목 정의:
- relevance: robot AI / embodied / manipulation 관련성
- novelty: 문제정의, 아키텍처, 학습법의 새로움
- empirical: ablation, baseline, real-robot 여부, 데이터 규모
- source_signal: venue / OpenReview / 저자군 / 구현 공개 여부
- momentum: citation/related papers/커뮤니티 반응의 초기 신호
- recency: 최근성
- actionability: 내가 지금 읽고 활용할 가치

권장 버킷:
- 85+: Must Read
- 70~84: Worth Reading
- 55~69: Skim
- <55: Archive only

## 8. 요약 프롬프트 규격

논문 1편당 출력 포맷:

1. 제목 / 저자 / 날짜 / 링크
2. 한 줄 요약
3. 무엇이 새로운가
4. 핵심 방법
5. 실험과 결과
6. robotics 관점 의미
7. 한계 / 리스크
8. 읽을 가치 점수
9. 다음 액션

제약:
- 초록만 읽은 내용과 본문에서 확인한 내용을 구분
- 수치/표현은 원문에 없는 추정 금지
- novelty는 근거 문장 없으면 보수적으로 기술
- "state-of-the-art" 문구는 인용 근거 있을 때만 사용

## 9. 권장 MCP tool contract

### search_arxiv
입력:
```json
{
  "query": "vision-language-action OR embodied",
  "categories": ["cs.RO", "cs.LG", "cs.AI"],
  "days_back": 10,
  "max_results": 100
}
```

출력:
- Paper[] (metadata only)

### search_openreview
입력:
```json
{
  "venues": ["ICLR.cc/2026/Conference", "robot-learning.org/CoRL/2025/Conference"],
  "keywords": ["manipulation", "policy", "world model"],
  "max_results": 100
}
```

출력:
- Paper[] + review_signal

### enrich_metadata
입력:
```json
{
  "paper_ids": ["arxiv:2604.12345", "doi:10.xxxx/abcd"],
  "providers": ["semanticscholar", "openalex"]
}
```

출력:
- citations, topics, relatedness, venue/source metadata

### summarize_papers
입력:
```json
{
  "paper_ids": ["..."],
  "style": "daily_radar_ko"
}
```

출력:
- structured summaries

### generate_digest
입력:
```json
{
  "scope": "weekly",
  "tracks": ["vla", "manipulation", "world_model", "supporting_ml"],
  "top_k_per_track": 5
}
```

출력:
- Markdown digest

## 10. 일간 실행 흐름

### Stage A. Fetch
- arXiv recent 수집
- OpenReview submission/review 수집
- OpenAlex / Semantic Scholar enrichment

### Stage B. Normalize
- arxiv_id / doi / normalized_title 생성
- source별 필드 정규화

### Stage C. Filter
- 날짜
- 키워드
- robotics relevance
- 제외어 (survey, benchmark-only, position 등 정책 기반 처리)

### Stage D. Dedup
우선순위:
1. DOI
2. arXiv ID
3. exact normalized title
4. near-duplicate title similarity + author overlap

### Stage E. Rank
- lightweight heuristic score
- 상위 N개만 LLM deep summary
- 낮은 점수는 archive

### Stage F. Summarize
- 제목/초록 기반 1차 요약
- PDF method/experiment section 확보 시 2차 보강
- evaluator pass에서 과장/환각 제거

### Stage G. Publish
- markdown 저장
- JSONL 저장
- Slack/Notion/Email 전송 가능

## 11. evaluator 규칙

검증 질문 예:
- novelty 근거가 실제 초록/본문에 있나?
- 결과 수치가 원문과 일치하나?
- real-robot 검증을 했는가, 아니면 simulation only 인가?
- baseline / ablation 언급이 실제로 존재하나?
- "중요"하다고 판단한 근거가 명시되어 있나?

evaluator가 실패시키는 대표 사례:
- 초록만 보고 과장된 결론 도출
- survey와 original research 혼동
- VLA paper인데 robotics 실험이 없는 경우
- 유사 제목 논문 중복 포함

## 12. 주간 리포트 포맷

### Section 1. 이번 주 Top Picks
- 가장 읽을 가치가 큰 5편

### Section 2. VLA / Embodied
- policy, world model, perception-action 결합 논문

### Section 3. Manipulation / Humanoid
- real-robot, dexterous, bimanual 우선

### Section 4. Supporting ML
- diffusion, planning, multimodal reasoning 등 보조 논문

### Section 5. Skip List
- 왜 제외했는지
- 비슷하지만 덜 중요한 논문들

### Section 6. Next Actions
- 직접 읽을 논문
- 구현 실험해볼 논문
- 팀 공유할 논문

## 13. 추천 저장소 구조

```text
paper_radar/
  config/
    config.yaml
    prompts.yaml
  data/
    raw/
    normalized/
    digests/
  src/
    collectors/
      arxiv.py
      openreview.py
      openalex.py
      semanticscholar.py
    ranking/
      rules.py
    summarization/
      prompts.py
      formatter.py
    storage/
      db.py
    runner.py
```

## 14. 최소 MVP 범위

반드시 포함:
- arXiv 수집
- 규칙 기반 relevance filter
- dedup
- 점수화
- 한국어 daily digest 출력

두 번째 단계에 추가:
- Semantic Scholar enrichment
- OpenAlex enrichment
- OpenReview venue tracking
- PDF section parsing
- Slack/Notion export

## 15. 운영 팁

- arXiv는 일별 공백이 생길 수 있으므로 rolling lookback을 쓴다.
- citation count는 최근 논문에서 lag가 크므로 보조 지표로만 쓴다.
- "major paper" 판정은 단일 점수보다 버킷 분류가 더 안정적이다.
- agent autonomy를 높이기 전에 evaluator를 먼저 강화한다.
- 긴 컨텍스트보다 저장된 중간 산출물(JSONL/DB/markdown artifacts)이 더 중요하다.

## 16. 다음에 바로 붙이면 좋은 것

1. Slack/Notion exporter
2. PDF method/experiment 섹션 추출기
3. 개인 선호 학습(예: manipulation > humanoid > general ML)
4. 팀용 shared watchlist