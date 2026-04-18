# Paper Radar Harness

Paper Radar는 최근 논문을 수집하고, 규칙 기반 랭킹과 선택적 LLM 요약/검증을 거쳐, Streamlit GUI에서 빠르게 탐색할 수 있게 만든 로컬 실험용 하네스입니다.

현재 버전은 아래를 포함합니다.

- `arXiv` 수집
- `OpenReview` 수집
- `Semantic Scholar`, `OpenAlex` enrich
- rule-based ranking
- `OpenAI` 기반 summary / evaluator
- track assignment + daily / weekly digest
- preset 저장 / 로드
- preset A/B compare + 결과 diff
- `SQLite` run/paper snapshot 저장

## 구성

- [paper_radar_core.py](./paper_radar_core.py)
  수집, enrich, ranking, summary/evaluator, digest, SQLite 저장, compare 로직
- [paper_radar_app.py](./paper_radar_app.py)
  Streamlit GUI
- [paper_radar_starter.py](./paper_radar_starter.py)
  CLI entrypoint
- [paper_radar_config.example.yaml](./paper_radar_config.example.yaml)
  기본 config
- [paper_radar_config_fundamental_ml.yaml](./paper_radar_config_fundamental_ml.yaml)
  fundamental ML 예제 config
- [paper_radar_prompts.example.yaml](./paper_radar_prompts.example.yaml)
  summary / evaluator prompt 예제
- [tests/test_paper_radar_core.py](./tests/test_paper_radar_core.py)
  핵심 로직 테스트

## 요구 사항

- Python 3.9+
- 인터넷 연결
- `pip install -r requirements.txt`

의존성:

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

브라우저에서:

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

## GUI 실행

기본 실행:

```bash
python -m streamlit run paper_radar_app.py
```

다른 config 사용:

```bash
python -m streamlit run paper_radar_app.py -- --config-path paper_radar_config_fundamental_ml.yaml
```

GUI 탭:

- `Single Run`
  현재 fetch snapshot 기준 rerank 결과, 상세 점수, summary/evaluator 상태
- `Track Digest`
  daily digest, weekly track digest preview
- `Compare`
  preset A/B config diff와 결과 diff

세션 규칙:

- fetch 관련 설정 변경은 화면에만 반영되고, 실제 원격 조회는 `Fetch`를 눌렀을 때만 일어납니다.
- ranking 관련 설정 변경은 마지막 fetch snapshot에 즉시 재적용됩니다.
- LLM summary/evaluator는 fetch 시점에만 새로 실행됩니다.

## CLI 실행

기본 실행:

```bash
python paper_radar_starter.py
```

다른 config 사용:

```bash
python paper_radar_starter.py --config-path paper_radar_config_fundamental_ml.yaml
```

또는:

```bash
python paper_radar_starter.py paper_radar_config_fundamental_ml.yaml
```

CLI와 GUI 모두 run 결과를 SQLite에 저장하고, 필요 시 `data/`로 export합니다.

## 설정 파일

주요 섹션:

- `sources.arxiv`
  query, category, 기간, query별 최대 결과 수
- `sources.openreview`
  venue, keyword 기반 수집
- `sources.semanticscholar`
  citation / venue / field enrich
- `sources.openalex`
  citation / topic / OA enrich
- `filters.include_keywords`
  relevance 관련 키워드
- `filters.exclude_keywords`
  hit 시 `archive`
- `ranking.weights`
  최종 점수 가중치
- `ranking.buckets`
  `must_read`, `worth_reading`, `skim`
- `digest.tracks`
  ordered primary track 우선순위
- `digest.track_definitions`
  custom track definition override
- `llm`
  summary/evaluator 모델, top-n, prompt path 설정

weight 합계가 1.0이 아니면 scoring 직전에 양수 합 기준으로 자동 정규화됩니다.

## 저장소와 출력

기본 저장 위치는 `data/`입니다.

- `data/paper_radar.sqlite3`
  runs, canonical papers, source payloads, run rankings, summaries, evaluations, track assignments
- `data/daily_radar.md`
  daily digest export
- `data/weekly_track_digest.md`
  weekly track digest export
- `data/papers.jsonl`
  최종 snapshot paper dump
- `data/gui_presets/*.yaml`
  GUI에서 저장한 preset
- `data/runtime_warnings.log`
  source/LLM/network 경고 로그

## 환경 변수

- `SEMANTIC_SCHOLAR_API_KEY`
- `OPENAI_API_KEY`
- `PAPER_RADAR_CONFIG`

예시:

```powershell
$env:SEMANTIC_SCHOLAR_API_KEY = "your_semantic_scholar_key"
$env:OPENAI_API_KEY = "your_openai_key"
python -m streamlit run paper_radar_app.py
```

```bash
export SEMANTIC_SCHOLAR_API_KEY="your_semantic_scholar_key"
export OPENAI_API_KEY="your_openai_key"
python -m streamlit run paper_radar_app.py --server.address 0.0.0.0 --server.port 8501
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
- preset YAML roundtrip
- OpenReview metadata / review signal 파싱
- OpenAlex fallback enrichment
- summary/evaluator top-n 적용
- track assignment / digest
- preset compare same-fetch / different-fetch
- SQLite persistence + export
- rerank 시 네트워크 미호출
- warning / OSError 방어

## 문제 해결

### `streamlit: command not found`

대부분 PATH 문제입니다. 아래처럼 실행하면 됩니다.

```bash
python -m streamlit run paper_radar_app.py
```

WSL에서는 Windows에 설치된 `streamlit`을 그대로 쓸 수 없으니 WSL 안의 venv에 따로 설치해야 합니다.

### Fetch 중 source 오류가 났는데 앱은 계속 뜸

source별 partial failure는 앱 전체 실패로 올리지 않고 경고만 남깁니다. 자세한 내용은 `data/runtime_warnings.log`를 보면 됩니다.

### Compare 탭에 결과가 비어 있음

비교 대상 preset으로 최소 한 번씩 `Fetch`를 실행해서 run snapshot을 SQLite에 남겨야 합니다.

## 현재 범위

- 배포 대상은 로컬 단일 사용자입니다.
- 수집 source 실패는 partial failure로 처리합니다.
- ranking은 rule-based입니다.
- summary/evaluator는 OpenAI API 키가 있을 때만 동작합니다.
- A/B compare는 preset 중심이며, 같은 fetch signature면 같은 raw corpus 재랭킹 비교를 우선합니다.
