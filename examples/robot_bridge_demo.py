"""Standalone synthetic telemetry bridge; not a robot manufacturer driver."""
import json
import math
import socketserver
import time
from datetime import datetime,timezone


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            while True:
                t=time.monotonic()
                record={'timestamp':datetime.now(timezone.utc).isoformat(),'values':{'joint1':30*math.sin(t/5),'current':2+math.sin(t/3),'running':True}}
                self.request.sendall((json.dumps(record)+'\n').encode())
                time.sleep(.5)
        except OSError:pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True


if __name__=='__main__':
    with Server(('127.0.0.1',15030),Handler) as server:
        print('Synthetic robot JSON bridge: 127.0.0.1:15030; Ctrl+C to stop.')
        try:server.serve_forever()
        except KeyboardInterrupt:pass
