"""Read-only inputs producing a common per-channel envelope."""
import json
import math
import os
import socket
import struct
import time
from urllib.parse import urlsplit
from protocol import read_registers


def envelope(payload, signals):
    if not isinstance(payload,dict) or not isinstance(payload.get('values',payload),dict):
        raise ValueError('수신 JSON은 values 객체 또는 센서 이름:숫자 객체여야 합니다.')
    values=payload.get('values',payload);result={}
    for signal in signals:
        key=signal['key'];v=values.get(key)
        if isinstance(v,dict):
            result[key]={'value':v.get('value'),'timestamp':v.get('timestamp',payload.get('timestamp')),'quality':v.get('quality','good')}
        else:
            result[key]={'value':int(v) if isinstance(v,bool) else v,'timestamp':payload.get('timestamp'),'quality':'good'}
    return result


class Demo:
    def __init__(self,config):self.config=config
    def read(self,signals):
        return {s['key']:{'value':25+10*i+4*math.sin(time.monotonic()/4+i),'quality':'good'} for i,s in enumerate(signals)}
    def close(self):pass


class Modbus:
    def __init__(self,config):self.config=config
    def read(self,signals):
        c=self.config;out={}
        for s in signals:
            parts=s['key'].split(':');address=int(parts[0]);kind=parts[1] if len(parts)>1 else 'u16'
            if kind not in {'u16','i16','u32','i32','f32'} or len(parts)>3 or (len(parts)==3 and parts[2]!='swap'):
                raise ValueError('Modbus 주소: 0 또는 0:f32 또는 0:f32:swap 형식입니다.')
            words=read_registers(c['host'],int(c.get('port',502)),int(c.get('unit',1)),address,2 if kind.endswith('32') else 1,int(c.get('function',3)),float(c.get('timeout',2)))
            if len(parts)==3:words.reverse()
            data=struct.pack('>'+'H'*len(words),*words)
            value=struct.unpack('>'+{'u16':'H','i16':'h','u32':'I','i32':'i','f32':'f'}[kind],data)[0]
            out[s['key']]={'value':value,'quality':'good'}
        return out
    def close(self):pass


class OPCUA:
    def __init__(self,config):self.config=config;self.client=None
    def read(self,signals):
        from asyncua.sync import Client
        if self.client is None:
            endpoint=self.config['endpoint']
            if urlsplit(endpoint).username:
                raise ValueError('OPC 주소에 비밀번호를 포함하지 마세요. 환경변수 설정을 사용하세요.')
            client=Client(endpoint,timeout=float(self.config.get('timeout',3)))
            try:
                if self.config.get('username_env'):client.set_user(os.environ[self.config['username_env']])
                if self.config.get('password_env'):client.set_password(os.environ[self.config['password_env']])
                if self.config.get('security_string'):client.set_security_string(self.config['security_string'])
                client.connect()
                self.client=client
            except Exception:
                client.disconnect()
                raise
        out={}
        for s in signals:
            dv=self.client.get_node(s['key']).read_data_value(raise_on_bad_status=False)
            value=dv.Value.Value if dv.Value else None
            out[s['key']]={'value':int(value) if isinstance(value,bool) else value,
                'timestamp':dv.SourceTimestamp.isoformat() if dv.SourceTimestamp else None,
                'quality':'good' if dv.StatusCode.is_good() else 'device_bad','detail':str(dv.StatusCode)}
        return out
    def close(self):
        if self.client:
            try:self.client.disconnect()
            finally:self.client=None


class JSONStream:
    def __init__(self,config):self.config=config;self.stream=None;self.buffer=bytearray()
    def connect(self):raise NotImplementedError
    def chunk(self):raise NotImplementedError
    def read(self,signals):
        if self.stream is None:self.connect()
        deadline=time.monotonic()+float(self.config.get('timeout',2))
        while b'\n' not in self.buffer:
            if time.monotonic()>deadline:raise TimeoutError('한 줄 데이터 수신 시간 초과')
            chunk=self.chunk()
            if chunk:self.buffer.extend(chunk)
            if len(self.buffer)>65536:raise ValueError('수신 프레임이 64 KiB를 초과했습니다.')
        line,_,rest=self.buffer.partition(b'\n');self.buffer=bytearray(rest)
        return envelope(json.loads(line.decode('utf-8')),signals)
    def close(self):
        if self.stream:self.stream.close()
        self.stream=None;self.buffer.clear()


class SerialJSON(JSONStream):
    def connect(self):
        import serial
        self.stream=serial.serial_for_url(self.config['port'],baudrate=int(self.config.get('baud',115200)),timeout=.2)
    def chunk(self):return self.stream.read(max(1,min(self.stream.in_waiting,4096)))


class RobotJSON(JSONStream):
    def connect(self):
        self.stream=socket.create_connection((self.config['host'],int(self.config['port'])),timeout=float(self.config.get('timeout',2)))
        self.stream.settimeout(.2)
    def chunk(self):
        try:
            data=self.stream.recv(4096)
            if not data:raise ConnectionError('로봇 브리지의 연결이 종료됐습니다.')
            return data
        except socket.timeout:return b''


def adapter(protocol,config):
    return {'demo':Demo,'modbus_tcp':Modbus,'opcua':OPCUA,'serial_json':SerialJSON,'robot_json':RobotJSON}[protocol](config)
