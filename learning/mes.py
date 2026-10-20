from tkinter import ttk
from .ui import Window,Form


class MESApp(Window):
    def __init__(self,path=None):
        super().__init__('OpenSignal MES · 생산 관리',path)
        ttk.Label(self.root,text='기준정보 → 작업지시 → POP 생산 실적 → 검사 판정. 수집기의 DB와 분리되어 있습니다.').pack(anchor='w')
        bar=ttk.Frame(self.root);bar.pack(fill='x',pady=10)
        for title,action in [('설비 등록',self.asset_form),('품목 등록',self.item_form),('작업지시 등록',self.job_form),('검사 판정',self.inspect_form),('새로 고침',self.refresh)]:ttk.Button(bar,text=title,command=lambda a=action:self.safe(a)).pack(side='left',padx=4)
        self.jobs_table=self.table(self.root,['ID','작업지시','품목','설비','LOT','목표','상태','양품','불량','판정'])
        self.info=ttk.Label(self.root);self.info.pack(anchor='w',pady=8)
        self.refresh();self.after(1500,self.tick)
    def tick(self):self.refresh();self.after(1500,self.tick)
    def refresh(self):
        rows=self.db.jobs();self.fill(self.jobs_table,[(r['id'],[r[k] for k in ['id','code','item_code','asset_code','lot','target','status','good','bad','result_label']]) for r in rows])
        assets=self.db.query('SELECT * FROM equipment');items=self.db.query('SELECT * FROM items')
        self.info.configure(text='설비: '+', '.join(a['code'] for a in assets)+'   |   품목: '+', '.join(i['code'] for i in items))
    def asset_form(self):
        def save(v):self.db.equipment(v['code'],v['name']);self.refresh()
        Form(self,'설비 등록',[('code','설비 코드','CELL-01',None),('name','설비 이름','가공 셀 1',None)],save)
    def item_form(self):
        def save(v):self.db.item(v['code'],v['name']);self.refresh()
        Form(self,'품목 등록',[('code','품목 코드','PART-01',None),('name','품목 이름','교육용 부품',None)],save)
    def job_form(self):
        assets=[a['code'] for a in self.db.query('SELECT * FROM equipment')];items=[i['code'] for i in self.db.query('SELECT * FROM items')]
        if not assets or not items:raise ValueError('먼저 설비와 품목을 등록하세요.')
        def save(v):self.db.job(v['code'],v['item'],v['asset'],v['lot'],int(v['target']));self.refresh()
        Form(self,'작업지시',[('code','작업지시 코드','WO-001',None),('item','품목',items[0],items),('asset','설비',assets[0],assets),('lot','LOT','LOT-001',None),('target','목표 수량',100,None)],save)
    def inspect_form(self):
        selected=self.jobs_table.selection()
        if not selected:raise ValueError('검사할 작업지시를 선택하세요.')
        def save(v):self.db.inspect(int(selected[0]),v['label']);self.refresh()
        Form(self,'작업 / LOT 검사',[('label','판정','unknown',['normal','defect','unknown'])],save)


if __name__=='__main__':MESApp().mainloop()
