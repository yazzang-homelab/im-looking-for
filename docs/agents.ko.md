# AI 에이전트를 위한 im-looking-for

[English](agents.md) · **한국어**

im-looking-for를 쓰면 에이전트가 사용자 컴퓨터의 파일을 내용으로 찾을 수 있습니다. “워크숍 때 찍은 화이트보드 사진”,
“임대차 계약서에서 반려동물 조항이 나오는 PDF”, “치과 얘기한 음성메모”처럼 사진·스캔·슬라이드·문서·오디오·영상을
가로질러 100개 이상의 언어로 찾습니다. 모든 처리는 로컬에서 합니다.

연결 방법은 **MCP 서버**(`ilf mcp`)와 **`--json` CLI** 두 가지이며, 둘 다 같은 JSON 구조를 돌려줍니다.

## 연결

| 클라이언트 | 방법 |
|---|---|
| Claude Code | `claude mcp add im-looking-for -- ilf mcp` |
| Codex CLI | `codex mcp add im-looking-for -- ilf mcp` |
| Claude Desktop, Cursor 등 | `{"mcpServers": {"im-looking-for": {"command": "ilf", "args": ["mcp"]}}}` |
| MCP 미지원 | 셸에서 `ilf <검색어> --json` 실행 |

에이전트의 `PATH`에 `ilf`가 없으면 절대 경로를 쓰십시오. 앱의 보관함 패널에 이 설치본의 정확한 명령이 복사 버튼과
함께 표시됩니다.

검색할 대상이 생기려면 사용자가 설정을 한 번 실행하고(`ilf` 또는 `ilf setup`) 폴더를 추가해야 합니다. 폴더 추가와
색인 시작은 에이전트가 직접 할 수 있지만(`add_folder`, `index`), 약 900MB 모델 내려받기는 사용자에게 맡깁니다.

## MCP 도구

| 도구 | 인자 | 반환 | 부수 효과 |
|---|---|---|---|
| `search` | `query`, `limit` = 10(1~50), `kinds` = 전체(`image`, `pdf`, `doc`, `audio`, `video`) | `{query, results: [Result]}` | 처음 호출 시 모델 기동 |
| `read_passages` | `path`(결과의 경로), `loc` = 처음, `limit` = 10 | `{path, passages: [{kind, modality, loc, loc_end, text}]}` | 없음 |
| `status` | 없음 | 아래 Status + `indexing`, `progress`, `index_error` | 없음 |
| `add_folder` | `folder` | `{added, folders}` | 설정 변경 |
| `remove_folder` | `folder` | `{removed, folders}` | 설정 변경. 다음 전체 색인 때 색인에서 빠짐 |
| `index` | `folders` = 전체 | `{started, queued}` | 백그라운드에서 파일 읽기. 이미 읽는 중이면 끝난 뒤 한 번 더 읽도록 예약 |
| `stop_indexing` | 없음 | `{stopping}` | 현재 파일까지 읽고 멈춤 |

`index`는 바로 반환합니다. `status`의 `indexing`이 false가 될 때까지 폴링하십시오. `progress`에는 `total`, `read`,
`unchanged`, `unreadable`과 지금 읽는 파일(`current`)이 들어 있습니다. 색인 중에도 이미 읽은 파일은 검색할 수 있습니다.

읽기 전용 도구에는 `readOnlyHint`가, `remove_folder`에는 `destructiveHint`가 붙어 있습니다(`remove_folder`는 폴더
목록만 바꾸며 디스크의 파일은 건드리지 않습니다).

## 결과(Result)

```json
{
  "path": "/home/you/Documents/lease_2026.pdf",
  "name": "lease_2026.pdf",
  "kind": "pdf",
  "score": 0.7765,
  "match": "page",
  "loc": 1.0,
  "loc_end": null,
  "where": "p.1",
  "snippet": "주택 임대차 계약서 제 1 조 (목적) …"
}
```

| 필드 | 의미 |
|---|---|
| `kind` | `image`, `pdf`, `doc`, `audio`, `video` |
| `match` | 일치한 대상: `image`, `page`(PDF 글자), `page_image`(그림으로 읽은 PDF 쪽), `chunk`(문서 한 토막), `audio`, `frame`(영상 프레임), `name`(파일·폴더 이름) |
| `loc`, `loc_end` | PDF는 쪽 번호, 문서는 토막 번호(0부터), 오디오·영상은 초 |
| `where` | 사람이 읽는 `loc`: `p.3`, `0:42`. 그림·문서·이름은 빈 값 |
| `snippet` | 일치한 글. 그림과 소리는 빈 값 |

파일마다 결과 하나이며 가장 잘 맞는 것부터 나옵니다.

## 점수 읽는 법

검색은 맞는 것이 없어도 **언제나 가장 가까운 파일을 돌려줍니다**. 시연 폴더에서 측정한 값입니다.
`lease termination`은 임대차 PDF가 0.78, 그다음 무관한 파일이 0.59였고, 무의미한 검색어 `xyzzy-nothing-here`도
영상 하나를 0.61로 돌려줬습니다. 따라서 다음을 지키십시오.

- 점수는 다른 결과와 비교할 때만 의미가 있습니다. 나머지보다 뚜렷이 앞선 결과(0.78 대 0.59)는 일치이고, 비슷한
  점수가 고르게 이어지면 “여기에는 없을 가능성이 높음”으로 보십시오.
- 단정하기 전에 확인하십시오. `snippet`을 읽거나 결과의 `path`와 `loc`으로 `read_passages`를 호출하십시오.
- 검색에 안 나왔다고 파일이 없다고 말하지 마십시오. 폴더가 추가·색인되지 않았거나(`status`로 확인), 읽지 않는
  형식(HEIC, 코드)이거나, 글자가 사진 속에 있을 수 있습니다(OCR 없음).

## 검색어 쓰는 법

- 이름이 아니라 내용을 묘사하십시오. `IMG_2041`이 아니라 `빨간 소파에서 자는 고양이`. 파일 이름도 키워드로
  검색되므로 아는 이름이 있으면 함께 넣어도 됩니다.
- 어떤 언어든 되고 섞여도 됩니다. 영어 검색어로 한국어 PDF를 찾습니다.
- 사용자가 종류를 말했으면(“그 녹음…”, “그 PDF…”) `kinds`를 쓰십시오.
- 정확한 단어도 반영됩니다. 문서에 글자 그대로 나오는 단어는 순위를 올리므로 이름·코드·숫자 검색에 유리합니다.

## `--json` CLI

```sh
ilf 3월 청구서 --json                  # ilf search 3월 청구서 --json 과 같음
ilf -k image -n 5 화이트보드 --json
ilf status --json
ilf add ~/Scans --json && ilf index --json
```

| 종료 코드 | 의미 |
|---|---|
| 0 | 완료(검색이면 결과 1개 이상) |
| 1 | 검색 결과 없음: 색인이 비었거나 `--kind`를 통과한 파일이 없음 |
| 2 | 오류. `--json`이면 stdout에 `{"error": "...", "code": 2}` |
| 3 | 설정 전: llama.cpp나 모델이 없음(`ilf setup`) |

`ilf index --json`은 끝날 때까지 기다린 뒤 `{read, unchanged, forgotten, unreadable, seconds, errors}`를
출력합니다. 진행 표시는 터미널일 때만 stderr로 나가므로 stdout은 깨끗한 JSON입니다.

## 상태(Status)

```json
{
  "version": "0.1.0",
  "ready": true,
  "data_dir": "/home/you/.local/share/im-looking-for",
  "runtime": "llama-b11461-bin-ubuntu-x64.tar.gz",
  "backend": "cpu",
  "gpu_failed": null,
  "backends": ["cpu", "vulkan"],
  "missing_models": [],
  "download_bytes": 0,
  "folders": ["/home/you/Pictures", "/home/you/Documents"],
  "excluded_folders": [],
  "excluded_extensions": [],
  "index": {"files": {"image": 6, "pdf": 1, "doc": 3}, "errors": 0, "vectors": 17, "bytes": 98304}
}
```

## 개인정보

컴퓨터 밖으로 나가는 것은 없습니다. 모델은 로컬 llama.cpp 프로세스에서, 색인은 로컬 SQLite 파일에서 동작합니다.
`read_passages`는 이미 색인된 파일, 즉 사용자가 폴더를 추가해 고른 파일의 글만 돌려줍니다.
