import tkinter as tk
from tkinter import ttk
import uuid
from .ui import Window,Form


class POPApp(Window):
    def __init__(self,path=None):
        super().__init__('OpenSignal POP · 현장 작업',path)
        top=ttk.Frame(self.root);top.pack(fill='x')
        ttk.Label(top,text='작업자').pack(side='left');self.operator=tk.StringVar(value='학습자')
        ttk.Entry(top,textvariable=self.operator,width=18).pack(side='left',padx=8)
        ttk.Label(top,text='바코드 / 작업지시 코드').pack(side='left');self.barcode=tk.StringVar()
        entry=ttk.Entry(top,textvariable=self.barcode,width=25);entry.pack(side='left',padx=8);entry.bind('<Return>',lambda e:self.safe(self.lookup))
        ttk.Button(top,text='조회',command=lambda:self.safe(self.lookup)).pack(side='left')
        bar=ttk.Frame(self.root);bar.pack(fill='x',pady=12)
        for title,kind in [('작업 시작','start'),('일시 정지','pause'),('작업 재개','resume'),('실적 등록','report'),('작업 완료','complete')]:ttk.Button(bar,text=title,command=lambda k=kind:self.safe(lambda:self.action(k))).pack(side='left',padx=4)
        ttk.Label(self.root,text='실적은 누적 합계가 아닌 이번에 추가한 수량입니다. 양품 카운터 연결 중에는 양품 수동 입력을 막습니다.').pack(anchor='w')
        self.jobs_table=self.table(self.root,['ID','작업지시','설비','LOT','목표','상태','양품','불량'])
        self.events=self.table(self.root,['시각','작업 ID','동작','추가 양품','추가 불량','작업자','사유','입력 경로'])
        self.refresh();self.after(1500,self.tick)
    def tick(self):self.refresh();self.after(1500,self.tick)
    def refresh(self):
        self.fill(self.jobs_table,[(r['id'],[r[k] for k in ['id','code','asset_code','lot','target','status','good','bad']]) for r in self.db.jobs()])
        rows=self.db.query('SELECT * FROM pop_events ORDER BY id DESC LIMIT 200')
        self.fill(self.events,[(r['id'],[r[k] for k in ['at_utc','job_id','kind','good','bad','operator','reason','origin']]) for r in rows])
    def lookup(self):
        row=next((r for r in self.db.jobs() if r['code']==self.barcode.get().strip()),None)
        if not row:raise ValueError('작업지시가 없습니다.')
        self.jobs_table.selection_set(str(row['id']));self.jobs_table.see(str(row['id']))
    def action(self,kind):
        selected=self.jobs_table.selection()
        if not selected:raise ValueError('작업지시를 선택하거나 바코드로 조회하세요.')
        job=int(selected[0]);operator=self.operator.get().strip();key=str(uuid.uuid4())
        if kind in {'pause','report'}:
            fields=[('reason','비가동 / 실적 사유','',None)]
            if kind=='report':fields=[('good','이번 추가 양품',0,None),('bad','이번 추가 불량',0,None)]+fields
            def save(v):self.db.event(job,kind,operator,int(v.get('good',0)),int(v.get('bad',0)),v['reason'],key);self.refresh()
            Form(self,'현장 입력',fields,save)
        else:self.db.event(job,kind,operator,event_key=key);self.refresh()


if __name__=='__main__':POPApp().mainloop()
