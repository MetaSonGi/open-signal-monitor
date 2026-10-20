import math
import statistics
import tkinter as tk
from tkinter import ttk,filedialog
from datetime import datetime
from .scenarios import SCENARIOS,seed_scenario,bottleneck,retrieve,export_example


class LessonsUI:
    def __init__(self,owner,tabs):
        self.owner=owner;self.tabs=tabs;self.model=None
        self.examples_page=ttk.Frame(tabs,padding=15);tabs.add(self.examples_page,text=' 예제 선택 ')
        self.trend_page=ttk.Frame(tabs,padding=15);tabs.add(self.trend_page,text=' 시계열 트렌드 ')
        self.context_page=ttk.Frame(tabs,padding=15);tabs.add(self.context_page,text=' 트윈·근거 검색 ')
        page=self.examples_page
        ttk.Label(page,text='데이터를 만들고, 추이를 보고, 결과를 비교하세요.',font=('맑은 고딕',16,'bold')).pack(anchor='w',pady=10)
        self.choices={v['title']:k for k,v in SCENARIOS.items()}
        self.lesson=tk.StringVar(value=next(iter(self.choices)))
        box=ttk.Combobox(page,textvariable=self.lesson,values=list(self.choices),state='readonly',width=65);box.pack(anchor='w',pady=10);box.bind('<<ComboboxSelected>>',lambda e:self.lesson_info())
        self.info=tk.Text(page,height=13,font=('맑은 고딕',11),wrap='word',state='disabled');self.info.pack(fill='x',pady=10)
        row=ttk.Frame(page);row.pack(fill='x')
        for title,action in [('예제 데이터 만들기',self.generate),('트렌드 보기',lambda:tabs.select(self.trend_page)),('학습·평가로 이동',lambda:tabs.select(owner.ai_page)),('이 예제 CSV 저장',self.export)]:ttk.Button(row,text=title,command=lambda a=action:owner.safe(a)).pack(side='left',padx=4,pady=8)
        ttk.Label(page,text='추가 체험: 트윈·근거 검색 탭에서 병목 공정과 생산량을 바꾸거나, 정비 질문에 맞는 근거를 찾아보세요.',wraplength=950).pack(anchor='w',pady=20)
        ttk.Label(page,text='모든 예제 데이터는 생성한 교육용 합성 데이터입니다. 실제 설비 성능·고장 예측 정확도의 근거로 사용할 수 없습니다.',foreground='#6b5660',wraplength=950).pack(anchor='w')
        self.lesson_info()

        page=self.trend_page
        self.feature_box=ttk.Combobox(page,textvariable=owner.feature,state='readonly',width=85);self.feature_box.pack(anchor='w',pady=8);self.feature_box.bind('<<ComboboxSelected>>',lambda e:self.draw())
        row=ttk.Frame(page);row.pack(fill='x')
        ttk.Label(row,text='이동평균 표본 수').pack(side='left');self.window=tk.StringVar(value='5')
        ttk.Combobox(row,textvariable=self.window,values=['3','5','10','20'],state='readonly',width=5).pack(side='left',padx=8)
        self.good_only=tk.BooleanVar(value=False)
        ttk.Checkbutton(row,text='good 품질만 그리기',variable=self.good_only,command=self.draw).pack(side='left')
        ttk.Button(row,text='갱신',command=lambda:owner.safe(self.draw)).pack(side='left',padx=8)
        self.caption=tk.StringVar(value='예제를 생성하거나 수집 데이터를 동기화하고 센서를 선택하세요.')
        ttk.Label(page,textvariable=self.caption,wraplength=1000).pack(anchor='w',pady=10)
        self.chart=tk.Canvas(page,bg='white',height=290,highlightthickness=0);self.chart.pack(fill='both',expand=True)
        self.chart.bind('<Configure>',lambda e:self.draw())
        ttk.Label(page,text='파랑: good 값  /  주황: 연속 good 구간의 이동평균  /  회색: 불량 품질·누락  /  초록 점선: 학습 기준선\n평가 시작 선은 학습 후 표시합니다. LOT 사이에는 선을 연결하지 않습니다. UTC 시각 축, 최근 2,000개 표본입니다.',wraplength=1000).pack(anchor='w',pady=8)

        inner=ttk.Notebook(self.context_page);inner.pack(fill='both',expand=True)
        twin=ttk.Frame(inner,padding=12);search=ttk.Frame(inner,padding=12);inner.add(twin,text=' 05 · 생산 라인 What-if ');inner.add(search,text=' 06 · 근거 검색 / RAG 기초 ')
        ttk.Label(twin,text='병목 공정을 바꾸면 양품 생산량은 얼마나 달라질까요?',font=('맑은 고딕',14,'bold')).pack(anchor='w',pady=10)
        self.cycles=[]
        for index,value in enumerate([30,60,45]):
            row=ttk.Frame(twin);row.pack(fill='x',pady=5);ttk.Label(row,text=f'공정 {index+1} 주기 (초)').pack(side='left')
            var=tk.DoubleVar(value=value);self.cycles.append(var)
            tk.Scale(row,from_=5,to=120,resolution=1,orient='horizontal',variable=var,length=450,command=lambda e:self.calculate()).pack(side='left',padx=15)
        row=ttk.Frame(twin);row.pack(fill='x',pady=8)
        ttk.Label(row,text='가동률 (%)').pack(side='left');self.availability=tk.StringVar(value='90');ttk.Entry(row,textvariable=self.availability,width=7).pack(side='left',padx=8)
        ttk.Label(row,text='양품률 (%)').pack(side='left');self.yield_rate=tk.StringVar(value='98');ttk.Entry(row,textvariable=self.yield_rate,width=7).pack(side='left',padx=8)
        ttk.Button(row,text='비교 계산',command=lambda:owner.safe(self.calculate)).pack(side='left',padx=12)
        self.twin_result=tk.StringVar();ttk.Label(twin,textvariable=self.twin_result,font=('맑은 고딕',12),wraplength=900).pack(anchor='w',pady=16)
        ttk.Label(twin,text='기준: 30·60·45초, 가동률 90%, 양품률 98%, 8시간.\n직렬 공정의 정상상태 근사입니다. 버퍼·운반·교체·시동·고장 상관관계는 계산하지 않습니다. 실제 설비에 명령을 보내지 않습니다.').pack(anchor='w',pady=8)
        ttk.Label(search,text='답변 전에 근거부터 찾기',font=('맑은 고딕',14,'bold')).pack(anchor='w',pady=10)
        self.question=tk.StringVar(value='진동이 높아졌는데 무엇을 확인해야 하나요?')
        ttk.Entry(search,textvariable=self.question,width=85).pack(anchor='w',pady=10)
        ttk.Button(search,text='근거 찾기',command=lambda:owner.safe(self.search)).pack(anchor='w')
        self.evidence=tk.Text(search,height=14,wrap='word',font=('맑은 고딕',11),state='disabled');self.evidence.pack(fill='both',expand=True,pady=12)
        ttk.Label(search,text='교육용 가상 절차 4건에서 키워드로 검색합니다. 문서 ID와 매칭 근거를 표시하며, 근거가 없으면 답하지 않습니다.\nLLM·벡터 DB·실제 장비 매뉴얼을 사용하는 완성형 RAG는 아닙니다.',wraplength=1000).pack(anchor='w')
        self.calculate()

    def lesson_info(self):
        spec=SCENARIOS[self.choices[self.lesson.get()]]
        text=f"학습 주제: {spec['focus']}\n\n생각해 볼 질문\n{spec['question']}\n\n실습\n{spec['steps']}\n\n생성 데이터\nLOT 10개 × LOT당 24개 시점. 앞 7개 LOT는 학습 구간, 뒤 3개 LOT는 평가 구간입니다.\n\n최근 제조 AI의 데이터 연결·품질·모델 검증 주제에 맞춘 기초 실습입니다. 실습의 성능은 실제 성능을 뜻하지 않습니다."
        self.info.configure(state='normal');self.info.delete('1.0','end');self.info.insert('1.0',text);self.info.configure(state='disabled')

    def generate(self):
        spec=seed_scenario(self.owner.db,self.choices[self.lesson.get()]);self.owner.refresh_features()
        selected=next((key for key,(dataset,sid,asset) in self.owner.features.items() if dataset==spec['dataset']),None)
        if selected:self.owner.feature.set(selected)
        self.owner.status.set(f"{spec['title']} 생성 · {spec['rows']}행 · 합성 데이터")
        self.draw();self.tabs.select(self.trend_page)

    def refresh(self):
        self.feature_box.configure(values=list(self.owner.features))
    def export(self):
        key=self.choices[self.lesson.get()]
        path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile=key+'.csv')
        if path:
            count=export_example(self.owner.db,key,path);self.owner.refresh_features()
            self.owner.status.set(f'이 예제 {count}행 CSV와 합성 데이터 설명 파일을 저장했습니다.')
    def evaluated(self,result):self.model=result;self.draw()

    def draw(self):
        self.chart.delete('all');choice=getattr(self.owner,'features',{}).get(self.owner.feature.get())
        if not choice:return
        dataset,sid,asset=choice
        rows=[r for r in self.owner.db.training_rows() if r['dataset']==dataset and r['signal_id']==sid and r['asset_code']==asset][-2000:]
        if not rows:return
        good=[r['value'] for r in rows if r['quality']=='good' and r['value'] is not None]
        naive=[r['value'] if r['value'] is not None else 0 for r in rows]
        self.caption.set(f"표본 {len(rows)}개 / good {len(good)}개 / 품질 불량·누락 {len(rows)-len(good)}개\n유효값 평균: {statistics.mean(good):.4f}" if good else f'표본 {len(rows)}개 / 유효한 값 없음')
        if good:self.caption.set(self.caption.get()+f' / 오류값 포함·누락 0 채움 평균: {statistics.mean(naive):.4f} (잘못된 전처리 비교)')
        width,height=self.chart.winfo_width(),self.chart.winfo_height()
        if width<180 or height<100:return
        visible=[r['value'] for r in rows if r['value'] is not None and (not self.good_only.get() or r['quality']=='good')]
        if not visible:return
        model=self.model
        if model and (model['parameters']['dataset'],model['parameters']['signal_id'],model['parameters']['asset_code'])!=choice:model=None
        bands=[]
        if model:
            p=model['parameters'];bands=[p['mean']-p['threshold'],p['mean'],p['mean']+p['threshold']]
        low,high=min(visible+bands),max(visible+bands);span=high-low or 1;low-=span*.08;high+=span*.08
        times=[datetime.fromisoformat(r['source_utc']).timestamp() for r in rows];start,end=min(times),max(times)
        def x(t):return 78+(t-start)/max(1,end-start)*(width-100)
        def y(v):return 18+(high-v)/(high-low)*(height-65)
        for i in range(5):
            value=low+(high-low)*i/4;yy=y(value)
            self.chart.create_line(75,yy,width-15,yy,fill='#e7edf2');self.chart.create_text(68,yy,text=f'{value:.2f}',anchor='e',fill='#536b7b')
        for index in [0,len(rows)//2,len(rows)-1]:
            self.chart.create_text(x(times[index]),height-20,text=datetime.fromisoformat(rows[index]['source_utc']).strftime('%m-%d %H:%M'),fill='#536b7b')
        if model:
            for value in bands:self.chart.create_line(78,y(value),width-20,y(value),fill='#238b55',dash=(5,4))
            held=[times[i] for i,r in enumerate(rows) if r['job_id'] in model['metrics']['test_jobs']]
            if held:
                xx=x(min(held));self.chart.create_line(xx,12,xx,height-45,fill='#b05a23',dash=(6,4));self.chart.create_text(xx+4,12,text='평가 시작',anchor='nw',fill='#b05a23')
        window=int(self.window.get());segment=[];averages=[];recent=[]
        def flush(points,color):
            if len(points)>=4:self.chart.create_line(*points,fill=color,width=2)
            elif len(points)==2:
                xx,yy=points;self.chart.create_oval(xx-2,yy-2,xx+2,yy+2,fill=color,outline='')
        previous_job=None
        for i,r in enumerate(rows):
            if i and r['job_id']!=previous_job:
                flush(segment,'#1876b9');flush(averages,'#e69824');segment=[];averages=[];recent=[]
            previous_job=r['job_id']
            xx=x(times[i]);value=r['value']
            if r['quality']=='good' and value is not None:
                segment.extend([xx,y(value)]);recent.append(value);recent=recent[-window:]
                if len(recent)==window:averages.extend([xx,y(statistics.mean(recent))])
            else:
                flush(segment,'#1876b9');flush(averages,'#e69824');segment=[];averages=[];recent=[]
                yy=y(value) if value is not None and not self.good_only.get() else height-44
                if not self.good_only.get() or value is None:
                    self.chart.create_line(xx-3,yy-3,xx+3,yy+3,fill='#8b9098');self.chart.create_line(xx-3,yy+3,xx+3,yy-3,fill='#8b9098')
        flush(segment,'#1876b9');flush(averages,'#e69824')

    def calculate(self):
        if not hasattr(self,'twin_result'):return
        try:
            values=[v.get() for v in self.cycles]
            result=bottleneck(values,float(self.availability.get())/100,float(self.yield_rate.get())/100)
        except (ValueError,tk.TclError):
            self.twin_result.set('가동률·양품률에 0 초과 100 이하의 숫자를 입력하세요.');return
        baseline=bottleneck([30,60,45]);difference=result['expected_good']-baseline['expected_good']
        self.twin_result.set(f"현재 병목: 공정 {result['bottleneck']}\n이상적 시간당 생산량: {result['ideal_per_hour']:.1f}개\n8시간 예상 양품: {result['expected_good']:.1f}개 / 기준 대비 {difference:+.1f}개\n\n병목이 아닌 공정만 줄였을 때 결과가 달라지는지 비교해 보세요.")

    def search(self):
        docs=retrieve(self.question.get())
        text='관련 근거가 없습니다. 질문을 구체화하거나 필요한 문서를 추가해야 합니다.' if not docs else '\n\n'.join(f"[{d['id']}] {d['title']}\n찾은 단어: {', '.join(d['matched'])}\n근거 문장: {d['text']}" for d in docs)
        self.evidence.configure(state='normal');self.evidence.delete('1.0','end');self.evidence.insert('1.0',text);self.evidence.configure(state='disabled')
