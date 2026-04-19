# paper-radar entity-centric presets

생성일: 2026-04-18

포함 파일:
- `paper_radar_config_major_universities.yaml`
- `paper_radar_config_major_research_labs.yaml`
- `paper_radar_config_outstanding_scholars.yaml`

## 전달 메모

이 preset들은 현재 repo의 arXiv collector가 `sources.arxiv.queries` 문자열을 그대로 검색식으로 전달하는 구조를 전제로 작성했습니다.
그래서 affiliation 검색보다는 `au:"Author Name"` 형태의 author query와 proxy author 구성을 중심으로 설계했습니다.

구성 방식:
- 대학 preset: 소속 기관별 proxy authors
- 연구소 preset: 기관별 proxy authors
- 학자 preset: citation-led scholar set

## OpenAlex

세 preset 모두 `sources.openalex.enabled: true`로 설정되어 있습니다.
WSL에서 안정적으로 쓰려면 `OPENALEX_API_KEY`를 `~/.profile`에 두는 것을 권장합니다.

예시:

```bash
echo 'export OPENALEX_API_KEY="your_openalex_key"' >> ~/.profile
source ~/.profile
```

GUI에서는 sidebar의 `OpenAlex self-check` 버튼으로 연결 상태를 확인할 수 있습니다.

## 사용 예시

```bash
python paper_radar_starter.py --config-path configs/paper_radar_config_major_universities.yaml
python paper_radar_starter.py --config-path configs/paper_radar_config_major_research_labs.yaml
python paper_radar_starter.py --config-path configs/paper_radar_config_outstanding_scholars.yaml
```

## 추천

- 기관/랩 중심 모니터링: `major_universities`, `major_research_labs`
- citation-driven scholar watchlist: `outstanding_scholars`
- 더 넓은 recall이 필요하면 `days_back_daily`, `max_results_per_query`를 조금 더 올리는 편이 자연스럽습니다.
- strict affiliation search가 꼭 필요하면 arXiv-only 접근보다는 affiliation-aware source를 collector에 추가하는 편이 맞습니다.
