# 전자신문 관심 기사 모음 (모바일 앱)

전자신문 RSS(`https://rss.etnews.com/Section901.xml`, 오늘의 뉴스 최신 30건)를 10분마다 확인해서
키워드가 들어간 기사를 **모바일 페이지에 계속 쌓아줍니다.**
휴대폰 홈 화면에 추가하면 앱처럼 열립니다. 알림(Gmail / 카카오톡)은 하루 한 번 요약으로 받을 수 있습니다.
외부 패키지 없이 Python 표준 라이브러리만 사용합니다.

실행 방법은 두 가지입니다.
- **A. GitHub Actions + GitHub Pages (추천)**: PC를 꺼도 24시간 동작, 휴대폰으로 어디서나 열람, 무료
- **B. 내 PC에서 실행**: 알림만 받을 때. PC가 켜져 있을 때만 동작

## 모바일 페이지 기능
- 키워드별 모아보기 (반도체 / AI / …), 날짜별(오늘·어제·날짜) 정리
- 검색, **안 읽은 것만** 보기, **모두 읽음**
- ☆ **즐겨찾기** — 오래돼서 목록에서 빠져도 즐겨찾기는 남음
- 지난번 방문 이후 새로 들어온 기사에 ● 표시
- 다크 모드 자동, 오프라인일 때 마지막 목록 표시
- 제목을 누르면 전자신문 원문으로 이동

> 읽음·즐겨찾기는 **그 기기 브라우저에 저장**됩니다 (휴대폰과 PC 사이에 공유되지 않음).

## 파일
| 파일 | 설명 | 저장소에 올림? |
|---|---|---|
| `etnews_alert.py` | 본체 (수집·보관·알림) | O |
| `kakao_auth.py` | 카카오 최초 로그인(한 번만, PC에서 실행) | O |
| `config.json` | 키워드·알림 방식 (비밀값 없음) | O |
| `docs/` | 모바일 페이지 (`index.html`, 아이콘 등) + `articles.json`(모인 기사) | O |
| `.github/workflows/etnews-alert.yml` | GitHub Actions 설정 | O |
| `seen.json`, `state.json` | 확인한 기사·요약 대기 목록 (자동 생성) | O (Actions가 자동 커밋) |
| `secrets.json` | PC 실행용 비밀값 (`secrets.example.json` 참고) | **X** |
| `kakao_token.json` | 카카오 토큰 (자동 생성) | **X** |

`.gitignore`가 `secrets.json`, `kakao_token.json`을 막아두었습니다.

---

## 1. 설정 (`config.json`)
```json
"keywords": ["반도체", "AI", "배터리"],
"notify_mode": "daily",
"daily_hour": 8,
"page_url": "https://<내아이디>.github.io/<저장소>/",
"gmail": { "enabled": true },
"kakao": { "enabled": false, ... }
```
- `keywords`: 대소문자 구분 없이 **제목 + 요약문**에서 찾습니다 (제목만: `"search_description": false`).
  짧은 영문 키워드(예: `AI`)는 다른 단어 안에서도 걸릴 수 있어요.
- `notify_mode`:
  - `"daily"` — 매일 `daily_hour`시(한국시간) 이후 첫 확인 때, 하루 동안 모인 기사를 **한 번에** 요약 발송
  - `"instant"` — 새 기사가 걸릴 때마다 바로 발송
  - `"off"` — 알림 없이 페이지에만 쌓기
- `page_url`: GitHub Pages 주소(아래 A-6). 넣으면 메일/카톡에 "모아보기" 링크가 붙어요.
- `max_articles`: 페이지에 보관할 최대 기사 수 (기본 1000, 오래된 것부터 삭제)
- 첫 실행 때 이미 올라와 있던 기사는 페이지에만 넣고 알림은 보내지 않습니다.
- 발송에 실패한 기사는 다음 확인 때 다시 시도합니다.

## 2. 발송 수단 준비

### Gmail
1. Google 계정 → 보안 → **2단계 인증** 켜기
2. https://myaccount.google.com/apppasswords 에서 **앱 비밀번호**(16자리) 생성

### 카카오톡 (나에게 보내기)
1. https://developers.kakao.com → **애플리케이션 추가**
2. **앱 키 → REST API 키** 복사
3. **카카오 로그인** 활성화 ON, **Redirect URI**에 `http://localhost:5000/callback` 등록
4. **카카오 로그인 → 동의항목**에서 *카카오톡 메시지 전송(talk_message)* 을 "선택 동의"로 설정
5. **플랫폼 → Web** 사이트 도메인에 `https://www.etnews.com` 추가 (메시지 속 기사 링크가 열리도록)
6. (보안 → Client Secret을 켰다면 그 값도 준비)
7. PC에서 `secrets.example.json`을 `secrets.json`으로 복사해 `kakao_rest_api_key`를 채우고:
   ```
   py kakao_auth.py
   ```
   브라우저에서 로그인·동의하면 `kakao_token.json`이 생깁니다.
8. `config.json`에서 `"kakao": { "enabled": true, ... }`

---

## A. GitHub Actions로 24시간 실행

1. GitHub에서 **새 저장소** 생성
   - **Public 추천**: Actions가 무제한 무료. 비밀값은 Secrets에만 들어가므로 코드가 공개돼도 안전합니다.
     (단, 키워드와 모인 기사 목록 페이지는 주소를 아는 누구나 볼 수 있습니다)
   - GitHub Pages도 무료 계정은 Public 저장소에서만 쓸 수 있습니다.
   - Private로 하면 무료 한도가 월 2,000분이라, 10분 간격(월 약 4,300회)은 초과합니다.
     → workflow의 cron을 `"*/30 * * * *"`(30분)로 바꾸세요.
2. 이 폴더의 파일을 올립니다 (`secrets.json`, `kakao_token.json` 제외 — `.gitignore`가 막아줌):
   ```
   git init
   git add .
   git commit -m "etnews alert"
   git branch -M main
   git remote add origin https://github.com/<내아이디>/<저장소>.git
   git push -u origin main
   ```
3. 저장소 → **Settings → Secrets and variables → Actions → New repository secret** 에 등록:

   | 이름 | 값 | 필요할 때 |
   |---|---|---|
   | `GMAIL_SENDER` | 보내는 Gmail 주소 | Gmail |
   | `GMAIL_APP_PASSWORD` | 앱 비밀번호 16자리 | Gmail |
   | `GMAIL_TO` | 받는 주소 (여러 개면 쉼표로) — 생략 시 보내는 주소 | Gmail |
   | `KAKAO_REST_API_KEY` | REST API 키 | 카카오 |
   | `KAKAO_CLIENT_SECRET` | Client Secret (안 켰으면 생략) | 카카오 |
   | `KAKAO_REFRESH_TOKEN` | PC의 `kakao_token.json` 안 `refresh_token` 값 | 카카오 |
   | `GH_PAT` | (선택) 아래 설명 참고 | 카카오 |

4. 저장소 → **Settings → Actions → General → Workflow permissions** 에서
   **Read and write permissions** 선택 (seen.json 저장용)
5. **Actions 탭 → etnews-alert → Run workflow** 로 한 번 수동 실행해서 로그 확인.
   이후 10분마다 자동 실행됩니다.
6. **모바일 페이지 켜기**: 저장소 → **Settings → Pages** →
   Source: *Deploy from a branch*, Branch: `main`, 폴더: **`/docs`** → Save.
   1~2분 뒤 위쪽에 `https://<내아이디>.github.io/<저장소>/` 주소가 나옵니다.
   이 주소를 `config.json`의 `page_url`에 넣어 주세요.
   (카카오를 쓴다면 카카오 개발자 콘솔 **플랫폼 → Web**에 `https://<내아이디>.github.io`도 추가)
7. **휴대폰 홈 화면에 추가** (앱처럼 쓰기):
   - 아이폰: Safari로 주소 열기 → 공유 버튼 → **홈 화면에 추가**
   - 안드로이드: Chrome으로 주소 열기 → ⋮ 메뉴 → **홈 화면에 추가** (또는 "앱 설치")

### 카카오 refresh token 자동 갱신 (`GH_PAT`, 선택)
카카오 refresh token은 약 2개월짜리이고, 만료 1개월 전부터 새 토큰이 발급됩니다.
`GH_PAT`을 넣어두면 새 토큰이 나올 때 앱이 `KAKAO_REFRESH_TOKEN` Secret을 자동으로 바꿔서 **계속 쓸 수 있습니다**.
- 만들기: GitHub → Settings → Developer settings → **Fine-grained tokens** → 이 저장소만 선택 →
  Repository permissions에서 **Secrets: Read and write**
- 안 넣으면: 로그에 경고가 뜨고, 약 2개월마다 PC에서 `py kakao_auth.py`를 다시 실행해 Secret을 직접 바꿔야 합니다.

### 알아둘 점
- GitHub의 예약 실행은 부하에 따라 **몇 분~수십 분 늦어질 수** 있습니다.
- 저장소에 60일간 커밋이 없으면 예약 실행이 멈추는데, 이 앱은 새 기사가 올 때마다 `seen.json`을 커밋하므로 보통 문제없습니다.
- 키워드를 바꾸려면 GitHub 웹에서 `config.json`을 바로 수정하면 됩니다.

---

## B. 내 PC에서 실행
1. `secrets.example.json` → `secrets.json` 으로 복사해서 값 채우기
2. 실행:
   ```
   py etnews_alert.py --test      # 테스트 메시지 발송 → 설정 확인
   py etnews_alert.py --dry-run   # 발송 없이 지금 매칭되는 기사 보기
   py etnews_alert.py             # 계속 실행 (interval_minutes 마다)
   py etnews_alert.py --once      # 한 번 확인 후 종료
   ```
3. Windows 작업 스케줄러로 10분마다 자동 실행 (이 폴더에서 PowerShell):
   ```powershell
   $dir = (Get-Location).Path
   $action = New-ScheduledTaskAction -Execute "py.exe" -Argument "etnews_alert.py --once" -WorkingDirectory $dir
   $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10)
   Register-ScheduledTask -TaskName "EtnewsAlert" -Action $action -Trigger $trigger
   ```
   해제: `Unregister-ScheduledTask -TaskName EtnewsAlert`

> A와 B를 동시에 돌리면 알림이 두 번 옵니다. 하나만 쓰세요.
