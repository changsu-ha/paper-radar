# Paper Radar Harness

ML / Robot AI 논문을 최근 기간 기준으로 수집하고, 키워드 및 규칙 기반 점수로 정렬한 뒤, CLI 또는 Streamlit GUI에서 빠르게 실험할 수 있는 로컬 하네스입니다.

현재 버전은 다음 흐름에 초점을 둡니다.

- arXiv에서 최근 논문 수집
- 선택적으로 Semantic Scholar 메타데이터 enrich
- `include_keywords`, `exclude_keywords`, ranking weights, bucket threshold 조정
- 결과를 표로 보고 즉시 rerank
- Markdown / JSONL export

## 주요 기능

- Streamlit GUI
  - 검색 기간, query, 카테고리, 최대 결과 수 조정
  - `include_keywords`, `exclude_keywords`, ranking weights, bucket 조정
  - `Fetch` 이후에는 네트워크 재호출 없이 rerank 즉시 반영
  - preset 저장 / 불러오기
- CLI 실행
  - 설정 파일 기준으로 fetch -> enrich -> rank -> export
- 코어 모듈 분리
  - fetch / enrich / rank / export를 재사용 가능한 API로 제공
- 테스트 포함
  - `days_back`, weight 정규화, preset roundtrip, mock HTTP 파이프라인 검증

## 저장소 구조

- [paper_radar_core.py](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\paper_radar_core.py:1>)
  핵심 데이터 모델과 fetch / enrich / rank / export 로직
- [paper_radar_app.py](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\paper_radar_app.py:1>)
  Streamlit GUI
- [paper_radar_starter.py](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\paper_radar_starter.py:1>)
  CLI entrypoint
- [paper_radar_config.example.yaml](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\paper_radar_config.example.yaml:1>)
  기본 설정 예제
- [paper_radar_prompts.example.yaml](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\paper_radar_prompts.example.yaml:1>)
  향후 요약 프롬프트용 예제
- [tests/test_paper_radar_core.py](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\tests\test_paper_radar_core.py:1>)
  핵심 테스트
- `data/`
  실행 결과, preset, warning log 저장

## 요구 사항

- Python 3.9+
- 인터넷 연결
- `pip install -r requirements.txt`

의존성:

- `requests`
- `PyYAML`
- `streamlit`
- `pandas`

## 빠른 시작

### GUI 실행

가장 안전한 실행 방식은 아래입니다.

```bash
python -m streamlit run paper_radar_app.py
```

브라우저에서 `http://localhost:8501` 로 접속합니다.

다른 config 파일로 실행하려면:

```bash
python -m streamlit run paper_radar_app.py -- --config-path paper_radar_config_fundamental_ml.yaml
```

GUI 사용 흐름:

1. 왼쪽 사이드바에서 fetch 설정을 조정합니다.
2. `Fetch` 버튼으로 arXiv 수집과 optional enrich를 실행합니다.
3. ranking 설정을 바꾸면 현재 fetch 결과에 즉시 rerank가 반영됩니다.
4. 필요하면 `Export 현재 결과`로 `data/`에 저장합니다.
5. 현재 설정을 preset으로 저장할 수 있습니다.

### CLI 실행

```bash
python paper_radar_starter.py
```

CLI는 [paper_radar_config.example.yaml](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\paper_radar_config.example.yaml:1>) 기준으로 실행한 뒤 결과를 `data/`에 저장합니다.

다른 config 파일로 실행하려면:

```bash
python paper_radar_starter.py --config-path paper_radar_config_fundamental_ml.yaml
```

또는 위치 인자로도 가능합니다.

```bash
python paper_radar_starter.py paper_radar_config_fundamental_ml.yaml
```

## 가상환경(venv) 설정

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

Ubuntu에 `venv`가 없다면 먼저 설치합니다.

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip
```

비활성화:

```bash
deactivate
```

## 서버 실행

### Windows PowerShell에서 실행

`streamlit` 명령이 PATH에 없을 수 있으므로 아래 방식을 권장합니다.

```powershell
.venv\Scripts\Activate.ps1
python -m streamlit run paper_radar_app.py --server.port 8501
```

### WSL에서 실행

WSL에서는 Windows에 설치된 `streamlit`을 그대로 쓰지 못하므로, WSL 안의 venv를 활성화한 뒤 실행합니다.

```bash
source .venv/bin/activate
python -m streamlit run paper_radar_app.py --server.address 0.0.0.0 --server.port 8501
```

Windows 브라우저에서는 다음 주소로 접속합니다.

```text
http://localhost:8501
```

### 백그라운드 실행 예시

WSL에서 세션을 유지하며 띄우고 싶다면:

```bash
source .venv/bin/activate
nohup python -m streamlit run paper_radar_app.py --server.address 0.0.0.0 --server.port 8501 > streamlit.log 2>&1 &
```

중지:

```bash
pkill -f "streamlit run paper_radar_app.py"
```

## 설정 파일

기본 설정 파일은 [paper_radar_config.example.yaml](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\paper_radar_config.example.yaml:1>) 입니다.

주요 항목:

- `sources.arxiv.categories`
  arXiv 검색 카테고리
- `sources.arxiv.queries`
  arXiv 검색 query 목록
- `sources.arxiv.days_back_daily`
  최근 며칠 내 논문만 반영할지 결정
- `sources.arxiv.max_results_per_query`
  query별 최대 수집 수
- `sources.semanticscholar.enabled`
  Semantic Scholar 메타데이터 enrich 사용 여부
- `filters.include_keywords`
  relevance 계산에 사용되는 포함 키워드
- `filters.exclude_keywords`
  hit 시 바로 `archive` 처리되는 제외 키워드
- `ranking.weights`
  최종 점수 가중치
- `ranking.buckets`
  `must_read`, `worth_reading`, `skim` 경계값
- `digest.daily_top_k`
  export 시 Markdown digest 상위 개수

## GUI 동작 규칙

- fetch 관련 설정
  - `days_back`
  - queries
  - categories
  - `max_results_per_query`
  - Semantic Scholar on/off
- ranking 관련 설정
  - `include_keywords`
  - `exclude_keywords`
  - weights
  - buckets
  - `daily_top_k`

중요한 동작:

- fetch 관련 설정을 바꾸면 기존 결과는 유지되고, 화면에 “재조회 필요” 상태만 표시됩니다.
- 실제 데이터 반영은 `Fetch` 버튼을 다시 눌렀을 때만 일어납니다.
- ranking 관련 설정은 마지막 fetch 결과에 즉시 재적용됩니다.
- weight 합이 1.0이 아니면 양수 합 기준으로 자동 정규화됩니다.
- preset 저장 시 예제 config 파일은 덮어쓰지 않고 `data/gui_presets/*.yaml`에 저장됩니다.

## 출력 파일

기본 출력 위치는 `data/`입니다.

- [data/daily_radar.md](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\data\daily_radar.md:1>)
  상위 논문 Markdown digest
- [data/papers.jsonl](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\data\papers.jsonl:1>)
  논문별 전체 메타데이터와 점수
- [data/runtime_warnings.log](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\data\runtime_warnings.log:1>)
  네트워크 / 파싱 경고 로그
- `data/gui_presets/*.yaml`
  GUI에서 저장한 preset

## 코어 API

`paper_radar_core.py`는 아래 API를 제공합니다.

```python
fetch_papers(fetch_options) -> list[Paper]
enrich_papers(papers, fetch_options, env=None) -> list[Paper]
rank_papers(papers, rank_options) -> list[Paper]
build_markdown_digest(papers, top_k=8) -> str
export_results(papers, out_dir, top_k) -> None
```

옵션 dataclass:

```python
FetchOptions(
    queries: list[str],
    categories: list[str],
    days_back: int,
    max_results_per_query: int,
    enable_semanticscholar: bool,
)

RankOptions(
    include_keywords: list[str],
    exclude_keywords: list[str],
    weights: dict[str, float],
    buckets: dict[str, float],
    daily_top_k: int,
)
```

## 테스트

실행:

```bash
python -m unittest discover -s tests -v
```

포함된 검증:

- `days_back` cutoff 동작
- query pagination 중단 조건
- `exclude_keywords` hit 시 `archive`
- weight 자동 정규화
- preset YAML roundtrip
- mock HTTP 기반 fetch -> enrich -> rank -> export
- rerank 시 네트워크 미호출
- `stderr` / OS-level 네트워크 오류 내구성

## 환경 변수

선택 사항:

- `SEMANTIC_SCHOLAR_API_KEY`

예제 config에서는 Semantic Scholar가 활성화되어 있습니다. API 키 없이도 동작할 수 있지만 rate limit 또는 네트워크 오류가 날 수 있으므로, 안정적으로 쓰려면 환경 변수를 설정하는 편이 낫습니다.

PowerShell 예시:

```powershell
$env:SEMANTIC_SCHOLAR_API_KEY = "your_api_key"
python -m streamlit run paper_radar_app.py
```

WSL 예시:

```bash
export SEMANTIC_SCHOLAR_API_KEY="your_api_key"
python -m streamlit run paper_radar_app.py --server.address 0.0.0.0 --server.port 8501
```

## 문제 해결

### `streamlit: command not found`

설치는 되어 있어도 실행 파일 경로가 PATH에 없을 수 있습니다. 가장 안전한 방식은 아래입니다.

```bash
python -m streamlit run paper_radar_app.py
```

WSL에서는 Windows에 설치된 `streamlit`을 사용할 수 없으므로, WSL 안에서 별도 venv를 만들고 설치해야 합니다.

### Fetch 중 오류가 나지만 앱은 살아 있음

이 프로젝트는 네트워크 오류가 나더라도 GUI가 죽지 않도록 처리합니다. 자세한 원인은 [data/runtime_warnings.log](<\\?\UNC\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness\data\runtime_warnings.log:1>)를 확인하면 됩니다.

### 결과가 비어 있음

다음을 확인하세요.

- `days_back`가 너무 짧지 않은지
- query가 너무 좁지 않은지
- 카테고리 조합이 너무 제한적이지 않은지
- 네트워크 연결 또는 외부 API 응답 상태

### 가중치가 이상하게 보임

GUI는 입력된 weight 합이 1.0이 아니면 자동 정규화를 적용합니다. 화면에 현재 합계와 정규화 적용 여부가 표시됩니다.

## 현재 범위와 한계

- 현재 실제로 연결된 수집 소스는 arXiv입니다.
- OpenReview / OpenAlex / LLM summary UI는 아직 구현 범위 밖입니다.
- ranking은 규칙 기반이며, LLM evaluator는 아직 사용하지 않습니다.
- GUI는 로컬 개인 사용을 전제로 합니다.

## 향후 확장 아이디어

- OpenReview / OpenAlex 수집 연결
- 논문 요약 및 evaluator 단계 통합
- track별 digest 뷰
- 설정 A/B 비교 UI
- preset별 결과 diff
