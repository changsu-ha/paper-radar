# Paper Radar Harness

Paper Radar Harness??理쒓렐 ?쇰Ц???섏쭛?섍퀬, 硫뷀??곗씠?곕? enrich???? 洹쒖튃 湲곕컲?쇰줈 ?먯닔瑜?怨꾩궛?섍퀬, digest? preset 鍮꾧탳瑜??????덇쾶 留뚮뱺 濡쒖뺄 ?꾧뎄?낅땲??

?꾩옱 湲곕뒫:

- `arXiv` ?섏쭛
- `OpenReview` ?섏쭛
- `Semantic Scholar` enrich
- `OpenAlex` enrich
- rule-based ranking
- track assignment
- daily / weekly digest
- Streamlit GUI
- YAML preset ???
- config A/B 鍮꾧탳
- SQLite run snapshot ???

## 援ъ꽦

- [paper_radar_core.py](./paper_radar_core.py)
  ?섏쭛, enrich, ranking, digest, SQLite, compare 濡쒖쭅
- [paper_radar_app.py](./paper_radar_app.py)
  Streamlit GUI
- [paper_radar_starter.py](./paper_radar_starter.py)
  CLI entrypoint
- [configs/paper_radar_config_robotics.yaml](./configs/paper_radar_config_robotics.yaml)
  湲곕낯 robotics config
- [configs/paper_radar_config_fundamental_ml.yaml](./configs/paper_radar_config_fundamental_ml.yaml)
  fundamental ML ?덉젣 config
- [tests/test_paper_radar_core.py](./tests/test_paper_radar_core.py)
  肄붿뼱 ?뚯뒪??
- [tests/test_paper_radar_app.py](./tests/test_paper_radar_app.py)
  GUI helper ?뚯뒪??

## ?붽뎄 ?ы빆

- Python 3.9+
- ?명꽣???곌껐
- `pip install -r requirements.txt`

?섏〈??

- `requests`
- `PyYAML`
- `streamlit`
- `pandas`

## venv ?ㅼ젙

### Windows PowerShell

```powershell
cd \\wsl.localhost\Ubuntu-24.04\home\changsu_ha\repos\paper_radar_harness

python -m venv .venv
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

鍮꾪솢?깊솕:

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

Ubuntu?먯꽌 `venv`媛 ?놁쑝硫?癒쇱? ?ㅼ튂?⑸땲??

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip
```

鍮꾪솢?깊솕:

```bash
deactivate
```

## ?쒕쾭 ?ㅽ뻾

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

釉뚮씪?곗?:

```text
http://localhost:8501
```

諛깃렇?쇱슫???ㅽ뻾 ?덉떆:

```bash
source .venv/bin/activate
nohup python -m streamlit run paper_radar_app.py --server.address 0.0.0.0 --server.port 8501 > streamlit.log 2>&1 &
```

以묒?:

```bash
pkill -f "streamlit run paper_radar_app.py"
```

## GUI ?ъ슜

湲곕낯 ?ㅽ뻾:

```bash
python -m streamlit run paper_radar_app.py
```

珥덇린 config瑜?吏?뺥빐?????섎룄 ?덉뒿?덈떎.

```bash
python -m streamlit run paper_radar_app.py -- --config-path configs/paper_radar_config_fundamental_ml.yaml
```

GUI?먯꽌???쒖옉 ?몄옄??怨좎젙?섏? ?딄퀬, ?ъ씠?쒕컮?먯꽌 ?ㅼ쓬 YAML???쒕∼?ㅼ슫?쇰줈 諛붽퓭媛硫??ㅽ뿕?????덉뒿?덈떎.

- `configs/*.yaml`
- `data/gui_presets/*.yaml`

??援ъ꽦:

- `Single Run`
  ?꾩옱 fetch snapshot 湲곗? rerank 寃곌낵? ?쇰Ц ?곸꽭
- `Track Digest`
  daily digest, weekly track digest preview
- `Compare`
  ?좏깮??YAML A/B??config diff? 寃곌낵 diff

?숈옉 洹쒖튃:

- fetch 愿???ㅼ젙 蹂寃쎌? `Fetch`瑜??ㅼ떆 ?뚮윭??諛섏쁺?⑸땲??
- ranking怨?digest 愿???ㅼ젙 蹂寃쎌? 留덉?留?fetch snapshot??利됱떆 ?ъ쟻?⑸맗?덈떎.
- `?꾩옱 ?ㅼ젙 ???? `data/gui_presets/<name>.yaml`????ν빀?덈떎.

## GUI ??ぉ ?섎?

### YAML / preset

- `YAML ?뚯씪`
  ?ㅽ뿕???쒖옉?먯씠 ?섎뒗 ?ㅼ젙 ?뚯씪?낅땲?? 遺덈윭?ㅻ㈃ ?꾩옱 ?몄뀡??fetch 寃곌낵? 鍮꾧탳 ?곹깭瑜?珥덇린?뷀빀?덈떎.
- `????대쫫`
  ?꾩옱 ?붾㈃ ?ㅼ젙??preset YAML濡???ν븷 ?대쫫?낅땲??

### Fetch ?ㅼ젙

- `寃??湲곌컙 (days_back)`
  理쒓렐 硫곗튌 ?덉뿉 ?섏삩 ?쇰Ц留??섏쭛?좎? ?뺥빀?덈떎.
- `query蹂?理쒕? 寃곌낵 ??
  媛?query?먯꽌 理쒕? 紐??멸퉴吏 媛?몄삱吏 ?뺥빀?덈떎.
- `arXiv queries`
  arXiv 寃?됱떇?낅땲?? 以꾨쭏???섎굹??query濡?泥섎━?⑸땲??
- `移댄뀒怨좊━`
  arXiv 移댄뀒怨좊━ ?꾪꽣?낅땲??
- `Semantic Scholar enrich`
  ?대? ?섏쭛???쇰Ц??citation, venue, field ?뺣낫瑜?異붽?濡?遺숈엯?덈떎.
- `OpenReview ?섏쭛`
  OpenReview venue?먯꽌 ?쇰Ц??異붽? source濡??섏쭛?⑸땲??
- `OpenReview venues`
  OpenReview venue id 紐⑸줉?낅땲??
- `OpenReview keywords`
  OpenReview ?섏쭛 寃곌낵?먯꽌 ?쒕ぉ/珥덈줉/?ㅼ썙?쒖뿉 ?ы븿?섏뼱?????꾪꽣 ?ㅼ썙?쒖엯?덈떎.
- `OpenAlex enrich`
  ?대? ?섏쭛???쇰Ц??citation, topic, OA ?뺣낫瑜?異붽?濡?遺숈엯?덈떎.

### Ranking ?ㅼ젙

- `include_keywords`
  ???ㅼ썙?쒓? 留롮씠 留욎쓣?섎줉 relevance媛 ?щ씪媛묐땲??
- `exclude_keywords`
  ???ㅼ썙?쒓? 諛쒓껄?섎㈃ ?대떦 ?쇰Ц? 諛붾줈 `archive` 泥섎━?⑸땲??

#### weight ?섎?

- `weight.relevance`
  ?닿? 蹂닿퀬 ?띠? 二쇱젣? ?쇰쭏??吏곸젒?곸쑝濡?留욌뒗吏?낅땲??
- `weight.novelty`
  ?덈줈??臾몄젣 ?ㅼ젙, 諛⑸쾿, benchmark, dataset 媛숈? ?덈줈? ?좏샇?낅땲??
- `weight.empirical`
  ablation, baseline, simulation, real-world 媛숈? ?ㅽ뿕/寃利??좏샇?낅땲??
- `weight.source_signal`
  異쒖쿂? 硫뷀??곗씠???덉쭏 ?좏샇?낅땲??
- `weight.momentum`
  citation 湲곕컲 ?곹뼢?μ엯?덈떎.
- `weight.recency`
  理쒖떊?깆엯?덈떎.
- `weight.actionability`
  ?ㅼ젣濡??쎄퀬 ?곸슜??留뚰븳 ?ㅼ슜???좏샇?낅땲??

#### bucket ?섎?

- `bucket.must_read`
  ???먯닔 ?댁긽?대㈃ must_read濡?遺꾨쪟?⑸땲??
- `bucket.worth_reading`
  ???먯닔 ?댁긽?대㈃ worth_reading?쇰줈 遺꾨쪟?⑸땲??
- `bucket.skim`
  ???먯닔 ?댁긽?대㈃ skim?쇰줈 遺꾨쪟?⑸땲?? 洹??꾨옒??archive?낅땲??

### Digest ?ㅼ젙

- `daily_top_k`
  daily digest? export?먯꽌 ?욎そ??蹂댁뿬以??곸쐞 ?쇰Ц ?섏엯?덈떎.
- `weekly_top_k_per_track`
  weekly digest?먯꽌 track蹂꾨줈 蹂댁뿬以?理쒕? ?쇰Ц ?섏엯?덈떎.
- `track order`
  ?щ윭 track???숈떆??嫄몃┫ ??primary track ?곗꽑?쒖꽌?낅땲??
- `custom track_definitions (YAML)`
  湲곕낯 track ?뺤쓽瑜???뼱?곕뒗 YAML?낅땲??

## source / enrich ?섎?

- `arXiv`
  湲곕낯 ?섏쭛 source?낅땲??
- `OpenReview`
  venue ?⑥쐞 異붽? ?섏쭛 source?낅땲??
- `Semantic Scholar enrich`
  ???쇰Ц????媛?몄삤??湲곕뒫???꾨땲?? ?대? ?섏쭛???쇰Ц??citation / venue / field ?뺣낫瑜?異붽??⑸땲??
- `OpenAlex enrich`
  ???쇰Ц????媛?몄삤??湲곕뒫???꾨땲?? ?대? ?섏쭛???쇰Ц??citation / topic / OA ?뺣낫瑜?異붽??⑸땲??

?꾩옱 援ъ“?먯꽌??source蹂?媛쒕퀎 weight???놁뒿?덈떎. 紐⑤뱺 ?쇰Ц??怨듯넻?쇰줈 `relevance`, `novelty`, `empirical`, `source_signal`, `momentum`, `recency`, `actionability`??global weight媛 ?곸슜?⑸땲?? source 李⑥씠??二쇰줈 `source_signal`, citation, venue, topic 媛숈? metadata瑜??듯빐 媛꾩젒 諛섏쁺?⑸땲??

## CLI ?ъ슜

湲곕낯 ?ㅽ뻾:

```bash
python paper_radar_starter.py
```

?ㅻⅨ config ?ъ슜:

```bash
python paper_radar_starter.py --config-path configs/paper_radar_config_fundamental_ml.yaml
```

?먮뒗:

```bash
python paper_radar_starter.py configs/paper_radar_config_fundamental_ml.yaml
```

## ?ㅼ젙 ?뚯씪

二쇱슂 ?뱀뀡:

- `sources.arxiv`
  query, category, 湲곌컙, query蹂?理쒕? 寃곌낵 ??
- `sources.openreview`
  venue, keyword 湲곕컲 ?섏쭛
- `sources.semanticscholar`
  citation / venue / field enrich
- `sources.openalex`
  citation / topic / OA enrich
- `filters.include_keywords`
  relevance 愿???ㅼ썙??
- `filters.exclude_keywords`
  hit ??`archive`
- `ranking.weights`
  理쒖쥌 ?먯닔 媛以묒튂
- `ranking.buckets`
  `must_read`, `worth_reading`, `skim`
- `digest.tracks`
  ordered primary track ?곗꽑?쒖쐞
- `digest.track_definitions`
  custom track definition override

?댁쟾 踰꾩쟾 YAML??`llm:` ?뱀뀡???⑥븘 ?덉뼱??濡쒕뱶???섏?留? ?꾩옱 踰꾩쟾?먯꽌??臾댁떆?⑸땲?? ?덈줈 ??λ릺??YAML?먮뒗 `llm`???ы븿?섏? ?딆뒿?덈떎.

weight ?⑷퀎媛 1.0???꾨땲硫?scoring 吏곸쟾???먮룞 ?뺢퇋?뷀빀?덈떎.

## ??μ냼? 異쒕젰

湲곕낯 ????꾩튂??`data/`?낅땲??

- `data/paper_radar.sqlite3`
  runs, canonical papers, source payloads, run rankings, track assignments
- `data/daily_radar.md`
  daily digest export
- `data/weekly_track_digest.md`
  weekly track digest export
- `data/papers.jsonl`
  理쒖쥌 snapshot paper dump
- `data/gui_presets/*.yaml`
  GUI?먯꽌 ??ν븳 preset
- `data/runtime_warnings.log`
  source/network 寃쎄퀬 濡쒓렇

## ?섍꼍 蹂??

- `SEMANTIC_SCHOLAR_API_KEY`
- `OPENALEX_API_KEY`
- `PAPER_RADAR_CONFIG`

?덉떆:

```powershell
$env:SEMANTIC_SCHOLAR_API_KEY = "your_semantic_scholar_key"
python -m streamlit run paper_radar_app.py
```

```bash
export SEMANTIC_SCHOLAR_API_KEY="your_semantic_scholar_key"
python -m streamlit run paper_radar_app.py --server.address 0.0.0.0 --server.port 8501
```

## ?뚯뒪??

?ㅽ뻾:

```bash
python -m unittest discover -s tests -v
```

?꾩옱 ?뚯뒪??踰붿쐞:

- `days_back` cutoff? arXiv pagination 以묐떒 議곌굔
- exclude keyword archive 泥섎━
- weight normalization
- config roundtrip怨?`llm` ?쒓굅 ???
- OpenReview metadata / review signal ?뚯떛
- OpenAlex fallback enrichment
- track assignment / digest
- config compare same-fetch / different-fetch
- old-style `llm` config 臾댁떆
- old snapshot extra field ??샇??
- SQLite persistence + export
- rerank ???ㅽ듃?뚰겕 誘명샇異?
- warning / `OSError` 諛⑹뼱
- GUI config discovery / session reset helper

## 臾몄젣 ?닿껐

### `streamlit: command not found`

?遺遺?PATH 臾몄젣?낅땲?? ?꾨옒泥섎읆 ?ㅽ뻾?섎㈃ ?⑸땲??

```bash
python -m streamlit run paper_radar_app.py
```

WSL?먯꽌??Windows???ㅼ튂??`streamlit`??洹몃?濡??????놁쑝誘濡? WSL ?덉쓽 `venv`??蹂꾨룄濡??ㅼ튂?댁빞 ?⑸땲??

### Fetch 以?source ?ㅻ쪟媛 ?섎룄 ?깆씠 怨꾩냽 ??

source蹂?partial failure瑜??덉슜?⑸땲?? 寃쎄퀬??`data/runtime_warnings.log`???④퀬, 媛?ν븳 source 寃곌낵濡?怨꾩냽 吏꾪뻾?⑸땲??

### Compare ??뿉 寃곌낵媛 鍮꾩뼱 ?덉쓬

鍮꾧탳 ???YAML 媛곴컖?????理쒖냼 ??踰덉? `Fetch`瑜??ㅽ뻾?댁꽌 run snapshot??SQLite????λ뤌 ?덉뼱???⑸땲??

