import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk,messagebox,filedialog
from .ui import Window,Form
from .core import ROOT


ROLES={'수집기':'collector','MES':'mes','POP':'pop','AI 학습':'ai'}
COLORS={'collector':'#d7eef4','mes':'#d8e6fb','pop':'#fae6ce','ai':'#dcefdc'}


class Studio(Window):
    def __init__(self,path=None):
        super().__init__('OpenSignal Learning Studio · 연결하며 배우는 제조 AI',path)
        self.catalog_data=None;self.busy=False;self.mail=queue.SimpleQueue();self.drag=None;self.pending=None;self.selected_edge=None;self.selected_node=None
        bar=ttk.Frame(self.root);bar.pack(fill='x')
        for title,action in [('MES 열기',lambda:self.launch('mes')),('POP 열기',lambda:self.launch('pop')),('예제 실습 데이터',self.seed),('배치 저장',self.save_layout),('배치 불러오기',self.load_layout)]:ttk.Button(bar,text=title,command=lambda a=action:self.safe(a)).pack(side='left',padx=3)
        self.status=tk.StringVar(value='1. 수집기에서 API 시작 → 2. 연결 확인 → 3. 블록 배치·연결 → 4. 장치 매핑 → 5. 동기화')
        ttk.Label(self.root,textvariable=self.status,foreground='#235a72',wraplength=1000).pack(anchor='w',pady=9)
        tabs=ttk.Notebook(self.root);tabs.pack(fill='both',expand=True)
        layout,connection,ai,guide=[ttk.Frame(tabs,padding=10) for _ in range(4)]
        for page,title in [(layout,'공장 배치·연결'),(connection,'수집기·장치 매핑'),(ai,'제조 AI 실습'),(guide,'실습 안내')]:tabs.add(page,text=' '+title+' ')
        controls=ttk.Frame(layout);controls.pack(fill='x')
        for title,action in [('블록 추가',self.node_form),('블록 수정',self.edit_node),('기본 블록 놓기',self.template),('선택 연결 해제',self.disconnect)]:ttk.Button(controls,text=title,command=lambda a=action:self.safe(a)).pack(side='left',padx=3)
        self.connect_mode=tk.BooleanVar(value=False)
        ttk.Checkbutton(controls,text='연결 모드: 출발 블록 → 도착 블록 클릭',variable=self.connect_mode,command=self.reset_pending).pack(side='left',padx=8)
        ttk.Label(layout,text='일반 모드에서는 블록을 드래그해 배치합니다. 선을 클릭하면 선택됩니다. 수집→MES 연결과 장치 매핑이 데이터 유입 경로를 정합니다.').pack(anchor='w',pady=7)
        wrap=ttk.Frame(layout);wrap.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(wrap,bg='#f4f7fb',scrollregion=(0,0,2050,1150),highlightthickness=0)
        ys=ttk.Scrollbar(wrap,orient='vertical',command=self.canvas.yview);ys.pack(side='right',fill='y')
        xs=ttk.Scrollbar(wrap,orient='horizontal',command=self.canvas.xview);xs.pack(side='bottom',fill='x')
        self.canvas.configure(yscrollcommand=ys.set,xscrollcommand=xs.set);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        row=ttk.Frame(connection);row.pack(fill='x')
        ttk.Label(row,text='수집기 API 주소').pack(side='left');self.endpoint=tk.StringVar(value=self.db.setting('collector_url'))
        ttk.Entry(row,textvariable=self.endpoint,width=36).pack(side='left',padx=8)
        for title,action in [('연결 확인',self.check_connection),('장치 매핑',self.binding_form),('지금 동기화',self.sync),('처음부터 다시 읽기',self.rewind)]:ttk.Button(row,text=title,command=lambda a=action:self.safe(a)).pack(side='left',padx=3)
        self.auto=tk.BooleanVar(value=False);ttk.Checkbutton(connection,text='2초마다 자동 동기화',variable=self.auto).pack(anchor='w',pady=10)
        self.catalog_table=self.table(connection,['수집 설비 코드','센서 ID','측정 항목','단위','연결 방식'])
        self.mapping=self.table(connection,['매핑 ID','수집 설비','MES 설비','양품 카운터 센서','활성'])
        ttk.Label(connection,text='카운터는 반드시 양품 누적 개수 센서에만 지정하세요. 온도·관절각을 생산 수량으로 지정하면 안 됩니다.').pack(anchor='w')
        ttk.Label(ai,text='작업/LOT를 시간 순으로 나눠 정상 기준선을 학습합니다.',font=('맑은 고딕',15,'bold')).pack(anchor='w',pady=10)
        self.feature=tk.StringVar();self.feature_box=ttk.Combobox(ai,textvariable=self.feature,state='readonly',width=80);self.feature_box.pack(anchor='w',pady=8)
        aibar=ttk.Frame(ai);aibar.pack(fill='x')
        for title,action in [('센서 목록 갱신',self.refresh_features),('정상 기준선 학습·평가',self.learn),('MES 연결 학습 CSV 저장',self.export_training)]:ttk.Button(aibar,text=title,command=lambda a=action:self.safe(a)).pack(side='left',padx=4,pady=8)
        self.result=tk.Text(ai,height=18,font=('맑은 고딕',11),wrap='word',state='disabled');self.result.pack(fill='both',expand=True,pady=10)
        ttk.Label(ai,text='판정은 LOT 전체에 붙인 교육용 정답입니다. 단일 센서 3σ 기준선은 고장 예측·예지보전 모델이 아닙니다.').pack(anchor='w')
        guide_text='''실습 순서

1. 수집기: Start.cmd → 가상 공장 추가 → 전체 수집 시작 → 학습 앱 연결 API.
2. MES: 설비와 품목을 등록하고 서로 다른 LOT의 작업지시를 만듭니다.
3. 배치: 수집기·MES·POP·AI 블록을 직접 놓고 연결합니다. 수집 블록의 설비 코드는 수집기의 코드이고 MES 블록은 MES 설비 코드입니다.
4. 매핑: 수집 설비 → MES 설비를 등록하고 센서 데이터를 동기화합니다. 연결 전의 데이터는 처음부터 다시 읽기로 가져올 수 있습니다.
5. POP: 작업지시를 바코드/코드로 조회하고 시작·정지·재개·실적·완료를 입력합니다. MES는 동일 실적을 조회합니다.
6. MES: 확인한 작업/LOT에 normal/defect/unknown 판정을 붙입니다.
7. AI: 센서를 선택해 학습·평가합니다. 앞 70% 작업의 normal 표본만 학습하고 뒤 작업을 평가합니다. 작업이 학습/평가에 동시에 들어가지 않습니다.

빠른 체험: 예제 실습 데이터를 누르면 가상 LOT 5개와 센서 데이터가 별도로 생성됩니다. 실제 수집 데이터와 synthetic-learning 이름으로 구분됩니다.

학습할 내용: 센서 수치만으로 생산 실적이 되지는 않습니다. 설비 매핑·시각·LOT·품질·판정이 연결되어야 학습 데이터를 만들 수 있습니다. 원본 수집 DB에는 쓰지 않습니다.

배치 파일에는 블록·선·기준정보·장치 매핑만 저장합니다. 측정 데이터·실적·학습 결과는 포함하지 않습니다. 불러오기는 기존 내용을 지우지 않고 추가합니다.'''
        text=tk.Text(guide,wrap='word',font=('맑은 고딕',11));text.pack(fill='both',expand=True);text.insert('1.0',guide_text);text.configure(state='disabled')
        self.refresh_layout();self.refresh_mappings();self.refresh_features();self.after(200,self.poll)

    def launch(self,module):
        import os
        env=os.environ.copy();env['OPENSIGNAL_LEARNING_DB']=str(self.db.path)
        subprocess.Popen([sys.executable,'-m','learning.'+module],cwd=ROOT,env=env)
    def reset_pending(self):self.pending=None
    def node_form(self):
        def save(v):self.db.node(v['name'],ROLES[v['role']],v['asset']);self.refresh_layout()
        Form(self,'블록 추가',[('name','블록 이름','새 블록',None),('role','역할','수집기',list(ROLES)),('asset','설비 코드 (AI/POP는 선택)','',None)],save)
    def edit_node(self):
        if self.selected_node is None:raise ValueError('블록을 먼저 선택하세요.')
        node=self.nodes[self.selected_node]
        def save(v):
            linked=self.db.query('SELECT 1 FROM edges WHERE source=? OR target=?',(node['id'],node['id']))
            if linked and v['asset']!=node['asset_code']:raise ValueError('설비 코드를 바꾸려면 연결을 먼저 해제하세요.')
            with self.db.connect() as db:db.execute('UPDATE nodes SET name=?,asset_code=? WHERE id=?',(v['name'],v['asset'],node['id']))
            self.refresh_layout()
        Form(self,'블록 수정',[('name','이름',node['name'],None),('asset','설비 코드',node['asset_code'],None)],save)
    def template(self):
        for i,(name,role,code) in enumerate([('PLC 수집','collector','DEMO-PLC'),('MES 생산 관리','mes','CELL-01'),('POP 현장','pop','CELL-01'),('AI 학습','ai','')]):self.db.node(name,role,code,70+i*250,120+(i%2)*120)
        self.refresh_layout()
    def refresh_layout(self):
        self.nodes={n['id']:n for n in self.db.query('SELECT * FROM nodes')};self.edges=self.db.query('SELECT * FROM edges');self.draw()
    def draw(self):
        self.canvas.delete('all')
        for x in range(0,2050,30):self.canvas.create_line(x,0,x,1150,fill='#e8edf3')
        for y in range(0,1150,30):self.canvas.create_line(0,y,2050,y,fill='#e8edf3')
        for edge in self.edges:
            a=self.nodes[edge['source']];b=self.nodes[edge['target']];tag=f"edge:{a['id']}:{b['id']}"
            chosen=self.selected_edge==(a['id'],b['id'])
            self.canvas.create_line(a['x']+190,a['y']+40,b['x'],b['y']+40,arrow='last',width=4 if chosen else 2,fill='#e17b25' if chosen else '#64839a',tags=(tag,))
        for key,n in self.nodes.items():
            x,y=n['x'],n['y'];tag=f'node:{key}'
            self.canvas.create_rectangle(x,y,x+190,y+85,fill=COLORS[n['role']],outline='#0d697b' if self.selected_node==key else '#a5b7c5',width=3 if self.selected_node==key else 1,tags=(tag,))
            self.canvas.create_text(x+12,y+20,text=n['name'],anchor='w',font=('맑은 고딕',11,'bold'),tags=(tag,))
            self.canvas.create_text(x+12,y+54,text=n['role'].upper()+'  /  '+(n['asset_code'] or '미지정'),anchor='w',font=('맑은 고딕',9),tags=(tag,))
    def press(self,event):
        current=self.canvas.find_withtag('current')
        tags=self.canvas.gettags(current[0]) if current else ()
        node=next((int(t.split(':')[1]) for t in tags if t.startswith('node:')),None)
        edge=next((tuple(map(int,t.split(':')[1:])) for t in tags if t.startswith('edge:')),None)
        if edge:self.selected_edge=edge;self.selected_node=None;self.draw();return
        if node is None:return
        self.selected_node=node;self.selected_edge=None
        if self.connect_mode.get():
            if self.pending is None:self.pending=node;self.status.set('도착 블록을 클릭하세요.')
            else:
                self.safe(lambda:self.db.edge(self.pending,node));self.pending=None;self.refresh_layout()
        else:
            n=self.nodes[node];self.drag=(node,self.canvas.canvasx(event.x)-n['x'],self.canvas.canvasy(event.y)-n['y'])
        self.draw()
    def motion(self,event):
        if self.drag:
            node,dx,dy=self.drag;self.nodes[node]['x']=max(10,min(1800,self.canvas.canvasx(event.x)-dx));self.nodes[node]['y']=max(10,min(1000,self.canvas.canvasy(event.y)-dy));self.draw()
    def release(self,event):
        if self.drag:
            node,_,_=self.drag;n=self.nodes[node];self.safe(lambda:self.db.move(node,n['x'],n['y']));self.drag=None
    def disconnect(self):
        if not self.selected_edge:raise ValueError('해제할 선을 클릭하세요.')
        self.db.disconnect(*self.selected_edge);self.selected_edge=None;self.refresh_layout();self.refresh_mappings()
    def save_layout(self):
        path=filedialog.asksaveasfilename(defaultextension='.json',initialfile='factory-layout.json')
        if path:self.db.save_layout(path)
    def load_layout(self):
        path=filedialog.askopenfilename(filetypes=[('배치 파일','*.json')])
        if path:self.db.load_layout(path);self.refresh_layout();self.refresh_mappings()
    def check_connection(self):
        from urllib.parse import urlsplit
        url=self.endpoint.get().strip();parts=urlsplit(url)
        if parts.scheme not in {'http','https'} or not parts.netloc or parts.username:raise ValueError('인증 정보 없는 HTTP API 주소를 입력하세요.')
        self.db.setting('collector_url',url)
        self.background('catalog',self.db.catalog)
    def background(self,kind,action):
        if self.busy:raise ValueError('진행 중인 연결 작업이 있습니다.')
        self.busy=True
        def work():
            try:self.mail.put((kind,action()))
            except Exception as e:self.mail.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()
    def binding_form(self):
        if not self.catalog_data:raise ValueError('먼저 수집기 연결 확인을 누르세요.')
        sources=[a['code'] for a in self.catalog_data['assets']];assets=[a['code'] for a in self.db.query('SELECT * FROM equipment')]
        if not sources or not assets:raise ValueError('수집기 설비와 MES 설비를 먼저 등록하세요.')
        choices={'사용 안 함':None}
        for s in self.catalog_data['signals']:choices[f"{s['id']} · {s['asset_code']} / {s['name']} ({s['unit']})"]=s['id']
        def save(v):
            counter=choices[v['counter']]
            if counter is not None and not any(s['id']==counter and s['asset_code']==v['source'] for s in self.catalog_data['signals']):raise ValueError('해당 수집 설비의 센서만 선택하세요.')
            self.db.bind(v['source'],v['asset'],counter);self.refresh_mappings()
        Form(self,'장치 → MES 매핑',[('source','수집 설비 코드',sources[0],sources),('asset','MES 설비 코드',assets[0],assets),('counter','양품 누적 카운터 (선택)','사용 안 함',list(choices))],save)
    def refresh_mappings(self):
        rows=self.db.query('SELECT * FROM bindings ORDER BY id DESC')
        self.fill(self.mapping,[(r['id'],[r[k] for k in ['id','collector_asset','asset_code','counter_signal','active']]) for r in rows])
    def sync(self):self.background('sync',self.db.sync)
    def rewind(self):
        with self.db.connect() as db:db.execute('UPDATE cursors SET last_id=0')
        self.status.set('읽기 위치를 초기화했습니다. 동기화하면 미수신 자료를 가져오며 기존 자료는 중복 저장하지 않습니다.')
    def seed(self):self.db.seed_lesson();self.refresh_features();self.status.set('가상 LOT 5개·온도 150개 생성. 제조 AI 실습에서 synthetic-learning 센서를 선택하세요.')
    def refresh_features(self):
        rows=self.db.query('SELECT DISTINCT dataset,signal_id,signal_name,unit,asset_code FROM samples ORDER BY dataset,signal_id')
        self.features={f"{r['signal_name']} / {r['asset_code']} / {r['unit']} / {r['dataset'][:18]} / {r['signal_id']}":(r['dataset'],r['signal_id'],r['asset_code']) for r in rows}
        self.feature_box.configure(values=list(self.features))
        if self.feature.get() not in self.features:self.feature.set(next(iter(self.features),''))
    def learn(self):
        if self.feature.get() not in self.features:raise ValueError('센서를 선택하세요.')
        result=self.db.learn(*self.features[self.feature.get()]);p=result['parameters'];m=result['metrics']
        text=f"정상 기준선: 평균 {p['mean']:.4f} {p['unit']} / 표준편차 {p['std']:.4f}\n이상 기준: 평균에서 ±{p['threshold']:.4f} 초과\n\n학습 작업 ID: {m['train_jobs']}\n평가 작업 ID: {m['test_jobs']}\n학습 {m['train_samples']}개 / 평가 {m['test_samples']}개\n\n불량 감지(TP): {m['tp']}\n정상 통과(TN): {m['tn']}\n정상 오탐(FP): {m['fp']}\n불량 미탐(FN): {m['fn']}\n평가 판정 미등록: {m['unlabeled']}\n\n학습·평가 작업은 겹치지 않습니다. 품질 good만 사용합니다.\nLOT 판정은 개별 센서 시점의 정밀 정답을 보증하지 않습니다."
        self.result.configure(state='normal');self.result.delete('1.0','end');self.result.insert('1.0',text);self.result.configure(state='disabled')
    def export_training(self):
        path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile='mes-pop-training.csv')
        if path:messagebox.showinfo('학습 데이터',f'{self.db.export_training(path):,}행 저장')
    def poll(self):
        try:
            while True:
                kind,data=self.mail.get_nowait();self.busy=False
                if kind=='catalog':
                    self.catalog_data=data;self.fill(self.catalog_table,[(s['id'],[s['asset_code'],s['id'],s['name'],s['unit'],s['protocol']]) for s in data['signals']]);self.status.set('수집기 연결 확인. 블록 연결과 장치 매핑을 설정하세요.')
                elif kind=='sync':self.status.set(f"동기화: 신규 {data['imported']}개 / 매핑 없음 {data['unmapped']}개");self.refresh_features()
                else:self.status.set('연결 확인 필요: '+str(data))
        except queue.Empty:pass
        if self.auto.get() and not self.busy:
            self.safe(self.sync)
        self.after(2000,self.poll)


if __name__=='__main__':Studio().mainloop()
