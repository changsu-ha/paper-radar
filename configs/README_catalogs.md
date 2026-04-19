# Paper Radar Catalogs

이 문서는 `configs/` 아래의 entity catalog와 scholar bundle을 정리한 안내서입니다.  
주제별 실행 config는 `README_config.md`를 참고하세요.

## 파일 역할

### 1. OpenAlex affiliation catalog

- `paper_radar_config_major_universities.yaml`
- `paper_radar_config_major_research_labs.yaml`

이 두 파일은 실행용 검색 preset이 아닙니다.  
`kind: openalex_affiliation_catalog` 스키마를 사용하는 보조 catalog이며, OpenAlex authorship institution metadata와 매칭해 `source_signal` bonus를 주는 데 사용합니다.

특징:

- GUI 메인 config selector에는 표시되지 않습니다.
- GUI의 `OpenAlex priority catalogs`에서 선택해서 사용합니다.
- config에서도 `ranking.openalex_priority_catalogs`로 직접 지정할 수 있습니다.
- `sources.openalex.enabled: true` 상태에서 fetch한 논문에만 실제 기관 매칭이 적용됩니다.

예시:

```yaml
ranking:
  openalex_priority_catalogs:
    - configs/paper_radar_config_major_universities.yaml
    - configs/paper_radar_config_major_research_labs.yaml
```

주의:

- 이 기능은 `boost only`입니다. 매칭되지 않은 논문을 제거하지는 않습니다.
- OpenAlex metadata가 없는 기존 snapshot에는 bonus가 붙지 않으므로, catalog를 새로 선택한 뒤에는 다시 fetch하는 것이 안전합니다.

### 2. 실행용 scholar config

- `paper_radar_config_outstanding_scholars.yaml`

이 파일은 직접 선택해서 실행하는 검색 config입니다.  
기존 citation-led scholars preset과 China-enhanced scholar 목록을 하나로 통합한 버전입니다.

포함 내용:

- 글로벌 high-impact scholar seed list
- 중국 및 중국계 high-impact scholar seed list
- 통합된 `search_aliases`, `focus`, citation snapshot metadata
- merged scholar 목록 기준으로 재구성된 arXiv author query
- China-related keyword와 `china_ai_watch` track

## 이번 통합에서 정리된 내용

- 기존 China 전용 entity 변형 파일들은 각 통합 catalog / scholar config 안으로 흡수했습니다.
- 기관 catalog 문서와 China-specific README도 이 문서 하나로 합쳤습니다.

## GUI에서 쓰는 방법

1. 메인 config selector에서 실행용 config를 선택합니다.
   - 예: `paper_radar_config_outstanding_scholars.yaml`
2. 필요하면 `OpenAlex priority catalogs`에서 대학 / 연구소 catalog를 추가로 선택합니다.
3. `OpenAlex enrich`를 켠 뒤 fetch합니다.
4. 결과 상세에서 OpenAlex institution match가 잡히면 matched catalog/entity 이유가 함께 표시됩니다.
