import json
import queue
import tkinter as tk
from collections import deque
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime,timezone,timedelta
from operations_db import OperationsDB,utc
from acquisition import Engine
from instance_lock import InstanceLock

BASE=Path(__file__).resolve().parent
PROTOCOLS={'가상 장비':'demo','Modbus TCP':'modbus_tcp','OPC UA':'opcua','아두이노 / 시리얼 JSON':'serial_json','로봇 / TCP JSON 브리지':'robot_json'}


class Form(tk.Toplevel):
    def __init__(self,parent,title,fields,callback):
        super().__init__(parent)
        self.title(title);self.transient(parent);self.grab_set();self.fields={}
        frame=ttk.Frame(self,padding=18);frame.pack(fill='both',expand=True)
        for i,(key,label,default,choices) in enumerate(fields):
            ttk.Label(frame,text=label).grid(row=i,column=0,sticky='w',pady=5,padx=(0,15))
            var=tk.StringVar(value=str(default));self.fields[key]=var
            widget=ttk.Combobox(frame,textvariable=var,values=choices,state='readonly',width=44) if choices else ttk.Entry(frame,textvariable=var,width=47)
            widget.grid(row=i,column=1,sticky='ew',pady=5)
        def submit():
            try:
                callback({k:v.get().strip() for k,v in self.fields.items()})
                self.destroy()
            except Exception as e:messagebox.showerror('입력 확인',str(e),parent=self)
        ttk.Button(frame,text='저장',command=submit).grid(row=len(fields),column=1,sticky='e',pady=(14,0))


class OperationsApp(tk.Tk):
    def __init__(self,path=None):
        super().__init__();self.title('OpenSignal · 제조 데이터 운영');self.geometry('1230x850');self.minsize(1000,700)
        db_path=Path(path or BASE/'data'/'manufacturing.sqlite3')
        self.instance_lock=InstanceLock(db_path.with_suffix('.lock'))
        self.db=OperationsDB(db_path)
        self.messages=queue.Queue(maxsize=500);self.controls=queue.SimpleQueue();self.engine=Engine(self.db,self.notify);self.latest={};self.log_lines=[];self.traces={}
        style=ttk.Style(self);style.theme_use('clam')
        style.configure('TLabel',font=('맑은 고딕',10));style.configure('TButton',font=('맑은 고딕',10),padding=7)
        style.configure('Treeview',rowheight=27,font=('맑은 고딕',10))
        root=ttk.Frame(self,padding=20);root.pack(fill='both',expand=True)
        ttk.Label(root,text='OpenSignal  /  제조 데이터 운영',font=('맑은 고딕',23,'bold')).pack(anchor='w')
        ttk.Label(root,text='설비 연결  ·  센서 수집  ·  생산 맥락  ·  품질 판정  ·  AI 데이터',foreground='#507080').pack(anchor='w',pady=(4,12))
        bar=ttk.Frame(root);bar.pack(fill='x',pady=(0,10))
        for title,command in [('가상 공장 추가',self.demo),('전체 수집 시작',self.start_all),('전체 중지',lambda:self.engine.stop())]:
            ttk.Button(bar,text=title,command=command).pack(side='left',padx=(0,8))
        self.status=tk.StringVar(value='설비를 등록하거나 가상 공장을 추가하세요.')
        ttk.Label(bar,textvariable=self.status).pack(side='right')
        tabs=ttk.Notebook(root);tabs.pack(fill='both',expand=True)
        pages=[]
        for title in ['연결·센서','실시간','생산 이력','정상·불량 판정','AI 데이터']:
            page=ttk.Frame(tabs,padding=12);tabs.add(page,text=' '+title+' ');pages.append(page)
        connections,live,jobs,labels,export=pages
        controls=ttk.Frame(connections);controls.pack(fill='x',pady=(0,8))
        for title,cmd in [('연결 추가',self.source_form),('연결 수정',lambda:self.source_form(True)),('선택 시작',self.start_selected),('선택 중지',self.stop_selected),('센서 추가',self.signal_form),('센서 수정',lambda:self.signal_form(True))]:
            ttk.Button(controls,text=title,command=cmd).pack(side='left',padx=3)
        self.sources=self.table(connections,['ID','설비 코드','설비','연결 이름','방식','간격(초)','상태'],height=7)
        self.sources.bind('<<TreeviewSelect>>',lambda e:self.refresh_signals())
        ttk.Label(connections,text='선택한 연결의 센서 · Modbus 주소 예: 0, 2:f32, 2:f32:swap / OPC UA: NodeId / JSON: 항목 이름').pack(anchor='w',pady=10)
        self.signals=self.table(connections,['ID','주소·항목','측정 항목','단위','배율','보정값','하한','상한','유효시간(초)'],height=8)
        self.live=self.table(live,['설비 연결','측정 항목','현재값','단위','품질','장치 시각(UTC)'],height=6)
        self.live.bind('<<TreeviewSelect>>',lambda e:self.draw_chart())
        ttk.Label(live,text='센서를 선택하면 최근 120회 추이를 표시합니다. 품질이 나쁜 구간은 선을 연결하지 않습니다.').pack(anchor='w',pady=5)
        self.chart=tk.Canvas(live,height=120,bg='white',highlightthickness=0);self.chart.pack(fill='x')
        self.chart.bind('<Configure>',lambda e:self.draw_chart())
        ttk.Label(live,text='품질: good 정상 / missing 누락 / stale 지연 / out_of_range 범위 이탈 / device_bad 장치 오류 / invalid 잘못된 값').pack(anchor='w',pady=8)
        self.log= tk.Text(live,height=4,state='disabled',font=('맑은 고딕',10));self.log.pack(fill='both',expand=True)
        jobbar=ttk.Frame(jobs);jobbar.pack(fill='x')
        for title,cmd in [('생산 작업 시작',self.job_form),('선택 작업 종료',self.end_job),('새로 고침',self.refresh_jobs)]:ttk.Button(jobbar,text=title,command=cmd).pack(side='left',padx=4,pady=8)
        self.jobs=self.table(jobs,['ID','설비','작업지시','제품','LOT','공정','운전 상태','시작(UTC)','종료(UTC)'])
        ttk.Label(labels,text='실제 확인한 구간만 판정하세요. 판정이 없는 데이터는 정상으로 간주하지 않습니다. 겹치는 판정은 내보내기에 모두 표시됩니다.').pack(anchor='w',pady=8)
        ttk.Button(labels,text='판정 구간 등록',command=self.label_form).pack(anchor='w',pady=8)
        self.labels=self.table(labels,['ID','설비','시작(UTC)','종료(UTC)','판정','메모'])
        ttk.Label(export,text='수집 원본 또는 시간 구간별 학습 특징을 내보냅니다.',font=('맑은 고딕',15,'bold')).pack(anchor='w',pady=12)
        self.export_fields={}
        for key,title,default in [('start','시작 시각 (ISO 8601, 비우면 전체)',''),('end','종료 시각 (ISO 8601, 비우면 전체)',''),('window','특징 집계 구간 (초)','60')]:
            ttk.Label(export,text=title).pack(anchor='w',pady=(10,3));var=tk.StringVar(value=default);self.export_fields[key]=var
            ttk.Entry(export,textvariable=var,width=55).pack(anchor='w')
        self.features=tk.BooleanVar(value=False)
        ttk.Checkbutton(export,text='AI 특징 집계: 평균·최솟값·최댓값·제곱평균·데이터 품질 비율',variable=self.features).pack(anchor='w',pady=18)
        for title,fmt in [('CSV 내보내기','csv'),('Parquet 내보내기','parquet')]:ttk.Button(export,text=title,command=lambda f=fmt:self.export_data(f)).pack(anchor='w',pady=5)
        ttk.Button(export,text='설비 연결별 · 일별 Parquet 폴더 저장',command=lambda:self.export_data('daily')).pack(anchor='w',pady=5)
        ttk.Label(export,text='LOT·작업 이력·판정 라벨·내보내기 조건도 포함됩니다. 학습/평가는 시간·LOT 기준으로 분리하세요.\nParquet에는 duckdb, OPC UA에는 asyncua, 시리얼에는 pyserial 설치가 필요합니다.\nSQLite는 로컬 수집용입니다. 대규모 분석은 Parquet를 외부 분석 환경에서 처리하세요.',foreground='#507080').pack(anchor='w',pady=20)
        self.export_busy=False;self.closing=False
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh();self.after(150,self.drain)

    def table(self,parent,columns,height=15):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        table=ttk.Treeview(frame,columns=columns,show='headings',height=height)
        for c in columns:table.heading(c,text=c);table.column(c,width=125,minwidth=70,anchor='center')
        scroll=ttk.Scrollbar(frame,orient='vertical',command=table.yview);scroll.pack(side='right',fill='y');table.configure(yscrollcommand=scroll.set)
        horizontal=ttk.Scrollbar(frame,orient='horizontal',command=table.xview);horizontal.pack(side='bottom',fill='x');table.configure(xscrollcommand=horizontal.set)
        table.pack(fill='both',expand=True);return table

    def notify(self,kind,data):
        if kind!='data':
            self.controls.put((kind,data));return
        try:self.messages.put_nowait((kind,data))
        except queue.Full:pass  # UI notifications may be coalesced; DB writes are never dropped.

    def selected_source(self):
        selection=self.sources.selection()
        if not selection:raise ValueError('연결을 선택하세요.')
        return next(s for s in self.db.sources() if s['id']==int(selection[0]))

    def idle_required(self):
        if self.engine.active():raise ValueError('설정을 바꾸려면 수집을 모두 중지하세요.')

    def source_form(self,edit=False):
        try:
            self.idle_required();old=self.selected_source() if edit else None;c=json.loads(old['config_json']) if old else {}
        except Exception as e:messagebox.showerror('연결 설정',str(e));return
        default_protocol=next((k for k,v in PROTOCOLS.items() if old and v==old['protocol']),'가상 장비')
        fields=[('asset','설비 코드',old['asset_code'] if old else 'MACHINE-01',None),('asset_name','설비 이름',old['asset_name'] if old else '설비 1',None),
          ('location','위치',old['location'] if old else 'LINE-A',None),('kind','설비 유형',old['asset_kind'] if old else 'equipment',['equipment','plc','robot','arduino']),('name','연결 이름',old['name'] if old else '센서 연결',None),
          ('protocol','연결 방식',default_protocol,list(PROTOCOLS)),('endpoint','IP / OPC 주소 / COM 포트',c.get('host',c.get('endpoint',c.get('port','127.0.0.1'))),None),
          ('port','TCP 포트 (시리얼에서는 무시)',c.get('port',502) if old and old['protocol']!='serial_json' else 502,None),('unit','Modbus 장치 번호',c.get('unit',1),None),
          ('function','Modbus 읽기 기능',str(c.get('function',3)),['3','4']),('baud','시리얼 속도',c.get('baud',115200),None),('interval','수집 간격 (초)',old['interval_s'] if old else 1,None),
          ('username_env','OPC 사용자명 환경변수 이름',c.get('username_env',''),None),('password_env','OPC 비밀번호 환경변수 이름',c.get('password_env',''),None),
          ('security','OPC 보안 설정 (선택)',c.get('security_string',''),None)]
        def save(v):
            self.idle_required();protocol=PROTOCOLS[v['protocol']];config={'timeout':3}
            if protocol in {'modbus_tcp','robot_json'}:
                port=int(v['port'])
                if not 1<=port<=65535:raise ValueError('TCP 포트 범위를 확인하세요.')
                config.update(host=v['endpoint'],port=port)
            if protocol=='modbus_tcp':
                unit=int(v['unit'])
                if not 0<=unit<=255:raise ValueError('장치 번호는 0~255입니다.')
                config.update(unit=unit,function=int(v['function']))
            if protocol=='opcua':
                if not v['endpoint'].startswith('opc.tcp://') or '@' in v['endpoint']:raise ValueError('opc.tcp:// 주소를 입력하세요. 인증은 환경변수로 설정하세요.')
                config.update(endpoint=v['endpoint'])
                for key,field in [('username_env','username_env'),('password_env','password_env'),('security_string','security')]:
                    if v[field]:config[key]=v[field]
            if protocol=='serial_json':
                baud=int(v['baud'])
                if baud<=0:raise ValueError('시리얼 속도는 양수입니다.')
                config.update(port=v['endpoint'],baud=baud)
            interval=float(v['interval'])
            if not .2<=interval<=3600 or not v['name']:raise ValueError('이름과 간격을 확인하세요.')
            if old:
                if v['asset']!=old['asset_code']:raise ValueError('기존 연결의 설비 코드는 변경할 수 없습니다. 새 연결을 추가하세요.')
                with self.db.connect() as db:
                    db.execute('UPDATE sources SET name=?,protocol=?,config_json=?,interval_s=? WHERE id=?',(v['name'],protocol,json.dumps(config),interval,old['id']))
                    db.execute('UPDATE assets SET name=?,location=?,kind=? WHERE id=?',(v['asset_name'],v['location'],v['kind'],old['asset_id']))
            else:self.db.add_source(v['asset'],v['asset_name'],v['location'],v['name'],protocol,config,interval,v['kind'])
            self.refresh()
        Form(self,'연결 수정' if old else '연결 추가',fields,save)

    def signal_form(self,edit=False):
        try:
            self.idle_required();source=self.selected_source();old=None
            if edit:
                selected=self.signals.selection()
                if not selected:raise ValueError('센서를 선택하세요.')
                old=next(s for s in self.db.signals(source['id']) if s['id']==int(selected[0]))
        except Exception as e:messagebox.showerror('센서 설정',str(e));return
        fields=[]
        for key,title,default in [('key','주소 / NodeId / JSON 항목','0' if source['protocol']=='modbus_tcp' else 'temperature'),('name','측정 항목','온도'),('unit','단위','°C'),('scale','배율',1),('offset','보정값',0),('low_limit','하한 (선택)',''),('high_limit','상한 (선택)',''),('stale_s','데이터 유효시간 (초)',30)]:
            value=old.get(key,default) if old else default;fields.append((key,title,'' if value is None else value,None))
        def save(v):
            self.idle_required()
            scale,offset,stale=[float(v[k]) for k in ['scale','offset','stale_s']]
            low,high=[float(v[k]) if v[k] else None for k in ['low_limit','high_limit']]
            # The same validation is applied for both insert and update.
            import math
            if not v['key'] or not v['name'] or not all(math.isfinite(n) for n in [scale,offset,stale]+[n for n in [low,high] if n is not None]) or stale<=0 or (low is not None and high is not None and low>high):raise ValueError('센서 설정 범위를 확인하세요.')
            if old:
                with self.db.connect() as db:db.execute('UPDATE signals SET key=?,name=?,unit=?,scale=?,offset=?,low_limit=?,high_limit=?,stale_s=? WHERE id=?',(v['key'],v['name'],v['unit'],scale,offset,low,high,stale,old['id']))
            else:self.db.add_signal(source['id'],v['key'],v['name'],v['unit'],scale,offset,low,high,stale)
            self.refresh_signals()
        Form(self,'센서 수정' if old else '센서 추가',fields,save)

    def demo(self):
        try:
            self.idle_required()
            existing={s['asset_code'] for s in self.db.sources()}
            for code,name,signals in [('DEMO-PLC','가상 PLC',[('temperature','온도','°C'),('pressure','압력','bar')]),('DEMO-ROBOT','가상 로봇',[('joint1','관절 1','deg'),('current','전류','A')]),('DEMO-ARDUINO','가상 아두이노',[('temperature','온도','°C'),('vibration','진동','g')])]:
                if code in existing:continue
                source=self.db.add_source(code,name,'DEMO LINE',name,'demo',{},.5,{'DEMO-PLC':'plc','DEMO-ROBOT':'robot','DEMO-ARDUINO':'arduino'}[code])
                for key,label,unit in signals:self.db.add_signal(source,key,label,unit,low=0,high=100)
            self.refresh()
        except Exception as e:messagebox.showerror('가상 공장',str(e))

    def start_all(self):
        try:
            for source in self.db.sources():self.engine.start(source['id'])
        except Exception as e:messagebox.showerror('수집 시작',str(e))
        self.refresh_sources()

    def start_selected(self):
        try:self.engine.start(self.selected_source()['id'])
        except Exception as e:messagebox.showerror('수집 시작',str(e))
        self.refresh_sources()

    def stop_selected(self):
        try:self.engine.stop(self.selected_source()['id'])
        except Exception as e:messagebox.showerror('수집 중지',str(e))

    def asset_choices(self):
        return {f"{a['id']} · {a['code']} / {a['name']}":a['id'] for a in self.db.query('SELECT * FROM assets ORDER BY id')}

    def job_form(self):
        choices=self.asset_choices()
        if not choices:messagebox.showinfo('생산 이력','설비 연결을 먼저 등록하세요.');return
        fields=[('asset','설비',next(iter(choices)),list(choices))]+[(k,t,d,None) for k,t,d in [('order','작업지시','WO-001'),('product','제품','제품 A'),('lot','LOT','LOT-001'),('process','공정','가공'),('state','운전 상태','running')]]
        def save(v):self.db.start_job(choices[v['asset']],v['order'],v['product'],v['lot'],v['process'],v['state']);self.refresh_jobs()
        Form(self,'생산 작업 시작',fields,save)

    def end_job(self):
        selected=self.jobs.selection()
        if selected:
            job=self.db.query('SELECT * FROM production_runs WHERE id=?',(int(selected[0]),))[0]
            if job['ended_utc'] is None:self.db.stop_job(job['asset_id'])
            self.refresh_jobs()

    def label_form(self):
        choices=self.asset_choices()
        if not choices:messagebox.showinfo('판정 등록','설비를 먼저 등록하세요.');return
        start=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec='milliseconds')
        fields=[('asset','설비',next(iter(choices)),list(choices)),('start','시작 시각 (시간대 포함)',start,None),('end','종료 시각 (시간대 포함)',utc(),None),('category','판정','normal',['normal','defect','failure','maintenance']),('note','고장 종류 / 판정 근거','',None)]
        def save(v):self.db.label(choices[v['asset']],v['start'],v['end'],v['category'],v['note']);self.refresh_labels()
        Form(self,'판정 구간 등록',fields,save)

    def export_data(self,fmt):
        if self.export_busy:messagebox.showinfo('내보내기','진행 중인 내보내기가 있습니다.');return
        path=filedialog.askdirectory(title='일별 Parquet 저장 폴더') if fmt=='daily' else filedialog.asksaveasfilename(defaultextension='.'+fmt,initialfile='manufacturing-features' if self.features.get() else 'manufacturing-telemetry',filetypes=[(fmt.upper(),'*.'+fmt)])
        if not path:return
        try:window=int(self.export_fields['window'].get())
        except ValueError:messagebox.showerror('내보내기','집계 구간은 정수입니다.');return
        args=dict(start=self.export_fields['start'].get() or None,end=self.export_fields['end'].get() or None,features=self.features.get(),window=window,parquet=fmt=='parquet')
        import threading
        self.export_busy=True
        def work():
            try:
                if fmt=='daily':
                    args.pop('parquet');rows=self.db.export_daily(path,**args)
                else:rows=self.db.export(path,**args)
                self.notify('export',{'rows':rows,'path':path})
            except Exception as e:self.notify('export_error',str(e))
        threading.Thread(target=work,daemon=True).start()

    def fill(self,table,rows):
        table.delete(*table.get_children())
        for key,values in rows:table.insert('','end',iid=str(key),values=tuple('' if v is None else v for v in values))

    def refresh_sources(self):
        selected=self.sources.selection();active=self.engine.active()
        self.fill(self.sources,[(s['id'],[s['id'],s['asset_code'],s['asset_name'],s['name'],s['protocol'],s['interval_s'],'수집 중' if s['id'] in active else '중지']) for s in self.db.sources()])
        if selected and self.sources.exists(selected[0]):self.sources.selection_set(selected[0])

    def refresh_signals(self):
        if not self.sources.selection():return
        self.fill(self.signals,[(s['id'],[s[k] for k in ['id','key','name','unit','scale','offset','low_limit','high_limit','stale_s']]) for s in self.db.signals(int(self.sources.selection()[0]))])

    def refresh_jobs(self):
        rows=self.db.query('SELECT p.*,a.code FROM production_runs p JOIN assets a ON a.id=p.asset_id ORDER BY p.id DESC LIMIT 500')
        self.fill(self.jobs,[(r['id'],[r[k] for k in ['id','code','work_order','product','lot','process','operating_state','started_utc','ended_utc']]) for r in rows])

    def refresh_labels(self):
        rows=self.db.query('SELECT l.*,a.code FROM labels l JOIN assets a ON a.id=l.asset_id ORDER BY l.id DESC LIMIT 500')
        self.fill(self.labels,[(r['id'],[r[k] for k in ['id','code','started_utc','ended_utc','category','note']]) for r in rows])

    def refresh(self):self.refresh_sources();self.refresh_signals();self.refresh_jobs();self.refresh_labels()

    def drain(self):
        changed=False;refresh=False
        for _ in range(100):
            try:kind,data=self.controls.get_nowait()
            except queue.Empty:
                try:kind,data=self.messages.get_nowait()
                except queue.Empty:break
            if kind=='data':
                for row in data:
                    self.latest[row['signal_id']]=row
                    self.traces.setdefault(row['signal_id'],deque(maxlen=120)).append(row['value'] if row['quality']=='good' else None)
                changed=True
            elif kind=='error':
                self.log_lines.append(utc()+' '+data['source']+' '+data['message']);self.log_lines=self.log_lines[-150:]
                self.log.configure(state='normal');self.log.delete('1.0','end');self.log.insert('end','\n'.join(self.log_lines));self.log.configure(state='disabled')
            elif kind=='stopped':refresh=True
            elif kind in {'export','export_error'}:
                self.export_busy=False
                if kind=='export':messagebox.showinfo('내보내기 완료',f"{data['rows']:,}행 저장\n{data['path']}\n조건 기록: .manifest.json")
                else:messagebox.showerror('내보내기 실패',data)
        if changed:
            selected=self.live.selection()
            self.fill(self.live,[(key,[r['source'],r['signal'],'—' if r['value'] is None else f"{r['value']:.4f}",r['unit'],r['quality'],r['time']]) for key,r in self.latest.items()])
            if selected and self.live.exists(selected[0]):self.live.selection_set(selected[0])
            elif self.live.get_children():self.live.selection_set(self.live.get_children()[0])
            self.draw_chart()
        if refresh:self.refresh_sources()
        self.status.set(f'수집 연결 {len(self.engine.active())}개 · 표시 센서 {len(self.latest)}개')
        if not self.closing:self.after(150,self.drain)

    def draw_chart(self):
        self.chart.delete('all');selected=self.live.selection()
        if not selected:return
        trace=list(self.traces.get(int(selected[0]),[]));values=[v for v in trace if v is not None]
        if not values:return
        w,h=self.chart.winfo_width(),self.chart.winfo_height()
        if w<100 or h<40:return
        low,high=min(values),max(values);span=high-low or 1
        self.chart.create_text(5,12,text=f'{high:.3f}',anchor='w',fill='#507080')
        self.chart.create_text(5,h-12,text=f'{low:.3f}',anchor='w',fill='#507080')
        segment=[]
        for i,v in enumerate(trace+[None]):
            if v is None:
                if len(segment)>=4:self.chart.create_line(*segment,fill='#158b8e',width=2)
                elif len(segment)==2:
                    x,y=segment;self.chart.create_oval(x-2,y-2,x+2,y+2,fill='#158b8e',outline='')
                segment=[]
            else:segment.extend([70+i*(w-90)/max(1,len(trace)-1),15+(high-v)*(h-30)/span])

    def close(self):
        if self.export_busy:messagebox.showinfo('내보내기 진행 중','내보내기가 끝난 후 종료하세요.');return
        self.engine.stop();self.withdraw()
        def finish():
            if self.engine.active():self.after(100,finish)
            else:self.closing=True;self.instance_lock.close();self.destroy()
        finish()


if __name__=='__main__':OperationsApp().mainloop()
