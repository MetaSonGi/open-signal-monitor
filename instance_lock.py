import os


class InstanceLock:
    def __init__(self,path):
        path.parent.mkdir(parents=True,exist_ok=True)
        self.file=open(path,'a+b')
        try:
            self.file.seek(0,2)
            if self.file.tell()==0:self.file.write(b'0');self.file.flush()
            self.file.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('이 데이터베이스를 사용하는 운영 화면이 이미 실행 중입니다.')
    def close(self):self.file.close()
