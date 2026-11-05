import os,socket,tempfile,unittest
from pathlib import Path
class RotationTests(unittest.TestCase):
 def test_socket_swap_preserves_existing_stream_and_routes_new_clients(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);live=p/'api.sock';next=p/'next.sock'
   with socket.socket(socket.AF_UNIX) as old,socket.socket(socket.AF_UNIX) as new,socket.socket(socket.AF_UNIX) as first,socket.socket(socket.AF_UNIX) as second:
    for sock in [old,new,first,second]:sock.settimeout(2)
    old.bind(str(live));old.listen();first.connect(str(live))
    connection,_=old.accept()
    with connection:
     new.bind(str(next));new.listen();os.replace(next,live)
     second.connect(str(live));replacement,_=new.accept()
     with replacement:
      first.sendall(b'old remains alive');self.assertEqual(connection.recv(64),b'old remains alive')
      second.sendall(b'new routing');self.assertEqual(replacement.recv(64),b'new routing')
if __name__=='__main__':unittest.main()
