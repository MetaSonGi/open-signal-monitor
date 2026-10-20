"""Loopback, read-only bridge. Never constructs OperationsDB or alters sessions."""
import argparse
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs


class CollectorAPI(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,path,port=8808):
        self.database=Path(path).resolve()
        super().__init__(('127.0.0.1',port),Handler)
    def read(self,path,query):
        db=sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True,timeout=3)
        db.row_factory=sqlite3.Row
        try:
            first=db.execute('SELECT started_utc FROM acquisition_runs ORDER BY id LIMIT 1').fetchone()
            identity=f'{self.database}:{self.database.stat().st_ino}:{first[0] if first else "empty"}'
            dataset=hashlib.sha256(identity.encode()).hexdigest()[:24]
            if path=='/v1/catalog':
                assets=[dict(r) for r in db.execute('SELECT id,code,name,kind,location FROM assets ORDER BY id')]
                signals=[dict(r) for r in db.execute('SELECT s.id,s.name,s.unit,s.key,s.source_id,a.code asset_code,so.protocol FROM signals s JOIN sources so ON so.id=s.source_id JOIN assets a ON a.id=so.asset_id ORDER BY s.id')]
                return {'dataset_id':dataset,'assets':assets,'signals':signals}
            if path=='/v1/samples':
                after=int(query.get('after_id',['0'])[0]);limit=int(query.get('limit',['500'])[0])
                if after<0 or not 1<=limit<=1000:raise ValueError('after_id >= 0, limit 1..1000')
                rows=[dict(r) for r in db.execute('''SELECT t.id,t.signal_id,t.source_utc,t.ingested_utc,t.value,t.quality,t.unit,t.scale,t.offset,
                    t.signal_name,a.code asset_code FROM telemetry t JOIN signals s ON s.id=t.signal_id
                    JOIN sources so ON so.id=s.source_id JOIN assets a ON a.id=so.asset_id
                    WHERE t.id>? ORDER BY t.id LIMIT ?''',(after,limit))]
                return {'dataset_id':dataset,'samples':rows,'next_id':rows[-1]['id'] if rows else after}
            return None
        finally:db.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        try:
            url=urlsplit(self.path);result=self.server.read(url.path,parse_qs(url.query))
            self.respond(404 if result is None else 200,result or {'error':'unknown endpoint'})
        except (sqlite3.Error,OSError):self.respond(503,{'error':'수집 DB를 사용할 수 없습니다. 수집기를 먼저 실행하세요.'})
        except ValueError as e:self.respond(400,{'error':str(e)})
    def respond(self,status,data):
        raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)


def start_api(path,port=8808):
    server=CollectorAPI(path,port)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database',default=str(Path(__file__).parent/'data'/'manufacturing.sqlite3'));parser.add_argument('--port',type=int,default=8808)
    args=parser.parse_args()
    with CollectorAPI(args.database,args.port) as server:
        print(f'Read-only collector API: http://127.0.0.1:{server.server_address[1]}')
        try:server.serve_forever()
        except KeyboardInterrupt:pass
