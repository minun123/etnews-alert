"""전자신문(etnews.com) 키워드 알림 앱.

RSS 피드를 주기적으로 확인해서, 설정한 키워드가 들어간 새 기사를
Gmail 및/또는 카카오톡(나에게 보내기)으로 보내줍니다.

사용법:
    py etnews_alert.py            # 계속 실행 (interval_minutes 마다 확인)
    py etnews_alert.py --once     # 한 번만 확인하고 종료 (작업 스케줄러용)
    py etnews_alert.py --dry-run  # 발송하지 않고 매칭 결과만 출력
    py etnews_alert.py --test     # 테스트 메시지를 발송해서 설정 확인
"""

import argparse
import html
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
SEEN_PATH = BASE_DIR / "seen.json"
KAKAO_TOKEN_PATH = BASE_DIR / "kakao_token.json"
SECRETS_PATH = BASE_DIR / "secrets.json"
STATE_PATH = BASE_DIR / "state.json"          # 하루 요약 대기 목록
ARCHIVE_PATH = BASE_DIR / "docs" / "articles.json"  # 모바일 페이지 데이터
KST = timezone(timedelta(hours=9))

USER_AGENT = "Mozilla/5.0 (etnews-keyword-alert)"


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_config():
    """config.json(공개 설정) + 비밀값.

    비밀값 우선순위: 환경변수(GitHub Secrets) > secrets.json(로컬) > config.json
    """
    cfg = load_json(CONFIG_PATH, None)
    if cfg is None:
        sys.exit("config.json 이 없습니다. config.example.json 을 복사해서 만드세요.")
    sec = load_json(SECRETS_PATH, {})
    env = os.environ.get
    g = cfg.setdefault("gmail", {})
    k = cfg.setdefault("kakao", {})

    g["sender"] = env("GMAIL_SENDER") or sec.get("gmail_sender") or g.get("sender", "")
    g["app_password"] = (env("GMAIL_APP_PASSWORD") or sec.get("gmail_app_password")
                         or g.get("app_password", ""))
    to = env("GMAIL_TO") or sec.get("gmail_to") or g.get("to") or g["sender"]
    if isinstance(to, str):
        to = [t.strip() for t in to.split(",") if t.strip()]
    g["to"] = to

    k["rest_api_key"] = (env("KAKAO_REST_API_KEY") or sec.get("kakao_rest_api_key")
                         or k.get("rest_api_key", ""))
    k["client_secret"] = (env("KAKAO_CLIENT_SECRET") or sec.get("kakao_client_secret")
                          or k.get("client_secret", ""))
    return cfg


# ---------------------------------------------------------------- RSS ----

def clean_text(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_feed(url, tries=3):
    """연결이 가끔 끊기므로(특히 GitHub 서버에서) 몇 번 다시 시도"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            break
        except Exception as e:
            if i == tries - 1:
                raise
            log(f"  재시도 {i + 1}/{tries - 1} ({url}): {e}")
            time.sleep(3 * (i + 1))  # 최악의 경우에도 피드 5개 약 3분 (작업 제한 5분 안)
    root = ET.fromstring(raw)
    items = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        if not link:
            continue
        pub = it.findtext("pubDate") or ""
        try:
            pub_dt = parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            pub_dt = None
        items.append({
            "title": clean_text(it.findtext("title")),
            "link": link,
            "description": clean_text(it.findtext("description")),
            "pub": pub_dt.strftime("%Y-%m-%d %H:%M") if pub_dt else "",
        })
    return items


def find_keywords(article, keywords, search_description):
    text = article["title"]
    if search_description:
        text += " " + article["description"]
    text_l = text.lower()
    return [k for k in keywords if k.lower() in text_l]


# -------------------------------------------------------------- Gmail ----

def send_gmail(cfg, matches):
    """matches: list of (article, [keywords])"""
    g = cfg["gmail"]
    subject = f"[전자신문 알림] {len(matches)}건 - " + ", ".join(
        sorted({k for _, ks in matches for k in ks}))
    rows = []
    for a, ks in matches:
        desc = a["description"]
        if len(desc) > 200:
            desc = desc[:200] + "…"
        rows.append(
            f'<div style="margin-bottom:18px">'
            f'<a href="{html.escape(a["link"])}" style="font-size:16px;font-weight:bold">'
            f'{html.escape(a["title"])}</a><br>'
            f'<span style="color:#888;font-size:12px">{html.escape(a["pub"])} · 키워드: '
            f'{html.escape(", ".join(ks))}</span>'
            f'<p style="margin:6px 0;color:#333">{html.escape(desc)}</p></div>'
        )
    page_url = cfg.get("page_url", "")
    header = (f'<p><a href="{html.escape(page_url)}" style="font-size:15px">'
              f'📱 내 관심 기사 페이지 열기</a></p><hr>') if page_url else ""
    body = "<html><body>" + header + "".join(rows) + "</body></html>"

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = g["sender"]
    msg["To"] = ", ".join(g["to"])

    with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                          context=ssl.create_default_context()) as s:
        s.login(g["sender"], g["app_password"].replace(" ", ""))
        s.sendmail(g["sender"], g["to"], msg.as_string())
    log(f"Gmail 발송 완료: {len(matches)}건")


# -------------------------------------------------------------- Kakao ----

def _post_form(url, data, headers=None):
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
                 **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code} {e.read().decode(errors='replace')}") from None


def kakao_refresh_token(cfg):
    k = cfg["kakao"]
    env_rt = os.environ.get("KAKAO_REFRESH_TOKEN")  # GitHub Actions용
    tok = load_json(KAKAO_TOKEN_PATH, None)
    if not tok and env_rt:
        tok = {"refresh_token": env_rt}
    if not tok:
        raise RuntimeError("카카오 토큰이 없습니다. 먼저 `py kakao_auth.py` 를 실행하세요.")
    data = {"grant_type": "refresh_token",
            "client_id": k["rest_api_key"],
            "refresh_token": tok["refresh_token"]}
    if k.get("client_secret"):
        data["client_secret"] = k["client_secret"]
    new = _post_form("https://kauth.kakao.com/oauth/token", data)

    if env_rt and not KAKAO_TOKEN_PATH.exists():
        # GitHub Actions: 토큰을 파일에 쓰지 않고, 새 refresh token이 오면 Secret을 갱신
        if "refresh_token" in new:
            update_github_secret("KAKAO_REFRESH_TOKEN", new["refresh_token"])
        return new["access_token"]

    tok["access_token"] = new["access_token"]
    if "refresh_token" in new:  # 만료 1개월 이내면 새 refresh token이 같이 옴
        tok["refresh_token"] = new["refresh_token"]
    tok["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_json(KAKAO_TOKEN_PATH, tok)
    return tok["access_token"]


def update_github_secret(name, value):
    pat = os.environ.get("GH_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not (pat and repo):
        log(f"⚠ 카카오 refresh token이 새로 발급됐지만 GH_PAT이 없어 {name} Secret을 "
            "갱신하지 못했습니다. 약 1개월 안에 `py kakao_auth.py`로 다시 발급받아 "
            "Secret을 직접 바꿔주세요.")
        return
    r = subprocess.run(["gh", "secret", "set", name, "--repo", repo],
                       input=value, text=True, capture_output=True,
                       env={**os.environ, "GH_TOKEN": pat})
    if r.returncode == 0:
        log(f"{name} Secret 자동 갱신 완료")
    else:
        log(f"⚠ {name} Secret 갱신 실패: {r.stderr.strip()}")


def send_kakao(cfg, matches):
    access = kakao_refresh_token(cfg)  # access token은 6시간이라 매번 갱신
    for a, ks in matches:
        text = f"[{', '.join(ks)}] {a['title']}"
        if a["description"]:
            text += "\n\n" + a["description"]
        if len(text) > 195:  # 카카오 text 템플릿 최대 200자
            text = text[:195] + "…"
        template = {
            "object_type": "text",
            "text": text,
            "link": {"web_url": a["link"], "mobile_web_url": a["link"]},
            "button_title": "기사 보기",
        }
        res = _post_form(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            {"template_object": json.dumps(template, ensure_ascii=False)},
            {"Authorization": f"Bearer {access}"})
        if res.get("result_code") != 0:
            raise RuntimeError(f"카카오 발송 실패: {res}")
        time.sleep(0.3)
    log(f"카카오톡 발송 완료: {len(matches)}건")


def send_kakao_digest(cfg, matches):
    """여러 기사를 카카오톡 메시지 1개로 요약 (하루 요약 모드)"""
    access = kakao_refresh_token(cfg)
    page_url = cfg.get("page_url") or matches[0][0]["link"]
    lines = [f"📰 오늘의 관심 기사 {len(matches)}건"]
    for a, _ in matches:
        line = "· " + a["title"]
        if len("\n".join(lines + [line])) > 180:
            lines.append(f"…외 {len(matches) - (len(lines) - 1)}건")
            break
        lines.append(line)
    template = {
        "object_type": "text",
        "text": "\n".join(lines)[:199],
        "link": {"web_url": page_url, "mobile_web_url": page_url},
        "button_title": "모아보기",
    }
    res = _post_form(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        {"template_object": json.dumps(template, ensure_ascii=False)},
        {"Authorization": f"Bearer {access}"})
    if res.get("result_code") != 0:
        raise RuntimeError(f"카카오 발송 실패: {res}")
    log(f"카카오톡 요약 발송 완료: {len(matches)}건")


# ------------------------------------------------------------ Archive ----

def now_kst():
    return datetime.now(KST)


def update_archive(cfg, matches):
    """매칭된 기사를 docs/articles.json 에 누적 (모바일 페이지가 읽는 파일)"""
    data = load_json(ARCHIVE_PATH, {"articles": []})
    by_link = {a["link"]: a for a in data.get("articles", [])}
    added = 0
    stamp = now_kst().strftime("%Y-%m-%d %H:%M")
    for a, ks in matches:
        if a["link"] in by_link:
            # 키워드가 추가됐으면 반영
            old = by_link[a["link"]]
            old["keywords"] = sorted(set(old.get("keywords", [])) | set(ks))
            continue
        by_link[a["link"]] = {
            "title": a["title"], "link": a["link"],
            "description": a["description"][:300],
            "pub": a["pub"] or stamp, "found": stamp, "keywords": ks,
        }
        added += 1
    arts = sorted(by_link.values(), key=lambda x: x["pub"], reverse=True)
    arts = arts[: int(cfg.get("max_articles", 1000))]
    ARCHIVE_PATH.parent.mkdir(exist_ok=True)
    save_json(ARCHIVE_PATH, {
        "updated": now_kst().strftime("%Y-%m-%d %H:%M"),
        "keywords": cfg["keywords"],
        "articles": arts,
    })
    return added


# --------------------------------------------------------------- Main ----

def notify(cfg, matches, digest=False):
    ok = True
    if cfg.get("gmail", {}).get("enabled"):
        try:
            send_gmail(cfg, matches)
        except Exception as e:
            ok = False
            log(f"Gmail 발송 오류: {e}")
    if cfg.get("kakao", {}).get("enabled"):
        try:
            if digest:
                send_kakao_digest(cfg, matches)
            else:
                send_kakao(cfg, matches)
        except Exception as e:
            ok = False
            log(f"카카오톡 발송 오류: {e}")
    return ok


def send_daily_digest_if_due(cfg, state, dry_run=False):
    """notify_mode=daily: 매일 daily_hour(한국시간) 이후 첫 실행 때 한 번 발송"""
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    if now.hour < int(cfg.get("daily_hour", 8)) or state.get("last_digest") == today:
        return
    pending = state.get("pending", [])
    if not pending:
        state["last_digest"] = today
        return
    log(f"하루 요약 발송: {len(pending)}건")
    if dry_run:
        return
    matches = [(a, a.get("keywords", [])) for a in pending]
    if notify(cfg, matches, digest=True):
        state["pending"] = []
        state["last_digest"] = today


def check_once(cfg, dry_run=False):
    keywords = [k.strip() for k in cfg["keywords"] if k.strip()]
    cfg["keywords"] = keywords
    mode = cfg.get("notify_mode", "daily")  # instant | daily | off
    first_run = not SEEN_PATH.exists()
    seen = load_json(SEEN_PATH, {})
    state = load_json(STATE_PATH, {})

    articles = {}
    for url in cfg["feeds"]:
        try:
            for a in fetch_feed(url):
                articles.setdefault(a["link"], a)
        except Exception as e:
            log(f"피드 읽기 실패 ({url}): {e}")

    if not articles:
        # 전부 실패: 아무것도 바꾸지 않고 다음 실행 때 다시 시도
        log("피드를 하나도 읽지 못했습니다. 다음 실행 때 다시 시도합니다.")
        return

    new = [a for link, a in articles.items() if link not in seen]
    matches = []
    for a in new:
        ks = find_keywords(a, keywords, cfg.get("search_description", True))
        if ks:
            matches.append((a, ks))

    log(f"기사 {len(articles)}개 확인, 새 기사 {len(new)}개, 키워드 매칭 {len(matches)}개")

    for a, ks in matches:
        log(f"  ▶ [{', '.join(ks)}] {a['title']}  {a['link']}")

    if dry_run:
        if mode == "daily":
            send_daily_digest_if_due(cfg, state, dry_run=True)
        return

    # 1) 모바일 페이지용 보관함에 저장 (첫 실행 포함 항상)
    added = update_archive(cfg, matches)
    if added:
        log(f"보관함에 {added}건 추가")

    # 2) 알림
    if first_run and not cfg.get("notify_on_first_run", False):
        log("첫 실행: 지금 올라와 있는 기사는 보관함에만 넣고 알림은 보내지 않습니다.")
        matches_to_send = []
    else:
        matches_to_send = matches

    sent_ok = True
    if mode == "instant" and matches_to_send:
        sent_ok = notify(cfg, matches_to_send)
    elif mode == "daily":
        pending = state.setdefault("pending", [])
        have = {p["link"] for p in pending}
        for a, ks in matches_to_send:
            if a["link"] not in have:
                pending.append({**a, "keywords": ks})
        send_daily_digest_if_due(cfg, state)
    save_json(STATE_PATH, state)

    if sent_ok:
        now = datetime.now().isoformat(timespec="seconds")
        for a in new:
            seen[a["link"]] = now
    else:
        # 발송 실패한 매칭 기사는 seen에 넣지 않아 다음 회차에 재시도
        failed = {a["link"] for a, _ in matches_to_send}
        now = datetime.now().isoformat(timespec="seconds")
        for a in new:
            if a["link"] not in failed:
                seen[a["link"]] = now

    # seen 목록이 무한히 커지지 않게 최근 5000개만 유지
    if len(seen) > 5000:
        seen = dict(sorted(seen.items(), key=lambda kv: kv[1])[-5000:])
    save_json(SEEN_PATH, seen)


def main():
    ap = argparse.ArgumentParser(description="전자신문 키워드 알림")
    ap.add_argument("--once", action="store_true", help="한 번만 확인하고 종료")
    ap.add_argument("--dry-run", action="store_true", help="발송 없이 매칭 결과만 출력")
    ap.add_argument("--test", action="store_true", help="테스트 메시지 발송")
    args = ap.parse_args()

    cfg = load_config()

    if args.test:
        sample = {"title": "전자신문 키워드 알림 테스트 메시지입니다",
                  "link": "https://www.etnews.com",
                  "description": "이 메시지가 보이면 설정이 정상입니다.",
                  "pub": datetime.now().strftime("%Y-%m-%d %H:%M")}
        notify(cfg, [(sample, ["테스트"])])
        return

    if args.once or args.dry_run:
        check_once(cfg, dry_run=args.dry_run)
        return

    interval = max(1, int(cfg.get("interval_minutes", 10)))
    log(f"감시 시작: 키워드 {cfg['keywords']} / {interval}분 간격 (Ctrl+C로 종료)")
    while True:
        try:
            check_once(cfg)
        except Exception as e:
            log(f"오류: {e}")
        time.sleep(interval * 60)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        main()
    except KeyboardInterrupt:
        log("종료")
