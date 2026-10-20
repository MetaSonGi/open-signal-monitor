"""Deterministic, synthetic teaching fixtures. No industrial training data."""
import json
import math
from datetime import datetime,timezone,timedelta


SCENARIOS={
 'quality':{'title':'01 · 품질 이상 탐지','focus':'정상 기준선, 오탐/미탐, LOT 분리','question':'민감도를 높이면 불량 감지와 정상 오탐은 어떻게 바뀔까요?',
  'steps':'진동 센서를 선택해 3σ와 0.5σ를 비교하세요. 마지막 3개 평가 LOT 중 첫 LOT는 정상입니다.','signals':[(1,'진동 RMS','mm/s'),(2,'온도','C')]},
 'drift':{'title':'02 · 데이터 드리프트','focus':'환경·센서 조건 변화와 재검증','question':'값이 변했다는 이유만으로 제품 불량이라고 할 수 있을까요?',
  'steps':'온도 트렌드의 평가 구간을 보세요. 모든 LOT 판정은 normal인데 정상 오탐이 늘어납니다.','signals':[(1,'온도','C')]},
 'energy':{'title':'03 · 생산량을 고려한 에너지 분석','focus':'운전 맥락과 특징 설계','question':'생산량이 늘어 사용 전력이 커졌다면 비효율일까요?',
  'steps':'소비 전력과 개당 에너지를 각각 학습하세요. 평가 첫 LOT는 생산량만 늘어난 정상 LOT입니다.','signals':[(1,'소비 전력','W'),(2,'생산 속도','part/h'),(3,'개당 에너지','Wh/part')]},
 'data_quality':{'title':'04 · 누락·센서 오류와 데이터 품질','focus':'NULL, 품질 마스크, 전처리','question':'센서 오류를 0으로 채우거나 그대로 학습하면 어떤 문제가 생길까요?',
  'steps':'회색 오류·누락 구간과 파란 정상값을 비교하세요. good 값만 학습하며 실제 제품 판정은 모두 normal입니다.','signals':[(1,'온도','C')]},
}


def seed_scenario(lab,key):
    if key not in SCENARIOS:raise ValueError('알 수 없는 예제입니다.')
    spec=SCENARIOS[key];dataset='lesson-'+key+'-v1';asset='LESSON-'+key.upper()
    base=datetime.now(timezone.utc)-timedelta(hours=10)
    with lab.connect() as db:
        exists=db.execute('SELECT count(*) FROM samples WHERE dataset=?',(dataset,)).fetchone()[0]
        if exists:return dict(spec,key=key,dataset=dataset,asset=asset,rows=exists)
        db.execute('INSERT OR IGNORE INTO equipment VALUES(?,?)',(asset,spec['title']))
        db.execute("INSERT OR IGNORE INTO items VALUES('LESSON-PART','실습 부품')")
        binding=db.execute('INSERT INTO bindings(collector_asset,asset_code,active,created_utc) VALUES(?,?,0,?)',('SYNTHETIC-'+key,asset,base.isoformat())).lastrowid
        sample_id=0
        for j in range(10):
            start=base+timedelta(minutes=10*j);end=start+timedelta(minutes=5)
            label='defect' if key in {'quality','energy'} and j>=8 else 'normal'
            job=db.execute("INSERT INTO jobs(code,item_code,asset_code,lot,target,status,started_utc,ended_utc,result_label,created_utc) VALUES(?,'LESSON-PART',?,?,24,'completed',?,?,?,?)",
                (f'{asset}-WO-{j+1:02}',asset,f'{asset}-LOT-{j+1:02}',start.isoformat(timespec='milliseconds'),end.isoformat(timespec='milliseconds'),label,base.isoformat())).lastrowid
            db.execute("INSERT INTO pop_events(event_key,job_id,at_utc,kind,good,bad,operator,reason,origin) VALUES(?,?,?,'report',?,?,'교육 예제','합성 데이터','synthetic')",
                (f'example:{dataset}:{j}',job,end.isoformat(timespec='milliseconds'),24 if label=='normal' else 0,24 if label=='defect' else 0))
            for i in range(24):
                noise=math.sin(i*1.7+j*.23);stamp=(start+timedelta(seconds=i*10)).isoformat(timespec='milliseconds')
                load=(30 if j>=7 else 10)+noise
                specific=(7 if j>=8 else 5)+.08*noise
                for sid,name,unit in spec['signals']:
                    quality='good'
                    if key=='quality':value=(3+.08*noise+(.8 if label=='defect' else 0)) if sid==1 else 25+.3*noise+(2 if label=='defect' else 0)
                    elif key=='drift':value=20+.12*noise+(2+(j-7)*.8 if j>=7 else 0)
                    elif key=='energy':value={1:load*specific,2:load,3:specific}[sid]
                    else:
                        value=25+.15*noise
                        if i in {3,4,5}:value=None;quality='missing'
                        elif i in {12,13}:value=90;quality='device_bad'
                        elif i==18:quality='stale'
                    sample_id+=1
                    db.execute('INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)',(dataset,sample_id,binding,asset,sid,name,unit,stamp,stamp,value,quality))
        db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('scenario:'+key,json.dumps(dict(spec,key=key,dataset=dataset,asset=asset),ensure_ascii=False)))
    return dict(spec,key=key,dataset=dataset,asset=asset,rows=sample_id)


def bottleneck(cycles,availability=.9,yield_rate=.98,hours=8):
    if not cycles or not all(isinstance(c,(int,float)) and math.isfinite(c) and c>0 for c in cycles):raise ValueError('각 공정 주기는 양수여야 합니다.')
    if not 0<availability<=1 or not 0<yield_rate<=1 or not 0<hours<=168:raise ValueError('가동률·양품률은 0 초과 1 이하, 시간은 0 초과 168 이하입니다.')
    bottleneck_index=max(range(len(cycles)),key=lambda i:cycles[i])
    hourly=3600/cycles[bottleneck_index]
    return {'bottleneck':bottleneck_index+1,'ideal_per_hour':hourly,'expected_good':hourly*hours*availability*yield_rate,
        'assumptions':'steady-state serial line; adequate buffers; no startup/transfer/changeover effects'}


EVIDENCE=[
 {'id':'EDU-M01','title':'진동 상승 확인 절차','keywords':['진동','베어링','vibration','마모'],'text':'진동 상승을 확인하면 장착 상태·운전 속도·센서 품질을 먼저 비교합니다. 장치 정지·정비는 담당자의 승인과 장비 절차를 따릅니다.'},
 {'id':'EDU-M02','title':'전력과 생산량 비교','keywords':['전력','에너지','생산량','energy','power'],'text':'소비 전력만 비교하지 말고 생산량과 운전 상태를 함께 확인합니다. 같은 조건의 개당 에너지를 비교한 뒤 원인을 검토합니다.'},
 {'id':'EDU-M03','title':'누락·시간 동기화 확인','keywords':['누락','시간','지연','missing','통신'],'text':'누락은 0으로 바꾸지 않습니다. 통신 상태, 센서 품질, 장치 시각과 PC 시각을 확인하고 유효한 구간을 구분합니다.'},
 {'id':'EDU-M04','title':'조건 변화와 오탐 검토','keywords':['드리프트','오탐','조건','drift','환경'],'text':'값의 분포가 달라져도 곧바로 불량으로 단정하지 않습니다. 운전 조건과 센서 보정을 확인한 뒤 판정 데이터로 모델을 재검증합니다.'},
]


def retrieve(question):
    # Transparent lexical retrieval, not an LLM or semantic vector database.
    query=question.lower().strip()
    if not query:raise ValueError('질문을 입력하세요.')
    ranked=[]
    for doc in EVIDENCE:
        hits=[k for k in doc['keywords'] if k in query]
        if hits:ranked.append(dict(doc,score=len(hits),matched=hits))
    return sorted(ranked,key=lambda d:(-d['score'],d['id']))[:3]


def export_example(lab,key,path):
    from pathlib import Path
    spec=seed_scenario(lab,key);path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    count=lab.export_training(path,spec['dataset'])
    manifest=dict(spec,synthetic=True,rows=count,created_utc=datetime.now(timezone.utc).isoformat(),
        model_scope='educational deterministic fixture; not evidence of industrial predictive performance')
    path.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return count


if __name__=='__main__':
    import argparse
    import tempfile
    from pathlib import Path
    from .core import LabDB
    parser=argparse.ArgumentParser(description='Export synthetic manufacturing AI teaching datasets')
    parser.add_argument('--export-dir',required=True);parser.add_argument('--lesson',choices=list(SCENARIOS)+['all'],default='all')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        lab=LabDB(Path(temp)/'examples.sqlite3')
        for key in SCENARIOS if args.lesson=='all' else [args.lesson]:
            path=Path(args.export_dir)/(key+'.csv');print(f'{path}: {export_example(lab,key,path)} synthetic rows')
