"""FCM 단일 토큰 발송 테스트 스크립트.

사용법:
    python send_test.py
    python send_test.py --title "안녕" --body "테스트"
    python send_test.py --token <다른_토큰>
    FCM_CREDENTIALS_PATH=/path/to/sa.json python send_test.py
"""
import argparse
import os
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, exceptions, messaging


DEFAULT_TOKEN = (
    "covcGz6bkRNvEOSa9PNBFy:APA91bFBWRGv6pQTf77YJIj9UkynxCSgnZ0mGg-"
    "mpQnsFoZsVNPX2WRDZhUdDX-21A_YiRKHLC5yK_EDAZ0r8nStaucBkJuFUrAaNg2PcOnyL4W2LZIvLns"
)
DEFAULT_CREDENTIAL_PATH = Path(__file__).parent / "secrets" / "krip-firebase-secret-key.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FCM 발송 테스트")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="대상 FCM 디바이스 토큰")
    parser.add_argument("--title", default="Krip 테스트", help="알림 제목")
    parser.add_argument("--body", default="FCM 발송 테스트 메시지입니다.", help="알림 본문")
    parser.add_argument(
        "--credentials",
        default=os.environ.get("FCM_CREDENTIALS_PATH", str(DEFAULT_CREDENTIAL_PATH)),
        help="Firebase 서비스 계정 JSON 경로",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 발송 없이 검증만 수행 (FCM validate-only 모드)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    cred_path = Path(args.credentials)
    if not cred_path.exists():
        sys.exit(
            f"[ERROR] 서비스 계정 JSON을 찾을 수 없습니다: {cred_path}\n"
            "  Firebase 콘솔 → 프로젝트 설정 → 서비스 계정 → 새 비공개 키 생성\n"
            f"  파일을 위 경로에 저장하거나 --credentials / FCM_CREDENTIALS_PATH로 지정하세요."
        )

    firebase_admin.initialize_app(credentials.Certificate(str(cred_path)))

    message = messaging.Message(
        notification=messaging.Notification(title=args.title, body=args.body),
        token=args.token,
    )

    print(f"[INFO] target token : {args.token[:24]}...")
    print(f"[INFO] title        : {args.title}")
    print(f"[INFO] body         : {args.body}")
    print(f"[INFO] dry-run      : {args.dry_run}")

    try:
        response = messaging.send(message, dry_run=args.dry_run)
    except messaging.UnregisteredError:
        sys.exit("[FAIL] 토큰이 더 이상 유효하지 않습니다 (UNREGISTERED). 새 토큰을 발급받아 다시 시도하세요.")
    except messaging.SenderIdMismatchError:
        sys.exit("[FAIL] 토큰을 발급한 Firebase 프로젝트와 서비스 계정이 다릅니다 (SENDER_ID_MISMATCH).")
    except exceptions.InvalidArgumentError as e:
        sys.exit(f"[FAIL] 잘못된 요청: {e}")
    except exceptions.FirebaseError as e:
        sys.exit(f"[FAIL] Firebase 오류: code={e.code} detail={e}")
    except Exception as e:
        sys.exit(f"[FAIL] 발송 실패: {type(e).__name__}: {e}")

    print(f"[SUCCESS] message_id = {response}")


if __name__ == "__main__":
    main()
