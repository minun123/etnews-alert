"""카카오 '나에게 보내기' 최초 인증 (한 번만 실행).

1. 브라우저가 열리면 카카오 로그인 후 '동의하고 계속하기'
2. 자동으로 kakao_token.json 이 만들어집니다.
   (refresh token 유효기간은 약 2개월이며, 앱이 실행되면서 자동 연장됩니다)
"""

import json
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from etnews_alert import KAKAO_TOKEN_PATH, _post_form, load_config, save_json  # noqa: E402

cfg = load_config()
k = cfg["kakao"]
if not k.get("rest_api_key"):
    sys.exit("카카오 REST API 키가 없습니다. secrets.json 의 kakao_rest_api_key 를 채워주세요.")
redirect_uri = k.get("redirect_uri", "http://localhost:5000/callback")
parsed = urllib.parse.urlparse(redirect_uri)

auth_url = "https://kauth.kakao.com/oauth/authorize?" + urllib.parse.urlencode({
    "client_id": k["rest_api_key"],
    "redirect_uri": redirect_uri,
    "response_type": "code",
    "scope": "talk_message",
})

result = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in q:
            result["code"] = q["code"][0]
            msg = "인증 완료! 이 창은 닫아도 됩니다."
        else:
            result["error"] = q.get("error_description", q.get("error", ["unknown"]))[0]
            msg = "인증 실패: " + result["error"]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<h2>{msg}</h2>".encode())

    def log_message(self, *a):
        pass


print("브라우저에서 카카오 로그인 후 동의해주세요...")
print("(브라우저가 안 열리면 아래 주소를 직접 여세요)\n" + auth_url + "\n")
webbrowser.open(auth_url)

server = HTTPServer((parsed.hostname, parsed.port or 80), Handler)
while not result:
    server.handle_request()

if "error" in result:
    sys.exit("인증 실패: " + result["error"])

data = {"grant_type": "authorization_code",
        "client_id": k["rest_api_key"],
        "redirect_uri": redirect_uri,
        "code": result["code"]}
if k.get("client_secret"):
    data["client_secret"] = k["client_secret"]
tok = _post_form("https://kauth.kakao.com/oauth/token", data)
save_json(KAKAO_TOKEN_PATH, {"access_token": tok["access_token"],
                             "refresh_token": tok["refresh_token"]})
print("kakao_token.json 저장 완료! 이제 `py etnews_alert.py --test` 로 확인해보세요.")
print("GitHub Actions에서 쓰려면 kakao_token.json 안의 refresh_token 값을 "
      "KAKAO_REFRESH_TOKEN Secret에 넣으세요.")
