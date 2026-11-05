import unittest
from unittest.mock import patch
from tools import l3_leaderboard_batch as b

class TrialProcessIdentity(unittest.TestCase):
    def check(self,container,argv,pid=123):
        with patch.object(b,'read',return_value={'container':container}),patch.object(b.Path,'read_bytes',return_value=bytes([0]).join(x.encode() for x in argv)):
            return b.trial_agent_live({'output':'/trial'},{'agent_pid':pid})
    def test_same_pid_other_container_is_not_live(self):
        self.assertFalse(self.check('l3-completed',['docker','exec','-i','l3-running','python3','/opt/l3-public/l3_native_agent.py']))
    def test_exact_agent_is_live(self):
        self.assertTrue(self.check('l3-trial',['/usr/bin/docker','exec','-i','l3-trial','python3','/opt/l3-public/l3_native_agent.py']))
    def test_non_agent_docker_exec_is_not_live(self):
        self.assertFalse(self.check('l3-trial',['docker','exec','-i','l3-trial','python3','other.py']))
    def test_missing_identity_is_not_live(self):
        self.assertFalse(self.check(None,[]))
        self.assertFalse(self.check('l3-trial',[],pid=None))
    def test_exited_process_is_not_live(self):
        with patch.object(b,'read',return_value={'container':'l3-trial'}),patch.object(b.Path,'read_bytes',side_effect=FileNotFoundError):
            self.assertFalse(b.trial_agent_live({'output':'/trial'},{'agent_pid':123}))

if __name__=='__main__':unittest.main()
