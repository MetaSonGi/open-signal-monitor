import csv
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from collections import deque
from protocol import read_registers, start_demo
from storage import Store

BASE = Path(__file__).resolve().parent


class Monitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('OpenSignal Monitor · 공개 규격 데이터 모니터')
        self.geometry('1100x760')
        self.minsize(900, 640)
        self.configure(bg='#edf2f7')
        self.store = Store(BASE / 'data' / 'monitor.sqlite3')
        self.messages = queue.Queue(maxsize=500)
        self.stop_event = threading.Event()
        self.worker = None
        self.demo = None
        self.points = deque(maxlen=120)
        self.success = self.errors = 0
        self.state_text = tk.StringVar(value='대기 중 · 시뮬레이터로 시작해보세요')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TFrame', background='#edf2f7')
        style.configure('TLabel', background='#edf2f7', font=('맑은 고딕', 10))
        style.configure('TButton', font=('맑은 고딕', 10), padding=7)
        style.configure('Treeview', rowheight=28, font=('맑은 고딕', 10))
        style.configure('Treeview.Heading', font=('맑은 고딕', 10, 'bold'))
        frame = ttk.Frame(self, padding=22)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='OpenSignal Monitor', font=('맑은 고딕', 23, 'bold'), foreground='#12314d').pack(anchor='w')
        ttk.Label(frame, text='Modbus TCP  →  실시간 확인  →  SQLite 기록', foreground='#526b80').pack(anchor='w', pady=(4, 14))
        settings = ttk.LabelFrame(frame, text='연결 설정', padding=12)
        settings.pack(fill='x')
        self.fields = {}
        specs = [('name','장치 이름','Demo Device'), ('host','장치 주소','127.0.0.1'), ('port','TCP 포트','15020'),
                 ('unit','장치 번호','1'), ('address','시작 주소 (0부터)','0'), ('count','레지스터 개수','3'),
                 ('interval','수집 간격 (초)','1'), ('scale','값 배율','0.1')]
        self.inputs = []
        for i, (key, title, default) in enumerate(specs):
            col, row = i % 4, (i // 4) * 2
            ttk.Label(settings, text=title).grid(row=row, column=col, sticky='w', padx=8)
            var = tk.StringVar(value=default)
            entry = ttk.Entry(settings, textvariable=var)
            entry.grid(row=row+1, column=col, sticky='ew', padx=8, pady=(3, 9))
            self.fields[key] = var
            self.inputs.append(entry)
            settings.columnconfigure(col, weight=1)
        self.function = tk.StringVar(value='03 Holding Registers')
        self.function_box = ttk.Combobox(settings, textvariable=self.function, state='readonly', values=['03 Holding Registers','04 Input Registers'])
        self.function_box.grid(row=4, column=0, columnspan=2, sticky='ew', padx=8)
        self.signed = tk.BooleanVar(value=False)
        self.signed_box = ttk.Checkbutton(settings, text='16비트 부호 있는 값으로 해석', variable=self.signed)
        self.signed_box.grid(row=4, column=2, columnspan=2, sticky='w', padx=8)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=12)
        self.demo_button = ttk.Button(buttons, text='시뮬레이터로 시작', command=self.start_simulation)
        self.demo_button.pack(side='left', padx=(0,8))
        self.start_button = ttk.Button(buttons, text='장치 수집 시작', command=self.start)
        self.start_button.pack(side='left', padx=(0,8))
        self.stop_button = ttk.Button(buttons, text='수집 중지', command=self.stop, state='disabled')
        self.stop_button.pack(side='left')
        ttk.Button(buttons, text='전체 기록 CSV 저장', command=self.export).pack(side='right')
        ttk.Label(frame, textvariable=self.state_text, foreground='#176e69').pack(anchor='w', pady=(0,10))
        tabs = ttk.Notebook(frame)
        tabs.pack(fill='both', expand=True)
        live, history, logs = [ttk.Frame(tabs, padding=10) for _ in range(3)]
        tabs.add(live, text=' 실시간 ')
        tabs.add(history, text=' 저장 기록 ')
        tabs.add(logs, text=' 통신 로그 ')
        self.table = self.make_table(live, ['주소','원시값 (UInt16)','변환값','갱신 시각 (UTC)'], height=5)
        self.table.pack(fill='x')
        ttk.Label(live, text='첫 번째 레지스터 · 최근 120회 수신값', foreground='#526b80').pack(anchor='w', pady=(12,4))
        self.chart = tk.Canvas(live, background='white', height=170, highlightthickness=0)
        self.chart.pack(fill='both', expand=True)
        self.chart.bind('<Configure>', lambda event: self.draw_chart())
        ttk.Button(history, text='기록 새로 고침 (최근 1,000개)', command=self.refresh_history).pack(anchor='w', pady=(0,8))
        self.history = self.make_table(history, ['수집 시각 (UTC)','장치','주소','원시값','변환값','응답 ms'])
        self.history.pack(fill='both', expand=True)
        self.logs = tk.Text(logs, font=('맑은 고딕',10), state='disabled', wrap='word', background='white')
        self.logs.pack(fill='both', expand=True)
        ttk.Label(frame, text='읽기 전용 FC03 / FC04  ·  가상 레지스터 0–127  ·  저장 위치: data/monitor.sqlite3', foreground='#60778a').pack(anchor='w', pady=(10,0))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.drain)
        self.refresh_history()

    def make_table(self, parent, columns, height=12):
        table = ttk.Treeview(parent, columns=columns, show='headings', height=height)
        for c in columns:
            table.heading(c, text=c)
            table.column(c, width=115, anchor='center')
        table.column(columns[0], width=200)
        return table

    def config(self):
        f = {k:v.get().strip() for k,v in self.fields.items()}
        c = {k:int(f[k]) for k in ['port','unit','address','count']}
        c.update({k:float(f[k]) for k in ['interval','scale']})
        c.update(name=f['name'],host=f['host'],signed=self.signed.get(),function=int(self.function.get()[:2]))
        if not c['host'] or not c['name'] or len(c['name'])>100:
            raise ValueError('장치 이름(100자 이하)과 주소를 입력하세요.')
        if not 1<=c['port']<=65535 or not 0<=c['unit']<=255:
            raise ValueError('포트는 1~65535, 장치 번호는 0~255입니다.')
        if not 1<=c['count']<=125 or not 0<=c['address'] or c['address']+c['count']>65536:
            raise ValueError('주소는 0~65535, 개수는 1~125이며 주소 범위를 넘을 수 없습니다.')
        if not math.isfinite(c['interval']) or not .2<=c['interval']<=3600 or not math.isfinite(c['scale']) or abs(c['scale'])>1e12:
            raise ValueError('간격은 0.2~3600초, 배율은 유한한 ±1조 이내 숫자입니다.')
        return c

    def start_simulation(self):
        if self.worker and self.worker.is_alive():
            return
        if self.demo is None:
            try:
                self.demo = start_demo(0)
            except OSError as e:
                messagebox.showerror('시뮬레이터 시작 실패', str(e))
                return
        for k,v in dict(name='Demo Device',host='127.0.0.1',port=str(self.demo.server_address[1]),unit='1',address='0',count='3',interval='1',scale='0.1').items():
            self.fields[k].set(v)
        self.start()

    def set_running(self, running):
        for entry in self.inputs:
            entry.configure(state='disabled' if running else 'normal')
        self.function_box.configure(state='disabled' if running else 'readonly')
        self.signed_box.configure(state='disabled' if running else 'normal')
        for button in [self.start_button,self.demo_button]:
            button.configure(state='disabled' if running else 'normal')
        self.stop_button.configure(state='normal' if running else 'disabled')

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            config = self.config()
            session, channels = self.store.begin(config)
        except Exception as e:
            messagebox.showerror('설정 확인',str(e))
            return
        self.stop_event.clear()
        self.points.clear()
        self.table.delete(*self.table.get_children())
        self.success = self.errors = 0
        self.set_running(True)
        self.state_text.set('연결 중…')
        self.worker = threading.Thread(target=self.collect,args=(config,session,channels),daemon=True)
        self.worker.start()

    def collect(self, c, session, channels):
        try:
            while not self.stop_event.is_set():
                started = time.monotonic()
                try:
                    raw = read_registers(c['host'],c['port'],c['unit'],c['address'],c['count'],c['function'])
                    latency = (time.monotonic()-started)*1000
                    values = [(v-65536 if c['signed'] and v>=32768 else v)*c['scale'] for v in raw]
                    stamp = self.store.record(channels,raw,values,latency)
                    self.messages.put(('data',(c['address'],raw,values,stamp,latency)))
                except Exception as e:
                    self.store.event(session,str(e))
                    self.messages.put(('error',str(e)))
                self.stop_event.wait(max(.05,c['interval']-(time.monotonic()-started)))
        except Exception as e:
            self.messages.put(('error','기록 작업 실패: '+str(e)))
        finally:
            try:
                self.store.finish(session)
            except Exception as e:
                self.messages.put(('error','종료 기록 실패: '+str(e)))
            self.messages.put(('done',None))

    def stop(self):
        self.stop_event.set()
        self.stop_button.configure(state='disabled')
        self.state_text.set('수집 중지 중…')

    def drain(self):
        for _ in range(100):
            try:
                kind, data = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == 'data':
                address,raw,values,stamp,latency=data
                self.success+=1
                self.table.delete(*self.table.get_children())
                for i,(r,v) in enumerate(zip(raw,values)):
                    self.table.insert('', 'end', values=(address+i,r,f'{v:.4f}',stamp))
                self.points.append(values[0])
                self.draw_chart()
                self.state_text.set(f'수집 중  ·  성공 {self.success}회  ·  오류 {self.errors}회  ·  최근 응답 {latency:.1f} ms')
            elif kind == 'error':
                self.errors+=1
                self.log(data)
                self.state_text.set(f'연결/기록 확인 필요  ·  오류 {self.errors}회  ·  자동 재시도 중')
            elif kind == 'done':
                self.set_running(False)
                self.state_text.set(f'수집 종료  ·  성공 {self.success}회  ·  오류 {self.errors}회')
                self.refresh_history()
        self.after(100,self.drain)

    def log(self, text):
        self.logs.configure(state='normal')
        self.logs.insert('end',time.strftime('%H:%M:%S')+'  '+text+'\n')
        if int(self.logs.index('end-1c').split('.')[0])>500:
            self.logs.delete('1.0','100.0')
        self.logs.see('end')
        self.logs.configure(state='disabled')

    def draw_chart(self):
        canvas=self.chart
        canvas.delete('all')
        width,height=canvas.winfo_width(),canvas.winfo_height()
        if width<100 or height<70:
            return
        if not self.points:
            canvas.create_text(width/2,height/2,text='수집을 시작하면 추이가 표시됩니다.',fill='#71869a')
            return
        low,high=min(self.points),max(self.points)
        span=high-low or max(1,abs(high)*.1)
        for i in range(4):
            y=20+(height-40)*i/3
            canvas.create_line(60,y,width-15,y,fill='#e8eef4')
            canvas.create_text(50,y,text=f'{high-span*i/3:.2f}',anchor='e',fill='#526b80')
        coordinates=[]
        for i,v in enumerate(self.points):
            coordinates.extend([60+(width-80)*i/max(1,len(self.points)-1),20+(height-40)*(high-v)/span])
        if len(coordinates)>=4:
            canvas.create_line(*coordinates,fill='#087e8b',width=3)
        else:
            x,y=coordinates
            canvas.create_oval(x-3,y-3,x+3,y+3,fill='#087e8b',outline='')

    def refresh_history(self):
        try:
            rows=self.store.history()
            self.history.delete(*self.history.get_children())
            for row in rows:
                self.history.insert('','end',values=(*row[:4],f'{row[4]:.4f}',f'{row[5]:.1f}'))
        except Exception as e:
            messagebox.showerror('기록 조회 실패',str(e))

    def export(self):
        path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile='signal-readings.csv',filetypes=[('CSV','*.csv')])
        if path:
            try:
                with open(path,'w',encoding='utf-8-sig',newline='') as stream:
                    self.store.export(stream)
                messagebox.showinfo('저장 완료',path)
            except Exception as e:
                messagebox.showerror('저장 실패',str(e))

    def close(self):
        self.stop_event.set()
        self.withdraw()
        def finish():
            if self.worker and self.worker.is_alive():
                self.after(100,finish)
                return
            if self.demo:
                self.demo.shutdown()
                self.demo.server_close()
            self.destroy()
        finish()


if __name__=='__main__':
    Monitor().mainloop()
