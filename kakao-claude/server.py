"""
카카오톡 채널 차트 분석 파이프라인
[카카오톡 채널 이미지 수신] → [Claude 혼마 무네히사 분석] → [카카오톡 채널 답장]

카카오 i 오픈빌더 스킬 서버로 동작합니다.
설정: 오픈빌더 → 스킬 → 서버 URL → http://YOUR_SERVER/webhook
"""

import os
import base64
import requests
import anthropic
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PORT = int(os.getenv("PORT", "5000"))

app = Flask(__name__)

# 혼마 무네히사 분석 프롬프트
HONMA_PROMPT = """당신은 18세기 일본의 전설적인 쌀 선물거래 상인 혼마 무네히사(本間宗久)의 통찰과 현대 기술적 분석을 결합한 최고의 차트 분석 전문가입니다.

아래 차트 이미지를 보고 다음 항목을 순서대로 분석해 주세요.

## 1. 캔들 패턴 분석 (혼마 무네히사 기법)
- 현재 캔들 패턴 이름과 의미
- 상승/하락 반전 신호 여부
- 도지, 망치형, 유성형 등 주요 패턴 식별

## 2. 추세 분석
- 단기(5일) / 중기(20일) / 장기(60일) 이동평균선 위치 관계
- 골든크로스 / 데드크로스 여부
- 현재 추세 방향과 강도

## 3. 거래량 분석
- 거래량 증감 추이
- 거래량 대비 가격 움직임의 신뢰도

## 4. 보조지표
- RSI: 과매수(70 이상) / 과매도(30 이하) 여부
- MACD: 시그널선 돌파 여부, 히스토그램 방향

## 5. 지지/저항 구간
- 핵심 지지선과 저항선 가격대
- 돌파 시 다음 목표가

## 6. 종합 진단 및 전략
- 현재 포지션 평가: 매수 / 매도 / 관망
- 진입 추천 가격대
- 손절 기준선
- 목표 수익 구간

⚠️ 본 분석은 투자 참고용이며, 최종 투자 판단은 본인 책임입니다."""


def analyze_with_claude(image_url: str) -> str:
    """이미지 URL을 받아 Claude로 분석 후 결과 반환"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 이미지 다운로드
    resp = requests.get(image_url, timeout=15)
    resp.raise_for_status()
    b64 = base64.standard_b64encode(resp.content).decode("utf-8")

    # Content-Type으로 미디어타입 판별
    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    if content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        content_type = "image/jpeg"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": content_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": HONMA_PROMPT}
                ],
            }
        ],
    )
    return message.content[0].text


def kakao_response(text: str) -> dict:
    """카카오 i 오픈빌더 응답 포맷"""
    # 카카오 말풍선 최대 1000자 제한
    chunks = [text[i:i+990] for i in range(0, min(len(text), 2970), 990)]
    outputs = [{"simpleText": {"text": chunk}} for chunk in chunks]
    return {
        "version": "2.0",
        "template": {"outputs": outputs}
    }


def kakao_error(message: str) -> dict:
    return kakao_response(f"⚠️ {message}")


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    카카오 i 오픈빌더 스킬 서버 엔드포인트
    사용자가 카카오톡 채널에 이미지를 보내면 오픈빌더가 이 URL을 호출합니다.
    """
    try:
        body = request.get_json(force=True)

        # 1. 이미지 URL 추출
        # 오픈빌더에서 이미지 업로드 시 action.params.image 또는 userRequest.utterance에 URL 포함
        image_url = None

        # 방법 A: 파라미터로 이미지 URL이 넘어오는 경우 (오픈빌더 엔티티 설정 시)
        params = body.get("action", {}).get("params", {})
        if "image" in params:
            image_url = params["image"]

        # 방법 B: utterance에 직접 URL이 있는 경우
        if not image_url:
            utterance = body.get("userRequest", {}).get("utterance", "")
            if utterance.startswith("http") and any(
                ext in utterance.lower() for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]
            ):
                image_url = utterance.strip()

        # 방법 C: 카카오 이미지 블록 payload
        if not image_url:
            payload = body.get("userRequest", {}).get("callbackUrl", "")
            if payload:
                image_url = payload

        if not image_url:
            return jsonify(kakao_error(
                "차트 이미지를 인식하지 못했습니다.\n이미지를 직접 전송해 주세요."
            ))

        print(f"이미지 수신: {image_url[:80]}...")

        # 2. Claude 분석
        analysis = analyze_with_claude(image_url)
        print(f"분석 완료: {len(analysis)}자")

        # 3. 카카오톡 채널로 결과 답장
        return jsonify(kakao_response(f"📊 혼마 무네히사 차트 분석\n{'─'*20}\n\n{analysis}"))

    except requests.exceptions.RequestException as e:
        print(f"이미지 다운로드 오류: {e}")
        return jsonify(kakao_error("이미지를 불러오지 못했습니다. 다시 시도해 주세요."))
    except Exception as e:
        print(f"처리 오류: {e}")
        return jsonify(kakao_error("분석 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."))


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print("=" * 50)
    print("카카오톡 채널 차트 분석 서버 시작")
    print(f"웹훅 URL: http://YOUR_SERVER_IP:{PORT}/webhook")
    print("오픈빌더 → 스킬 메뉴에 위 URL을 등록하세요.")
    print("=" * 50)
    app.run(host="0.0.0.0", port=PORT, debug=False)
