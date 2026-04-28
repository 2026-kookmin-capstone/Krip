"""
==============================================================================
                        AI 모듈 코드 컨벤션
==============================================================================

[ 디렉토리 구조 ]
---------------------------------------------------------------------------

    app/core/ai/
    ├── __init__.py                     # 컨벤션 문서
    │
    ├── {agent_name}/                   # AI 에이전트 단위 디렉토리
    │   ├── __init__.py                 # 에이전트 모듈 진입점
    │   ├── load.py                     # 모델 로더 & 호출기
    │   │
    │   └── v1/                         # 버전별 모델 구현
    │       ├── __init__.py
    │       ├── model.py                # 모델 추론 로직
    │       ├── train.py                # 모델 학습 스크립트
    │       └── {agent_name}_v1.        # 학습된 모델 파일
    │
    │   └── v2/                         # 다음 버전 (필요 시 추가)
    │       ├── ...
    │       └── {agent_name}_v2.
    │
    └── another_agent/                  # 또 다른 AI 에이전트도 위와 동일
        └── ...

---------------------------------------------------------------------------

[ 1. 에이전트 디렉토리: /{agent_name}/ ]
---------------------------------------------------------------------------

    - 각 AI 에이전트는 반드시 /ai/ 하위에 독립된 디렉토리를 가져야 한다.
    - 디렉토리명은 snake_case로 에이전트 이름에 맞게 작성한다.
      예) chatbot, super_chatbot

    예시:
        app/core/ai/chatbot/
        app/core/ai/super_chatbot/

---------------------------------------------------------------------------

[ 2. load.py — 모델 로더 & 호출기 ]
---------------------------------------------------------------------------

    load.py는 싱글톤 클래스로 다음 두 가지 책임을 가진다:
      (1) load() 서버 시작 시 모델을 메모리에 로드한다.
      (2) invoke() 메서드를 통해 추론을 실행한다.

    규칙:
      - 클래스는 반드시 싱글톤이어야 한다 (프로세스당 하나의 인스턴스).
      - load()은 서버 시작 시 한 번만 호출된다.
      - invoke()는 모든 추론 요청의 단일 진입점이다.
      - 모델 아키텍처나 학습 로직을 포함하지 않는다.
        메인 로직은 v{n}/model.py에 위임한다.

    예시 템플릿:

        from app.core.ai.{agent_name}.v1.model import {AgentName}Model


        class {AgentName}:
            _instance = None

            def __new__(cls):
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
                return cls._instance

            def load(self) -> None:
                '''서버 시작 시 한 번 호출된다.'''
                if self._initialized:
                    return
                self._model = {AgentName}Model()
                self._model.load_weights()
                self._initialized = True

            def invoke(self, input_data: dict) -> dict:
                '''추론 요청의 단일 진입점.'''
                if not self._initialized:
                    raise RuntimeError("모델이 로드되지 않았습니다.")
                return self._model.predict(input_data)


    서버 시작 시 연동 (예: main.py 또는 lifespan):

        from app.core.ai.{agent_name}.load import {AgentName}

        model = {AgentName}()
        model.load()

---------------------------------------------------------------------------

[ 3. v{n}/ — 버전별 모델 구현 ]
---------------------------------------------------------------------------

    각 모델 버전은 독립된 버전 디렉토리에 존재한다.
    기존 배포를 깨뜨리지 않고 안전하게 반복 개선할 수 있다.

    v{n}/
    ├── __init__.py
    ├── model.py                # 모델 핵심 로직
    ├── train.py                # 학습 스크립트 (재현 가능)
    └── {agent_name}_v{n}.      # 학습된 모델

---------------------------------------------------------------------------

[ 4. 버전 업그레이드 흐름 ]
---------------------------------------------------------------------------

    v1 -> v2 업그레이드 시:

    1단계:  v2/ 디렉토리 생성 후 model.py, train.py 작성
    2단계:  학습 실행 후 {agent_name}_v2. 저장
    3단계:  load.py의 import 변경:
              from ...v1.model import ...  ->  from ...v2.model import ...
    4단계:  invoke()로 검증 — API 변경 불필요
    5단계:  v1/ 디렉토리는 롤백 대비 유지

---------------------------------------------------------------------------
"""
