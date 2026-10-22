"""텔레그램 Bot API(sendMessage)를 직접 호출해 메시지를 보낸다."""
from __future__ import annotations

import logging
import sys

import httpx

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LEN = 4096  # 텔레그램 메시지 최대 길이


class NotifyError(Exception):
    pass


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, client: httpx.Client | None = None):
        self._url = API_URL.format(token=token)
        self._chat_id = chat_id
        self._client = client or httpx.Client(timeout=10)

    def send(self, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        """HTML 형식 메시지를 보낸다. buttons=[(라벨, https URL), ...] 는 메시지 아래 한 줄로 붙는다.
        실패하면 NotifyError."""
        payload = {
            "chat_id": self._chat_id,
            "text": text[:MAX_LEN],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": t, "url": u} for t, u in buttons]]}
        try:
            resp = self._client.post(self._url, json=payload)
        except httpx.HTTPError as e:
            # 예외 메시지에 토큰이 든 URL 이 들어갈 수 있어 타입만 남긴다
            raise NotifyError(f"텔레그램 요청 실패: {type(e).__name__}") from None
        if resp.status_code != 200 or not resp.json().get("ok"):
            raise NotifyError(f"텔레그램 응답 오류 {resp.status_code}: {resp.text[:200]}")
        log.info("텔레그램 전송 완료 (%d자)", len(text))


if __name__ == "__main__":
    # 사용법: python -m notifier "테스트 메시지"
    from config import load_telegram_credentials

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    text = " ".join(sys.argv[1:]) or "✅ 취소표 알림 봇 테스트 메시지입니다."
    token, chat_id = load_telegram_credentials()
    try:
        TelegramNotifier(token, chat_id).send(text)
    except NotifyError as e:
        sys.exit(f"전송 실패: {e}")
    print("전송 성공! 텔레그램을 확인하세요.")
