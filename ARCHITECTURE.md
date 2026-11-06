# 프로젝트 역할과 중복 방지 기준

## 이 저장소의 책임

OpenSignal Monitor는 장치 데이터를 수집하고 생산·LOT·품질 이력과 연결하는 제조 데이터 실습 프로젝트입니다. 기능을 추가할 때 아래 담당 모듈을 확장합니다. 같은 데이터를 다른 DB에 별도 수집하는 앱이나 같은 역할의 새 저장소를 만들지 않습니다.

| 책임 | 구현 원본 | 데이터/인터페이스 |
|---|---|---|
| 공개 프로토콜 연결 | `protocol.py`, `adapters.py` | Modbus TCP, OPC UA, serial JSON, robot JSON bridge |
| 수집 실행·재연결 | `acquisition.py` | 센서 품질·수집 세션 |
| 수집 데이터·보정·구간 라벨 | `operations_db.py` | `data/manufacturing.sqlite3` |
| 수집기 UI | `operations_app.py` | 위 수집 엔진과 DB 사용 |
| MES/POP·장치 매핑·중복 수신 방지 | `learning/core.py` | `data/learning.sqlite3` |
| MES / POP / Studio 화면 | `learning/mes.py`, `learning/pop.py`, `learning/studio.py` | 공통 LabDB 사용, 별도 실행 |
| 합성 데이터·학습 평가 | `learning/scenarios.py`, `learning/lessons_ui.py` | LOT 분리·기준선·키워드 근거 검색 |
| 읽기 전용 연결 | `collector_api.py`, `web_snapshot.py` | loopback HTTP, DB 원본 변경 없음 |
| 웹 현황 | `docs/dashboard.js`, `docs/factory_ui.js` | 예제 또는 로컬 API 조회 |
| 웹 가상 라인·추세 수학 | `docs/factory_math.js` | 브라우저 내 순수 계산 |
| 실행 선택 | `launch.py` | 모든 시작 파일이 같은 진입점 사용 |

초기 `app.py`는 현재 수집기로 연결하는 호환 진입점입니다. 초기 DB 도구는 `legacy/`에 보존하며 새 앱으로 운영하지 않습니다. `storage.py`는 과거 import 호환용 별칭입니다.

수집기 생산 구간은 **센서 기록에 작업 맥락을 붙이는 메타데이터**이며, 학습 MES 작업지시는 **작업 상태·실적의 원본**입니다. 서로 자동 복제하거나 동일한 작업 원장으로 간주하지 않습니다. Studio의 명시적 장치 매핑과 동기화를 통해 연결합니다.

## GitHub 저장소별 경계

기존 저장소의 소개와 README를 확인해 정리한 역할입니다. 아래 링크는 관련 프로젝트 탐색용이며, 자동 연동이 구현되었다는 뜻은 아닙니다.

| 저장소 | 그곳에서 확장할 기능 | 이 저장소와의 관계 |
|---|---|---|
| [open-signal-monitor](https://github.com/MetaSonGi/open-signal-monitor) | 장치 수집, MES/POP, 생산·품질 현황, 제조 데이터 분석 | 제조 데이터의 중심 |
| [automotive-factory-twin-world](https://github.com/MetaSonGi/automotive-factory-twin-world) | 3D 공장·물류·로봇 시각화 | 향후 읽기 전용 데이터 소비자; 3D 공장 엔진을 여기서 복제하지 않음 |
| [robot-ai-lab](https://github.com/MetaSonGi/robot-ai-lab) | 로봇 이동시간 예측·AI 보정·강화학습 실습 | 로봇 동작 모델은 해당 저장소에서 발전 |
| [robot-lab](https://github.com/MetaSonGi/robot-lab) | 웹 로봇 제어·통신 실험 | 로봇 명령/제어 화면을 MES에 복제하지 않음 |
| [physical-ai-robot-digital-twin](https://github.com/MetaSonGi/physical-ai-robot-digital-twin) | ROS 2·로봇 학습·디지털트윈 | 실제 제어와 배포 계층은 별도 유지 |
| [metasongi-smartfactory-vr](https://github.com/MetaSonGi/metasongi-smartfactory-vr) | Unity 공장 조작·절차·평가 훈련 | VR 공간·3D 자산은 해당 저장소 담당 |
| [metasongi-learning-hub](https://github.com/MetaSonGi/metasongi-learning-hub) | 교육 과정·학습 경로·평가 이력 | MES 작업지시와 학습 수강 이력을 혼합하지 않음 |

## 분석 기능의 경계

- 데스크톱 병목 What-if는 가동률·양품률을 반영한 **정상상태 근사**입니다.
- 웹 라인 시뮬레이션은 **시작 시점·유한 버퍼·설비 대수**를 반영하는 3공정 이산 사건 모델입니다. 두 계산은 가정이 다르며 같은 결과를 약속하지 않습니다.
- 웹 추세 경고는 선형 외삽입니다. 고장 학습 모델과 구분합니다.
- 실제 창고 원장은 아직 없습니다. 예제 재고를 실제 데이터로 저장하지 않습니다.

## 후속 개발 위치

1. 실제 입출고·예약·LOT 재고: 이 저장소의 별도 재고 서비스로 구현하고 MES와 API로 연결. 현재 예제 테이블을 실재고로 승격하지 않음.
2. 고장·정비 이력 기반 분석: 현재 라벨·수집 데이터를 활용하는 분석 모듈로 추가. 검증 전 고장 확률이나 잔여수명을 제공하지 않음.
3. 3D 표시: 위 3D 저장소가 수집 API 또는 내보낸 파일을 소비하도록 연결. 코드·자산을 복사하지 않음.
4. 로봇 제어: 로봇 저장소가 담당. 이 수집 API에는 제어 명령을 추가하지 않음.

이 문서는 기능 경계와 연결 방향이며 미구현 기능의 완료 목록이 아닙니다.
