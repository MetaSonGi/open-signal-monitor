import json
import threading
import time
from adapters import adapter


class Engine:
    def __init__(self,db,notify=None):
        self.db=db;self.notify=notify or (lambda *args:None)
        self.tasks={};self.lock=threading.Lock()

    def active(self):
        with self.lock:return [sid for sid,(event,thread) in self.tasks.items() if thread.is_alive()]

    def start(self,source_id):
        with self.lock:
            if source_id in self.tasks and self.tasks[source_id][1].is_alive():return
            source=next(s for s in self.db.sources() if s['id']==source_id)
            signals=self.db.signals(source_id)
            if not signals:raise ValueError('먼저 센서를 등록하세요.')
            event=threading.Event()
            thread=threading.Thread(target=self._collect,args=(source,signals,event),daemon=True)
            self.tasks[source_id]=(event,thread);thread.start()

    def stop(self,source_id=None):
        with self.lock:
            for sid,(event,thread) in self.tasks.items():
                if source_id is None or sid==source_id:event.set()

    def _collect(self,source,signals,event):
        run=None;client=None;previous={}
        try:
            run=self.db.begin(source,signals)
            while not event.is_set():
                started=time.monotonic()
                try:
                    if client is None:client=adapter(source['protocol'],json.loads(source['config_json']))
                    packet=client.read(signals)
                except Exception as e:
                    # Avoid echoing credentials from third-party exceptions.
                    message=f'{type(e).__name__}: 수신 실패. 주소·매핑·패키지·장치 상태를 확인하세요.'
                    self.db.incident(source['id'],message)
                    self.notify('error',{'source':source['name'],'message':message})
                    packet={s['key']:{'value':None,'quality':'missing','detail':message} for s in signals}
                    if client:
                        try:client.close()
                        except Exception:pass
                    client=None
                records=self.db.record(source,run,signals,packet,(time.monotonic()-started)*1000,previous)
                self.notify('data',records)
                event.wait(max(.05,source['interval_s']-(time.monotonic()-started)))
        except Exception as e:
            self.notify('error',{'source':source['name'],'message':f'수집 중단: {type(e).__name__}'})
        finally:
            if client:
                try:client.close()
                except Exception:pass
            if run:
                try:self.db.finish(run)
                except Exception:self.notify('error',{'source':source['name'],'message':'수집 종료 기록 실패'})
            self.notify('stopped',source['id'])
