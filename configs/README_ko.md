# configs 안내

## 실행용 config
- `robotics.yaml`, `optimization_training_dynamics.yaml`, `broad_ml.yaml` 같은 파일은 직접 선택해서 실행하는 검색 config입니다.
- 이 파일들은 `sources`, `filters`, `ranking`, `digest`를 포함합니다.

## OpenAlex 기관 catalog
- `paper_radar_config_major_universities.yaml`
- `paper_radar_config_major_research_labs.yaml`

위 두 파일은 더 이상 실행용 preset이 아닙니다. OpenAlex affiliation 매칭용 보조 catalog입니다.

용도:
- OpenAlex enrich로 수집한 저자 소속 기관 metadata를 기준으로
- 주요 대학 또는 주요 연구소 논문에 `source_signal` bonus를 주는 데 사용합니다.

특징:
- GUI 메인 YAML 선택 목록에는 표시되지 않습니다.
- GUI의 `OpenAlex priority catalogs`에서 선택해서 사용합니다.
- `ranking.openalex_priority_catalogs`에 경로를 넣으면 config에서도 직접 사용할 수 있습니다.

예시:

```yaml
ranking:
  openalex_priority_catalogs:
    - configs/paper_radar_config_major_universities.yaml
    - configs/paper_radar_config_major_research_labs.yaml
```

주의:
- 이 기능은 `boost only`입니다. 매칭되지 않은 논문을 제거하지는 않습니다.
- 실제 기관 매칭을 하려면 `sources.openalex.enabled: true`로 두고 다시 fetch 해야 합니다.
- OpenAlex key는 WSL에서는 보통 `~/.profile`에 `OPENALEX_API_KEY`로 두는 것이 가장 안정적입니다.
