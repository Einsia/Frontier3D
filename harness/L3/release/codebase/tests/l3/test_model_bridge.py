import email.message
import unittest
from tools.l3_model_bridge import upstream_headers

class ModelBridgeTests(unittest.TestCase):
    def test_mixed_case_headers_cannot_duplicate_content_type_or_authorization(self):
        incoming=email.message.Message()
        for key,value in [('content-type','application/json'),('Content-Type','application/json'),
                          ('authorization','Bearer container-placeholder'),('Host','127.0.0.1:8765'),
                          ('User-Agent','codex-test'),('Content-Length','123')]:incoming[key]=value
        forwarded=upstream_headers(incoming,'host-only-test-key')
        self.assertEqual(sum(k.lower()=='content-type' for k in forwarded),1)
        self.assertEqual(forwarded['authorization'],'Bearer host-only-test-key')
        self.assertEqual(forwarded['user-agent'],'codex-test')
        self.assertNotIn('host',forwarded)
        self.assertNotIn('content-length',forwarded)
