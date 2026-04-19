# Paper Radar Search Rules

이 문서는 현재 `paper_radar_core.py` 기준으로 Paper Radar가 논문을 찾고, enrich하고, 점수화하는 규칙을 정리한 설명서입니다.

핵심 흐름:

1. config에서 fetch / ranking / digest 옵션을 읽음
2. `arXiv`와 선택적으로 `OpenReview`에서 논문 수집
3. 선택적으로 `Semantic Scholar`, `OpenAlex`로 metadata enrich
4. dedup 및 metadata merge
5. track assignment
6. rule-based ranking
7. bucket 분류 및 digest 생성

주요 코드 위치:

- fetch option 파싱: [paper_radar_core.py](./paper_radar_core.py#L650)
- ranking option 파싱: [paper_radar_core.py](./paper_radar_core.py#L673)
- arXiv 수집: [paper_radar_core.py](./paper_radar_core.py#L1020)
- OpenReview 수집: [paper_radar_core.py](./paper_radar_core.py#L1162)
- OpenAlex priority match: [paper_radar_core.py](./paper_radar_core.py#L1587)
- ranking: [paper_radar_core.py](./paper_radar_core.py#L1637)

## Flow Chart

```text
[Config YAML / GUI 입력]
        |
        +--> [Fetch Options 구성]
        |         |
        |         +--> [arXiv 수집]
        |         |
        |         +--> [OpenReview 수집 (선택)]
        |                    |
        |                    +--> decision / review_signal 생성 가능
        |         |
        |         +--> [초기 논문 pool]
        |                    |
        |                    +--> [1차 dedup / metadata merge]
        |                                  |
        |                                  +--> [Semantic Scholar enrich (선택)]
        |                                  |
        |                                  +--> [OpenAlex enrich (선택)]
        |                                                 |
        |                                                 +--> citation / topic / OA / institutions
        |                                  |
        |                                  +--> [2차 dedup / metadata merge]
        |
        +--> [Rank Options 구성]
        |
        +--> [Digest Options 구성]
                      |
                      v
              [Track assignment]
                      |
                      v
              [Rule-based ranking]
                      |
                      +--> relevance
                      +--> novelty
                      +--> empirical
                      +--> source_signal
                      |      |
                      |      +--> OpenReview decision / review_signal 반영
                      |      +--> OpenAlex priority catalog match bonus 반영
                      |
                      +--> momentum
                      +--> recency
                      +--> actionability
                      |
                      v
                 [Final Score]
                      |
                      v
                 [Bucket 분류]
                      |
        +-------------+-------------+
        |             |             |
        v             v             v
[Daily/Weekly]   [GUI 결과 테이블] [SQLite snapshot / export]
```

## 1. 입력 규칙

실행용 config에서 아래 항목을 읽습니다.

- `sources.arxiv.queries`
- `sources.arxiv.categories`
- `sources.arxiv.days_back_daily`
- `sources.arxiv.max_results_per_query`
- `sources.openreview.*`
- `sources.semanticscholar.*`
- `sources.openalex.*`
- `filters.include_keywords`
- `filters.exclude_keywords`
- `ranking.weights`
- `ranking.buckets`
- `ranking.openalex_priority_catalogs`
- `digest.tracks`
- `digest.track_definitions`

키워드 입력은 소문자 정규화 + 중복 제거를 거칩니다.

- 문자열이면 `,` 또는 줄바꿈 기준 분리
- 공백 제거
- lower-case 변환
- 중복 제거

코드:

- keyword 파싱: [paper_radar_core.py](./paper_radar_core.py#L609)
- weight 정규화: [paper_radar_core.py](./paper_radar_core.py#L625)

## 2. arXiv 수집 규칙

arXiv는 public Atom feed를 사용합니다.

실제 검색식 구성:

- query는 `sources.arxiv.queries`를 그대로 사용
- category가 있으면 `cat:<category>`들을 OR로 묶어 뒤에 붙임
- 최종 형태는 대략 `(<query>) AND (cat:a OR cat:b ...)`

수집 규칙:

- 정렬 기준: `submittedDate desc`
- cutoff: `now - days_back`
- query별로 페이지를 돌며 최근 논문만 유지
- `max_results_per_query`에 도달하면 중단
- 페이지 결과가 부족하면 중단
- 현재 페이지에 cutoff 이내 논문이 하나도 없으면 중단

즉, 각 query에 대해 "최근순으로 가져오되 기간 밖 논문이 나오면 빠르게 멈추는" 구조입니다.

코드:

- search entrypoint: [paper_radar_core.py](./paper_radar_core.py#L1027)
- page query: [paper_radar_core.py](./paper_radar_core.py#L1071)

## 3. OpenReview 수집 규칙

`sources.openreview.enabled=true`일 때만 동작합니다.

수집 방식:

- venue별로 `.../-/Blind_Submission`
- 실패 시 `.../-/Submission`
- `details=directReplies`로 review/decision reply까지 포함해 조회

필터 규칙:

- `published_at` 또는 `updated_at`이 cutoff 안에 있어야 함
- `openreview_keywords`가 있으면 제목/초록/키워드 텍스트에 하나 이상 포함되어야 함

OpenReview에서 추가로 추출하는 값:

- `decision`
- `review_signal`
- `review_count`

코드:

- venue 수집: [paper_radar_core.py](./paper_radar_core.py#L1167)
- note -> paper 변환: [paper_radar_core.py](./paper_radar_core.py#L1233)
- review signal 계산: [paper_radar_core.py](./paper_radar_core.py#L1281)

## 4. enrich 규칙

### Semantic Scholar enrich

목적:

- citation
- venue
- field of study
- DOI
- OA PDF

동작:

- 논문 제목으로 검색
- 반환 후보 중 제목이 충분히 비슷한 첫 결과만 사용
- 맞지 않는 상위 결과는 버림

코드:

- client: [paper_radar_core.py](./paper_radar_core.py#L1290)
- title 호환성 검사: [paper_radar_core.py](./paper_radar_core.py#L545)

### OpenAlex enrich

목적:

- citation
- venue
- topic / concepts
- OA 정보
- authorship institutions

조회 순서:

1. DOI
2. arXiv id
3. `title.search`
4. full-text `search`

후보 선택 규칙:

- 각 query 결과를 순서대로 훑음
- 제목이 충분히 비슷한 첫 결과만 채택
- 엉뚱한 논문 metadata가 붙는 것을 막기 위해 제목 호환성 검사를 통과해야 함

코드:

- OpenAlex client: [paper_radar_core.py](./paper_radar_core.py#L1370)
- candidate query 순서: [paper_radar_core.py](./paper_radar_core.py#L1424)
- title 호환성 검사: [paper_radar_core.py](./paper_radar_core.py#L545)

## 5. dedup 및 merge 규칙

dedup key 우선순위:

1. DOI
2. arXiv id
3. OpenReview forum id
4. normalized title + author signature

source 우선순위:

- `openreview > arxiv > openalex > semanticscholar`

merge 규칙:

- 더 긴 abstract/title 우선
- citation은 max
- decision/review_signal/review_count는 흡수
- topics/categories/authors는 합집합
- `source_metadata`는 merge

코드:

- canonical key: [paper_radar_core.py](./paper_radar_core.py#L850)
- deduplicate: [paper_radar_core.py](./paper_radar_core.py#L903)
- merge: [paper_radar_core.py](./paper_radar_core.py#L951)

## 6. track assignment 규칙

track assignment는 ranking 전에 수행됩니다.

텍스트 구성:

- title
- abstract
- categories
- topics
- venue
- decision
- `track_ids`
- `source_metadata` 전체 JSON

각 track의 keyword 중 하나라도 포함되면 해당 track에 매칭됩니다.

특징:

- multi-label 허용
- `digest.tracks` 순서가 primary track 우선순위
- 아무것도 안 맞으면 `unassigned`

코드:

- track assignment: [paper_radar_core.py](./paper_radar_core.py#L2159)
- 내부 텍스트 생성: [paper_radar_core.py](./paper_radar_core.py#L2567)

## 7. ranking 규칙

weight는 모두 양수화한 뒤 정규화합니다.

- 합이 1이 아니면 자동 정규화
- 전부 0 이하이면 7개 축에 균등 분배

코드:

- weight normalization: [paper_radar_core.py](./paper_radar_core.py#L625)

### 7.1 Relevance

규칙:

- `include_keywords` hit 수 × `12.5`
- 최대 100
- `cs.RO` category면 `+20`
- `primary_track`가 있고 `unassigned`가 아니면 `+10`

즉, "관심 키워드 hit + 로보틱스 카테고리 + primary track" 기반 점수입니다.

### 7.2 Novelty

아래 표현이 텍스트에 들어 있으면 각 `+10`:

- `we propose`
- `introduce`
- `novel`
- `new benchmark`
- `new dataset`
- `first`
- `generalist`
- `foundation model`
- `vision-language-action`
- `world model`

최대 100입니다.

### 7.3 Empirical

아래 표현이 텍스트에 들어 있으면 각 `+8`:

- `real robot`
- `real-world`
- `ablation`
- `baseline`
- `simulation`
- `hardware`
- `policy`
- `dataset`
- `benchmark`

최대 100입니다.

### 7.4 Source Signal

규칙:

- arXiv metadata가 있으면 `+20`
- OpenReview metadata가 있으면 `+20`
- `decision`에 `accept`가 있으면 `+20`
- `review_signal`이 있으면 `+min(30, review_signal * 0.3)`
- OpenAlex `is_oa=True`면 `+5`
- `venue`가 있으면 `+5`
- 텍스트에 `benchmark` 또는 `dataset`이 있으면 `+5`
- OpenAlex priority catalog match가 있으면 `+25`

상한은 100입니다.

priority bonus 상수:

- `OPENALEX_PRIORITY_BONUS = 25.0`

코드:

- source signal 계산: [paper_radar_core.py](./paper_radar_core.py#L1726)

### 7.5 Momentum

규칙:

- citation이 없으면 `0`
- citation이 있으면 `log1p(citations) * 20`
- 최대 100

### 7.6 Recency

규칙:

- `100 - 3 * 경과일수`
- floor는 0
- 날짜가 없으면 20

즉, 매우 최신 논문일수록 유리하고, 하루당 3점씩 감소합니다.

코드:

- recency: [paper_radar_core.py](./paper_radar_core.py#L1758)

### 7.7 Actionability

아래 표현이 텍스트에 들어 있으면 각 `+12.5`:

- `manipulation`
- `policy`
- `robot`
- `embodied`
- `visuomotor`
- `humanoid`
- `vla`
- `world model`
- `alignment`
- `reward model`

최대 100입니다.

## 8. exclude keyword 규칙

`exclude_keywords`가 하나라도 텍스트에 hit하면:

- `final_score = 0`
- `bucket = archive`

즉, ranking 축을 모두 계산하기 전에 hard filter처럼 동작합니다.

코드:

- exclude 처리: [paper_radar_core.py](./paper_radar_core.py#L1708)

## 9. 최종 점수 계산

최종 점수:

```text
final_score =
  w_relevance * relevance_score +
  w_novelty * novelty_score +
  w_empirical * empirical_score +
  w_source_signal * source_signal_score +
  w_momentum * momentum_score +
  w_recency * recency_score +
  w_actionability * actionability_score
```

결과는 소수 둘째 자리로 반올림됩니다.

코드:

- final score: [paper_radar_core.py](./paper_radar_core.py#L1714)

## 10. bucket 규칙

최종 점수로 bucket을 정합니다.

- `must_read >= ranking.buckets.must_read`
- `worth_reading >= ranking.buckets.worth_reading`
- `skim >= ranking.buckets.skim`
- 그 아래는 `archive`

코드:

- bucket 결정: [paper_radar_core.py](./paper_radar_core.py#L1749)

## 11. OpenAlex priority catalog 규칙

priority catalog는 filter가 아니라 bonus입니다.

동작:

- `ranking.openalex_priority_catalogs`에 지정된 YAML들을 로드
- OpenAlex `authorships[].institutions`와 비교
- match 순서:
  1. `openalex_ids` exact match
  2. normalized `display_name` vs `label/aliases`

match가 하나라도 있으면:

- `matched_priority_entities`에 기록
- `source_signal +25`

GUI table의 `priority_match`는 이 `matched_priority_entities`에서 label만 꺼내 보여줍니다.

코드:

- catalog match: [paper_radar_core.py](./paper_radar_core.py#L1587)
- record export: [paper_radar_core.py](./paper_radar_core.py#L819)

## 12. GUI에서 보이는 주요 필드

결과 테이블의 대표 필드:

- `title`
- `final_score`
- `bucket`
- `primary_track`
- `published_at`
- `categories`
- `citations`
- `source`
- `venue`
- `decision`
- `review_signal`
- `priority_match`

record 변환:

- [paper_radar_core.py](./paper_radar_core.py#L819)

상세 보기에서 추가로 보이는 값:

- keyword hit
- score breakdown
- OpenAlex priority matches 상세

## 13. 현재 rule의 성격

이 rule은 전반적으로 아래 성격을 가집니다.

- fetch는 recall 위주
- ranking은 heuristic 위주
- catalog는 boost only
- track는 ranking 전에 붙어서 relevance에 간접 영향
- `source_metadata` 전체가 `_paper_text`에 포함되므로, enrich된 topic / venue / decision도 keyword hit에 영향을 줄 수 있음

즉, "정교한 학습 기반 ranking"이 아니라 "search query + metadata enrich + 가중치 기반 scoring" 구조입니다.
