import csv
import io
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from protocol import read_registers, start_demo, ProtocolError
from storage import Store


class ProtocolTests(unittest.TestCase):
    def scripted_response(self, mode):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        requests = []
        def serve():
            with listener:
                connection, _ = listener.accept()
                with connection:
                    req = b''
                    while len(req) < 12:
                        req += connection.recv(12-len(req))
                    requests.append(req)
                    transaction = req[:2]
                    if mode == 'exception':
                        answer = transaction + bytes.fromhex('00000003018302')
                    elif mode == 'truncated':
                        answer = transaction + bytes.fromhex('000000070103040001')
                    elif mode == 'mismatch':
                        answer = bytes.fromhex('ffff000000070103040001ffff')
                        if transaction == b'\xff\xff':
                            answer = b'\x00\x00' + answer[2:]
                    else:
                        answer = transaction + bytes.fromhex('000000070103040001ffff')
                    for byte in answer:
                        try:
                            connection.sendall(bytes([byte]))
                        except OSError:
                            break  # A rejected header lets the client close immediately.
        thread = threading.Thread(target=serve,daemon=True)
        thread.start()
        return port, requests, thread

    def test_fragmented_known_wire_vector(self):
        port, requests, thread = self.scripted_response('valid')
        self.assertEqual(read_registers('127.0.0.1',port,1,0,2),[1,65535])
        thread.join(2)
        self.assertEqual(requests[0][2:],bytes.fromhex('00000006010300000002'))

    def test_exceptions_truncation_and_wrong_transaction(self):
        for mode in ['exception','truncated','mismatch']:
            with self.subTest(mode=mode):
                port, _, thread = self.scripted_response(mode)
                with self.assertRaises(ProtocolError):
                    read_registers('127.0.0.1',port,1,0,2)
                thread.join(2)

    def test_invalid_input(self):
        for address,count in [(65535,2),(-1,1),(0,126),(0,0)]:
            with self.assertRaises(ValueError):
                read_registers('127.0.0.1',1,1,address,count)

    def test_demo_functions_and_address_exception(self):
        server = start_demo(0)
        try:
            port=server.server_address[1]
            for function in [3,4]:
                values=read_registers('127.0.0.1',port,1,0,3,function)
                self.assertEqual(len(values),3)
                self.assertTrue(all(0<=v<=65535 for v in values))
            with self.assertRaises(ProtocolError):
                read_registers('127.0.0.1',port,1,127,2)
        finally:
            server.shutdown()
            server.server_close()


class StorageTests(unittest.TestCase):
    def test_session_values_history_and_safe_export(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'test.sqlite3')
            config=dict(name='=unsafe',host='127.0.0.1',port=502,unit=1,function=3,address=4,count=2,interval=1,scale=.1,signed=True)
            session,channels=store.begin(config)
            store.record(channels,[65535,100],[-.1,10],2.5)
            store.event(session,'test error')
            store.finish(session)
            rows=store.history()
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[1][2:5],(4,65535,-.1))
            output=io.StringIO()
            store.export(output)
            exported=list(csv.reader(io.StringIO(output.getvalue())))
            self.assertEqual(exported[1][1],"'=unsafe")
            self.assertEqual(len(exported),3)
            with store.connect() as db:
                self.assertIsNotNone(db.execute('SELECT stopped_utc FROM sessions').fetchone()[0])
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])


if __name__=='__main__':
    unittest.main()
