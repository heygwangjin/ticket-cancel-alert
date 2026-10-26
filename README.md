# 🎫 NOL티켓 취소표 알림 봇

[NOL티켓](https://nol.yanolja.com/ticket)(구 인터파크 티켓)에서 지정한 공연·경기의 잔여석(취소표)이 **새로 생기면** 텔레그램으로 알려주는 봇입니다.

- 봇은 **알림만** 보냅니다. 예매는 직접 하세요. 자동 예매, 로그인 자동화, 캡차·대기열 우회 기능은 없고 앞으로도 넣지 않습니다.
- 여러 공연을 동시에 감시하고, 날짜·회차·좌석 등급으로 거를 수 있습니다.
- 같은 좌석으로는 알림을 한 번만 보냅니다. 매진됐다가 다시 풀리면 다시 알립니다.
- 3회 연속 조회에 실패하면 "⚠️ 감시 오류"를 알리고, 다시 정상이 되면 "✅ 감시 복구"를 알립니다.
- 알림의 **📱 NOL 앱에서 열기** 버튼을 누르면 로그인돼 있는 NOL 앱에서 공연 페이지가 열립니다.

```
🎫 취소표 발견!
요네즈 켄시 내한공연

• 2027-01-16 (토) 1회 19:00 — 플로어석 2매
• 2027-01-16 (토) 1회 19:00 — 지정석 R 1매
 [📱 NOL 앱에서 열기]  [🌐 웹에서 열기]
```

---

## 1. 텔레그램 봇 만들기

1. 텔레그램에서 [@BotFather](https://t.me/BotFather)를 열고 `/newbot`을 보냅니다.
2. 봇 이름과 아이디를 정하면 `123456789:AA...` 형태의 **봇 토큰**을 줍니다. 비밀번호처럼 보관하세요.
3. BotFather가 알려준 링크(`t.me/<봇아이디>`)로 내 봇 대화창을 열고 **시작** 또는 아무 메시지를 한 번 보냅니다. 봇은 먼저 말을 건 사람에게만 메시지를 보낼 수 있습니다.

## 2. chat_id 확인하기

1. 봇에게 메시지를 보낸 뒤 브라우저에서 아래 주소를 엽니다 (`<토큰>` 자리에 봇 토큰).
   ```
   https://api.telegram.org/bot<토큰>/getUpdates
   ```
2. 결과에서 `"chat":{"id":123456789, ...}`의 숫자가 **chat_id**입니다.
   - `"result":[]`처럼 비어 있으면 봇에게 메시지를 한 번 더 보내고 새로고침하세요.
   - 그룹방으로 받으려면 봇을 그룹에 초대한 뒤 같은 방법으로 확인합니다. 그룹 chat_id는 `-`로 시작합니다.

## 3. 설치

Python 3.11 이상이 필요합니다.

```bash
git clone https://github.com/heygwangjin/ticket-cancel-alert.git
cd ticket-cancel-alert
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt        # 테스트까지 하려면 requirements-dev.txt

cp .env.example .env                 # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 입력
cp config.example.yaml config.yaml   # 감시할 공연 입력
```

텔레그램 연결 확인:

```bash
.venv/bin/python -m notifier "테스트 메시지"
```

## 4. 감시 대상 설정 (config.yaml)

```yaml
settings:
  interval_min_sec: 180        # 점검 간격: 180~300초 사이 무작위 (최소 60초)
  interval_max_sec: 300
  request_delay_sec: [2, 6]    # 요청 사이 무작위 지연(초)
  failure_alert_threshold: 3   # 연속 실패 몇 번에 "감시 오류" 알림을 보낼지
  max_rounds_per_target: 20    # 한 공연에서 조회할 회차 수 상한
  app_open_page: "https://heygwangjin.github.io/ticket-cancel-alert/open.html"  # 아래 "앱으로 열기" 참고

targets:
  - name: "요네즈 켄시 내한"     # 비우면 사이트의 공연명 사용
    site: nol
    goods: "https://nol.yanolja.com/ticket/products/26015024"   # 공연 URL 또는 상품 ID
    dates: ["2027-01-16", "2027-01-17"]   # 비우면 전체 날짜
    rounds: [1]                           # 그날의 회차(1회, 2회…), 비우면 전체
    grades: ["플로어", "R"]               # 비우면 전체 등급

  - goods: "25001234"            # 상품 ID만 적어도 됨
```

- **goods**: NOL 공연 페이지 주소(`https://nol.yanolja.com/ticket/products/…`), 상품 ID, 옛 인터파크 주소 중 아무거나 써도 됩니다.
- **grades**: 사이트 등급명의 일부만 써도 됩니다. `"R"`, `"R석"`, `"지정석 R"`은 모두 "지정석 R"과 맞고, `"플로어"`는 "플로어석"과 맞습니다.
- **rounds**: 사이트 내부 회차 번호가 아니라 **그날의 몇 번째 공연**인지를 적습니다.
- 공연을 처음 등록했을 때 이미 잔여석이 있으면 첫 점검에서 바로 알림이 옵니다.
- 회차가 많은 장기 공연은 `dates`로 범위를 좁혀야 합니다. 한 공연에서 회차를 `max_rounds_per_target`개까지만 조회합니다.

조회가 잘 되는지 미리 보기:

```bash
.venv/bin/python -m sites.nol https://nol.yanolja.com/ticket/products/26015024
```

## 5. 실행

### A. 내 컴퓨터나 서버에서 계속 실행

```bash
.venv/bin/python main.py                          # 3~5분 간격으로 계속 감시 (Ctrl+C로 종료)
.venv/bin/python main.py --once                   # 한 번만 점검
.venv/bin/python main.py --interval-override 30   # 테스트용: 30초 간격
```

- 로그는 화면과 `logs/bot.log`에 남습니다.
- 알림 기록은 `state.json`에 저장되므로, 껐다 켜도 같은 알림을 다시 보내지 않습니다.
- 서버에서 백그라운드로 돌리려면 `nohup .venv/bin/python main.py &`나 systemd, tmux 등을 쓰면 됩니다.

### B. GitHub Actions로 주기 실행

`.github/workflows/monitor.yml`이 5분마다 `python main.py --once`를 실행합니다. `state.json`은 Actions 캐시에 보관되어 다음 실행으로 이어집니다.

1. 이 저장소를 내 GitHub에 올립니다 (fork 또는 새 저장소).
2. 저장소 **Settings → Secrets and variables → Actions → New repository secret**에서 아래 3개를 등록합니다.

   | 이름 | 값 |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | 봇 토큰 |
   | `TELEGRAM_CHAT_ID` | chat_id |
   | `CONFIG_YAML` | `config.yaml` 파일 내용 전체 |

   `gh` CLI가 있으면 터미널에서 바로 등록할 수 있습니다.
   ```bash
   gh secret set -f .env                  # .env 의 두 값을 한 번에
   gh secret set CONFIG_YAML < config.yaml
   ```
3. **Actions** 탭에서 "취소표 감시" 워크플로를 고르고 **Run workflow**로 한 번 실행해 성공하는지 확인합니다.

주의할 점:
- GitHub 스케줄은 **정확하지 않습니다.** 이 저장소에서 `*/5`로 설정했을 때 실제 간격은 평균 약 3시간(2~5시간)이었습니다. 5분 간격이 필요하면 아래처럼 외부 크론으로 실행 신호를 보내세요.
- 공개 저장소에서 **60일 동안 커밋이 없으면** 스케줄 실행이 자동으로 멈춥니다. Actions 탭에서 다시 켜면 됩니다. 외부 크론으로 보내는 실행 신호는 이 제한을 받지 않습니다.
- 공개 저장소의 Actions 실행 로그는 누구나 볼 수 있습니다. 그래서 Actions에서는 경고와 오류만 기록하고, 감시 대상은 저장소 파일이 아니라 `CONFIG_YAML` Secret으로 넣습니다.
- 감시 대상을 바꾸려면 `CONFIG_YAML` Secret을 다시 등록하세요.

#### 외부 크론으로 5분마다 실행하기 (cron-job.org)

GitHub의 정기 스케줄은 늦지만, API로 보내는 수동 실행 신호(`workflow_dispatch`)는 바로 실행됩니다. 무료 크론 서비스가 5분마다 이 신호를 보내게 합니다.

**① GitHub 토큰 만들기** (이 저장소의 Actions 실행 권한만 가진 토큰)
1. GitHub → 프로필 사진 → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. Token name: `cron-job-ticket-alert`, Expiration: 원하는 기간 (만료되면 새로 만들어 교체)
3. Repository access: **Only select repositories** → `ticket-cancel-alert`
4. Permissions → Repository permissions → **Actions: Read and write** (Metadata: Read-only는 자동으로 들어감)
5. **Generate token**을 누르고 `github_pat_…` 값을 복사합니다. 이 화면을 벗어나면 다시 볼 수 없습니다.

**② cron-job.org 설정**
1. https://cron-job.org 에 가입한 뒤 **Dashboard → Create cronjob**
2. COMMON 탭
   - Title: `티켓 취소표 감시`
   - URL: `https://api.github.com/repos/<아이디>/ticket-cancel-alert/actions/workflows/monitor.yml/dispatches`
   - Execution schedule: **Every 5 minutes**
3. ADVANCED 탭
   - Request method: **POST**
   - Headers (4개):

     | Key | Value |
     |---|---|
     | `Authorization` | `Bearer github_pat_…` (①에서 복사한 토큰) |
     | `Accept` | `application/vnd.github+json` |
     | `X-GitHub-Api-Version` | `2022-11-28` |
     | `Content-Type` | `application/json` |
   - Request body: `{"ref":"main"}`
4. **TEST RUN**을 눌러 응답 코드가 **204**(또는 200)인지 확인한 뒤 **CREATE**로 저장합니다.
5. NOTIFICATIONS 탭의 실행 실패 알림을 켜 두면, 토큰이 만료됐을 때 메일로 알 수 있습니다.

응답 코드로 원인을 알 수 있습니다.
- `401`: 토큰이 틀렸거나 만료됨
- `403`: Actions 권한이 Read and write가 아님
- `404`: URL의 아이디·저장소명·파일명이 틀림
- `422`: body의 브랜치 이름이 틀림

실행이 겹치면 워크플로의 `concurrency` 설정에 따라 차례로 실행되므로, 상태 파일이 꼬이지 않습니다.

## 6. 앱으로 열기 (📱 버튼)

텔레그램 버튼에는 `https://` 주소만 넣을 수 있어서, NOL 앱 전용 주소(`yanoljamotel://wv?url=…`)로 바로 연결할 수 없습니다. 그래서 `docs/open.html` 중계 페이지를 거칩니다.

```
텔레그램 버튼 → https://<아이디>.github.io/ticket-cancel-alert/open.html?url=<NOL 공연 주소>
             → yanoljamotel://wv?url=<NOL 공연 주소>  → NOL 앱 (로그인 상태 유지)
```

설정 방법:
1. 저장소 **Settings → Pages**에서 Source를 **Deploy from a branch**로 하고, 브랜치는 `main`, 폴더는 `/docs`로 저장합니다.
2. 1~2분 뒤 `https://<아이디>.github.io/<저장소명>/open.html` 주소가 열리면, 이 주소를 `config.yaml`의 `app_open_page`에 넣습니다 (Actions를 쓴다면 `CONFIG_YAML`에도).
3. 중계 페이지는 `https://nol.yanolja.com` 주소만 받기 때문에 다른 사이트로 넘기는 데 쓰일 수 없습니다.

iPhone에서 확인했습니다. 앱이 열리지 않으면 중계 페이지의 **📱 NOL 앱에서 열기** 버튼을 직접 누르거나 **🌐 웹에서 열기**를 쓰세요.

## 7. 구조

```
main.py              진입점 (계속 실행 / --once)
config.py            config.yaml + .env 로드·검증
monitor.py           점검 1회: 조회 → 새 잔여석 판별 → 알림 → 상태 저장
state.py             state.json (좌석별 마지막 잔여 수량, 연속 실패 횟수)
notifier.py          텔레그램 Bot API sendMessage
sites/base.py        공통 타입(SeatAvailability), 재시도 GET, 등급명 매칭
sites/nol.py         NOL티켓 조회
sites/__init__.py    사이트 목록
docs/open.html       앱 열기 중계 페이지 (GitHub Pages)
```

NOL 조회 방식: 공연 페이지가 브라우저에서 호출하는 **비로그인 공개 API**를 그대로 씁니다.
1. 공연 페이지 HTML에서 공연명, 공연 기간, 공연장 코드를 읽습니다. 6시간 캐시합니다.
2. `/ticket/products/api/schedules`에서 회차 목록을 받습니다.
3. `/ticket/products/api/remaining-seats`에서 회차별·등급별 잔여 수량을 받습니다.

요청 사이에는 2~6초씩 쉬고, 429·5xx 응답에는 간격을 늘려 가며 최대 2번만 다시 시도합니다. NOL이 사이트 구조를 바꾸면 조회가 실패할 수 있는데, 이때는 "감시 오류" 알림으로 알 수 있습니다.

**다른 사이트 추가하기**: `sites/<이름>.py`에 `fetch(target) -> list[SeatAvailability]`를 가진 클래스를 만들고, `sites/__init__.py`의 `_REGISTRY`에 한 줄 추가한 뒤 config에서 `site: <이름>`으로 쓰면 됩니다.

## 8. 테스트

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

실제 네트워크 없이 저장해 둔 NOL 응답으로 파싱, 필터, 중복 알림, 실패 알림 시나리오를 검사합니다.

## 주의

이 봇은 개인이 취소표를 놓치지 않도록 돕는 알림 도구입니다. 점검 간격을 지나치게 줄이거나 공연을 너무 많이 등록해 사이트에 부담을 주지 마세요. 최소 간격은 60초로 막혀 있습니다. 사이트 이용약관은 직접 확인하세요.
