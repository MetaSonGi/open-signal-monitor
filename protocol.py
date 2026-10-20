"""Small read-only Modbus TCP implementation from the public wire specification."""
import socket
import struct
import threading
import socketserver
import math
import time


class ProtocolError(Exception):
    pass


def receive(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ProtocolError('상대 장치가 연결을 종료했습니다.')
        data.extend(chunk)
    return bytes(data)


def read_registers(host, port, unit, address, count, function=3, timeout=2):
    if function not in (3, 4) or not 1 <= count <= 125:
        raise ValueError('지원 기능은 03/04이며 개수는 1~125입니다.')
    if not 0 <= address <= 65535 or address + count > 65536:
        raise ValueError('레지스터 주소 범위를 확인하세요.')
    if not 0 <= unit <= 255 or not 1 <= port <= 65535:
        raise ValueError('장치 번호 또는 포트 범위를 확인하세요.')
    transaction = time.monotonic_ns() & 65535
    packet = struct.pack('>HHHBBHH', transaction, 0, 6, unit, function, address, count)
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(packet)
        tid, protocol, length, returned_unit = struct.unpack('>HHHB', receive(sock, 7))
        if tid != transaction or protocol != 0 or returned_unit != unit or not 2 <= length <= 254:
            raise ProtocolError('잘못된 Modbus 응답 헤더입니다.')
        payload = receive(sock, length - 1)
        if payload[0] == function | 128:
            if len(payload) != 2:
                raise ProtocolError('잘못된 예외 응답입니다.')
            raise ProtocolError(f'Modbus 예외 코드: {payload[1]}')
        if payload[0] != function or len(payload) != 2 + count * 2 or payload[1] != count * 2:
            raise ProtocolError('응답 기능 또는 데이터 길이가 일치하지 않습니다.')
        return list(struct.unpack('>' + 'H' * count, payload[2:]))


class DemoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(3)
        try:
            while True:
                tid, proto, length, unit = struct.unpack('>HHHB', receive(self.request, 7))
                if proto != 0 or not 2 <= length <= 254:
                    return
                pdu = receive(self.request, length - 1)
                func = pdu[0]
                if func not in (3, 4):
                    response = bytes([func | 128, 1])
                elif len(pdu) != 5:
                    response = bytes([func | 128, 3])
                else:
                    address, count = struct.unpack('>HH', pdu[1:])
                    if not 1 <= count <= 125:
                        response = bytes([func | 128, 3])
                    elif address + count > 128:
                        response = bytes([func | 128, 2])
                    else:
                        tick = time.monotonic()
                        values = [int(1000 + i * 100 + 100 * math.sin(tick / 3 + i)) for i in range(address, address + count)]
                        response = bytes([func, count * 2]) + struct.pack('>' + 'H' * count, *values)
                self.request.sendall(struct.pack('>HHHB', tid, 0, len(response) + 1, unit) + response)
        except (OSError, ProtocolError):
            return


class DemoServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_demo(port=15020):
    server = DemoServer(('127.0.0.1', port), DemoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
