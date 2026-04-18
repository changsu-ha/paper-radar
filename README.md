# Paper Radar Harness

Paper Radar Harness는 최근 논문을 수집하고, 규칙 기반으로 점수를 매기고, track별 digest와 preset 비교를 로컬에서 빠르게 실험하기 위한 도구입니다.

현재 범위:

- `arXiv` 수집
- `OpenReview` 수집
- `Semantic Scholar`, `OpenAlex` enrich
- rule-based ranking
- track assignment + daily / weekly digest
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
- [paper_radar_config.example.yaml](./paper_radar_config.example.yaml)
  기본 robotics config
- [paper_radar_config_fundamental_ml.yaml](./paper_radar_config_fundamental_ml.yaml)
  fundamental ML 예제 config
- [tests/test_paper_radar_core.py](./tests/test_paper_radar_core.py)
  코어 테스트
- [tests/test_paper_radar_app.py](./tests/test_paper_radar_app.py)
  GUI helper 테스트

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
python -m streamlit run paper_radar_app.py -- --config-path paper_radar_config_fundamental_ml.yaml
```

하지만 GUI 자체는 시작 인자에 고정되지 않습니다. 사이드바에서 다음 YAML을 드롭다운으로 선택하고 `불러오기` 할 수 있습니다.

- repo 루트의 `paper_radar_config*.yaml`
- `data/gui_presets/*.yaml`

GUI 탭:

- `Single Run`
  현재 fetch snapshot 기준 rerank 결과와 논문 상세
- `Track Digest`
  daily digest, weekly track digest preview
- `Compare`
  선택한 YAML A/B의 config diff와 결과 diff

동작 규칙:

- fetch 관련 설정 변경은 `Fetch`를 다시 눌러야 반영됩니다.
- ranking과 digest 관련 설정 변경은 마지막 fetch snapshot에 즉시 재적용됩니다.
- `현재 설정 저장`은 `data/gui_presets/<name>.yaml`에 저장합니다.

## CLI 사용

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

CLI와 GUI 모두 run 결과를 SQLite에 기록하고, 필요하면 `data/`로 export합니다.

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

이전 버전 YAML에 `llm:` 섹션이 남아 있어도 로드는 되지만, 현재 버전에서는 무시합니다. 새로 저장되는 YAML에는 `llm`이 포함되지 않습니다.

weight 합계가 1.0이 아니면 scoring 직전에 양수 합 기준으로 자동 정규화합니다.

## 저장소와 출력

기본 저장 위치는 `data/`입니다.

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

예시:

```powershell
$env:SEMANTIC_SCHOLAR_API_KEY = "your_semantic_scholar_key"
python -m streamlit run paper_radar_app.py
```

```bash
export SEMANTIC_SCHOLAR_API_KEY="your_semantic_scholar_key"
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
- config roundtrip과 `llm` 제거 저장
- OpenReview metadata / review signal 파싱
- OpenAlex fallback enrichment
- track assignment / digest
- config compare same-fetch / different-fetch
- old-style `llm` config 무시
- old snapshot extra field 역호환
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

WSL에서는 Windows에 설치한 `streamlit`을 그대로 쓸 수 없으므로, WSL 안의 `venv`에 별도로 설치해야 합니다.

### Fetch 중 source 오류가 나도 앱이 계속 뜸

source별 partial failure를 허용합니다. 경고는 `data/runtime_warnings.log`에 남고, 가능한 source 결과로 계속 진행합니다.

### Compare 탭에 결과가 비어 있음

비교 대상 YAML 각각에 대해 최소 한 번은 `Fetch`를 실행해서 run snapshot이 SQLite에 저장돼 있어야 합니다.

## 현재 범위

- 로컬 단일 사용자 기준입니다.
- ranking은 rule-based입니다.
- source 실패는 partial failure로 처리합니다.
- YAML 비교는 preset 전용이 아니라, GUI에서 발견한 config YAML 전체를 대상으로 합니다.
