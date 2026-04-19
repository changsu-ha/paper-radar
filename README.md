# Paper Radar Harness

Paper Radar Harness는 최근 논문을 수집하고, 외부 메타데이터를 enrich한 뒤 규칙 기반 점수로 재정렬하고 digest와 비교 화면까지 제공하는 로컬 실험용 도구입니다.

현재 지원 기능:

- `arXiv` 수집
- `OpenReview` 수집
- `Semantic Scholar` enrich
- `OpenAlex` enrich
- rule-based ranking
- OpenAlex affiliation priority catalog 기반 bonus
- track assignment
- daily / weekly digest
- Streamlit GUI
- YAML preset 저장
- config A/B 비교
- SQLite run snapshot 저장

## 구성

- [paper_radar_core.py](./paper_radar_core.py)
  수집, enrich, ranking, digest, SQLite, compare 로직
- [paper_radar_app.py](./paper_radar_app.py)
  Streamlit GUI
- [paper_radar_starter.py](./paper_radar_starter.py)
  CLI entrypoint
- [SEARCH_RULES.md](./SEARCH_RULES.md)
  현재 수집 / enrich / ranking rule 설명
- [configs/README_config.md](./configs/README_config.md)
  주제별 실행 config 묶음 설명
- [configs/README_catalogs.md](./configs/README_catalogs.md)
  OpenAlex affiliation catalog와 scholar bundle 설명
- [tests/test_paper_radar_core.py](./tests/test_paper_radar_core.py)
  코어 테스트
- [tests/test_paper_radar_app.py](./tests/test_paper_radar_app.py)
  GUI helper 테스트

대표 config:

- [configs/robotics.yaml](./configs/robotics.yaml)
- [configs/fundamental_ml.yaml](./configs/fundamental_ml.yaml)
- [configs/optimization_training_dynamics.yaml](./configs/optimization_training_dynamics.yaml)
- [configs/paper_radar_config_outstanding_scholars.yaml](./configs/paper_radar_config_outstanding_scholars.yaml)

## 요구 사항

- Python 3.9+
- 인터넷 연결
- `pip install -r requirements.txt`

필수 패키지:

- `requests`
- `PyYAML`
- `streamlit`
- `pandas`

## venv 설정

### Windows PowerShell

```powershell
cd \\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness

python -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

비활성화:

```powershell
deactivate
```

### WSL

```bash
cd ~/repos/paper_radar_harness

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Ubuntu에서 `venv`가 없으면 먼저 설치합니다.

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip
```

비활성화:

```bash
deactivate
```

## 서버 실행

### Windows PowerShell

```powershell
.venv\Scripts\Activate.ps1
python -m streamlit run paper_radar_app.py --server.port 8501
```

### WSL

```bash
source .venv/bin/activate
python -m streamlit run paper_radar_app.py --server.address 0.0.0.0 --server.port 8501
```

브라우저:

```text
http://localhost:8501
```

백그라운드 실행 예시:

```bash
source .venv/bin/activate
nohup python -m streamlit run paper_radar_app.py --server.address 0.0.0.0 --server.port 8501 > streamlit.log 2>&1 &
```

중지:

```bash
pkill -f "streamlit run paper_radar_app.py"
```

## GUI 사용

기본 실행:

```bash
python -m streamlit run paper_radar_app.py
```

초기 config를 지정해서 열 수도 있습니다.

```bash
python -m streamlit run paper_radar_app.py -- --config-path configs/fundamental_ml.yaml
```

GUI는 아래 위치의 실행용 YAML을 읽습니다.

- `configs/*.yaml`
- `data/gui_presets/*.yaml`

단, `kind: openalex_affiliation_catalog`인 catalog YAML은 메인 selector에 보이지 않습니다. 이 파일들은 `OpenAlex priority catalogs`에서 별도로 선택합니다.

탭 구성:

- `Single Run`
  현재 fetch snapshot 기준 rerank 결과와 논문 상세
- `Track Digest`
  daily digest, weekly track digest preview
- `Compare`
  선택한 YAML A/B의 config diff와 결과 diff

동작 규칙:

- fetch 관련 설정 변경은 `Fetch`를 다시 눌러야 반영됩니다.
- ranking과 digest 관련 설정 변경은 마지막 fetch snapshot에 즉시 재적용됩니다.
- `현재 설정 저장`은 `data/gui_presets/<name>.yaml`에 저장됩니다.
- `OpenAlex self-check` 버튼으로 현재 key / 연결 상태를 sidebar에서 바로 확인할 수 있습니다.

## CLI 사용

기본 실행:

```bash
python paper_radar_starter.py
```

특정 config 사용:

```bash
python paper_radar_starter.py --config-path configs/fundamental_ml.yaml
```

또는 파일명만 넘겨도 `configs/`에서 자동으로 찾습니다.

```bash
python paper_radar_starter.py fundamental_ml.yaml
```

## Config 구조

기본 config 디렉터리는 `configs/`입니다. 기본 실행 시 `configs/robotics.yaml`을 사용합니다.

실행용 config의 주요 섹션:

- `sources.arxiv`
  query, category, 기간, query별 최대 결과 수
- `sources.openreview`
  venue, keyword 기반 추가 수집
- `sources.semanticscholar`
  citation / venue / field enrich
- `sources.openalex`
  citation / topic / OA / institution enrich
- `filters.include_keywords`
  relevance 관련 키워드
- `filters.exclude_keywords`
  hit 시 `archive`
- `ranking.weights`
  최종 점수 가중치
- `ranking.buckets`
  `must_read`, `worth_reading`, `skim`
- `ranking.openalex_priority_catalogs`
  OpenAlex institution 매칭 bonus용 catalog 경로
- `digest.tracks`
  ordered primary track 우선순위
- `digest.track_definitions`
  custom track definition override

예전 YAML에 `llm:` 섹션이 남아 있어도 로드는 되지만, 현재 버전에서는 사용하지 않습니다.

## Catalog와 Scholar Bundle

아래 파일들은 topic preset과 역할이 다릅니다.

- [configs/paper_radar_config_major_universities.yaml](./configs/paper_radar_config_major_universities.yaml)
  OpenAlex affiliation 기준 주요 대학 catalog
- [configs/paper_radar_config_major_research_labs.yaml](./configs/paper_radar_config_major_research_labs.yaml)
  OpenAlex affiliation 기준 주요 연구소 catalog
- [configs/paper_radar_config_outstanding_scholars.yaml](./configs/paper_radar_config_outstanding_scholars.yaml)
  글로벌 + 중국/중국계 scholar를 통합한 실행용 검색 config

catalog 동작 방식:

- OpenAlex enrich가 활성화된 논문에만 적용됩니다.
- 저자 소속 기관이 선택한 catalog entity와 매칭되면 `source_signal` bonus가 붙습니다.
- 이 기능은 `boost only`이며, 매칭되지 않은 논문을 제거하지는 않습니다.

자세한 설명은 [configs/README_catalogs.md](./configs/README_catalogs.md)를 참고하세요.

## GUI 주요 항목 의미

### Fetch 설정

- `days_back`
  최근 며칠 이내 논문만 수집할지 정합니다.
- `max_results_per_query`
  각 query에서 최대 몇 건까지 가져올지 정합니다.
- `arXiv queries`
  줄마다 하나의 query를 넣습니다.
- `categories`
  arXiv category 필터입니다.
- `Semantic Scholar enrich`
  새 논문을 가져오는 기능이 아니라, 이미 수집한 논문에 citation / venue / field 정보를 붙입니다.
- `OpenReview 수집`
  OpenReview venue 기반으로 논문을 추가 수집합니다.
- `OpenAlex enrich`
  새 논문을 가져오는 기능이 아니라, 이미 수집한 논문에 citation / topic / OA / institution 정보를 붙입니다.
- `OpenAlex priority catalogs`
  OpenAlex authorship institution이 catalog와 매칭되면 source signal bonus를 주는 보조 YAML 목록입니다.
- `OpenAlex self-check`
  현재 환경변수, enabled 상태, HTTP 연결 여부를 바로 확인합니다.

### Ranking 설정

- `include_keywords`
  많이 등장할수록 relevance 점수가 올라갑니다.
- `exclude_keywords`
  발견되면 해당 논문은 바로 `archive` 처리됩니다.

weight 의미:

- `weight.relevance`
  관심 주제와의 직접 관련성
- `weight.novelty`
  새 문제 설정, 방법, benchmark, dataset 신호
- `weight.empirical`
  ablation, baseline, simulation, real-world 같은 검증 신호
- `weight.source_signal`
  출처와 메타데이터 품질 신호
- `weight.momentum`
  citation 기반 영향력
- `weight.recency`
  최신성
- `weight.actionability`
  실제로 읽고 적용할 만한 실용성

bucket 의미:

- `bucket.must_read`
  이 점수 이상이면 `must_read`
- `bucket.worth_reading`
  이 점수 이상이면 `worth_reading`
- `bucket.skim`
  이 점수 이상이면 `skim`, 그 아래는 `archive`

### Digest 설정

- `daily_top_k`
  daily digest와 export에 포함할 상위 논문 수
- `weekly_top_k_per_track`
  weekly digest에서 track별로 보여줄 최대 논문 수
- `track order`
  여러 track에 동시에 걸릴 때 primary track 우선순위
- `custom track_definitions`
  기본 track 정의를 덮어쓰는 사용자 정의 YAML

## 출력 파일

기본 출력 위치는 `data/`입니다.

- `data/paper_radar.sqlite3`
  runs, canonical papers, source payloads, run rankings, track assignments
- `data/daily_radar.md`
  daily digest export
- `data/weekly_track_digest.md`
  weekly track digest export
- `data/papers.jsonl`
  최종 snapshot paper dump
- `data/gui_presets/*.yaml`
  GUI에서 저장한 preset
- `data/runtime_warnings.log`
  source/network 경고 로그

## 환경 변수

- `SEMANTIC_SCHOLAR_API_KEY`
- `OPENALEX_API_KEY`
- `PAPER_RADAR_CONFIG`

WSL에서는 `OPENALEX_API_KEY`를 `~/.profile`에 두는 것을 권장합니다. `~/.bashrc`에만 두면 login shell이 아닌 경로에서 보이지 않을 수 있습니다.

예시:

```powershell
$env:SEMANTIC_SCHOLAR_API_KEY = "your_semantic_scholar_key"
python -m streamlit run paper_radar_app.py
```

```bash
export SEMANTIC_SCHOLAR_API_KEY="your_semantic_scholar_key"
python -m streamlit run paper_radar_app.py --server.address 0.0.0.0 --server.port 8501
```

```bash
echo 'export OPENALEX_API_KEY="your_openalex_key"' >> ~/.profile
source ~/.profile
```

## 테스트

실행:

```bash
python -m unittest discover -s tests -v
```

현재 테스트 범위:

- `days_back` cutoff와 arXiv pagination 중단 조건
- exclude keyword archive 처리
- weight normalization
- config roundtrip과 legacy `llm` 무시
- OpenReview metadata / review signal 파싱
- OpenAlex fallback enrichment / self-check / query param 인증
- OpenAlex affiliation catalog bonus
- track assignment / digest
- config compare same-fetch / different-fetch
- merged catalog / scholar config 로드
- old snapshot extra field 호환
- SQLite persistence + export
- rerank 시 네트워크 미호출
- warning / `OSError` 방어
- GUI config discovery / session reset helper

## 문제 해결

### `streamlit: command not found`

대부분 PATH 문제입니다. 아래처럼 실행하면 됩니다.

```bash
python -m streamlit run paper_radar_app.py
```

WSL에서는 Windows에 설치된 `streamlit`을 그대로 쓸 수 없으므로, WSL 안의 `venv`에 따로 설치해야 합니다.

### OpenAlex self-check에서 key가 안 보이는 경우

WSL에서 앱을 띄웠는데 `OPENALEX_API_KEY is not set`가 나오면, 현재 프로세스가 key를 읽지 못한 상태일 가능성이 큽니다.

권장 절차:

```bash
echo 'export OPENALEX_API_KEY="your_openalex_key"' >> ~/.profile
source ~/.profile
python -m streamlit run paper_radar_app.py --server.address 0.0.0.0 --server.port 8501
```

이미 떠 있는 서버가 예전 환경으로 실행된 상태면, 서버를 다시 시작해야 합니다.

### Fetch 중 source 오류가 나도 앱이 계속 도는 이유

source별 partial failure를 허용하도록 되어 있어서, 한 source가 실패해도 가능한 결과를 계속 보여줍니다. 자세한 경고는 `data/runtime_warnings.log`에서 확인할 수 있습니다.
