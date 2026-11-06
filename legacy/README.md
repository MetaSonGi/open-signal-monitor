# 초기 DB 호환 계층

`storage.py`는 초기 `monitor.sqlite3` 형식의 읽기·내보내기 호환성과 회귀 검증을 위해 보존합니다. 현재 실행 메뉴에서는 사용하지 않습니다. 현재 수집 기록은 `operations_db.py`와 `manufacturing.sqlite3`가 담당합니다.

루트의 `storage.py`는 기존 import 호환용 별칭입니다. 기존 DB를 삭제하거나 자동 변환하지 않습니다. 새 기능·새 수집 경로를 이 폴더에 추가하지 않습니다.
