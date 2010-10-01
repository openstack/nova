import unittest
import webob
import webob.dec
import webob.exc

from nova.api.rackspace import faults

class TestFaults(unittest.TestCase):

    def test_fault_parts(self):
        req = webob.Request.blank('/.xml')
        f = faults.Fault(webob.exc.HTTPBadRequest(explanation='scram'))
        resp = req.get_response(f)

        first_two_words = resp.body.strip().split()[:2]
        self.assertEqual(first_two_words, ['<badRequest', 'code="400">'])
        body_without_spaces = ''.join(resp.body.split())
        self.assertTrue('<message>scram</message>' in body_without_spaces)

    def test_retry_header(self):
        req = webob.Request.blank('/.xml')
        exc = webob.exc.HTTPRequestEntityTooLarge(explanation='sorry', 
                                                  headers={'Retry-After': 4})
        f = faults.Fault(exc)
        resp = req.get_response(f)
        first_two_words = resp.body.strip().split()[:2]
        self.assertEqual(first_two_words, ['<overLimit', 'code="413">'])
        body_sans_spaces = ''.join(resp.body.split())
        self.assertTrue('<message>sorry</message>' in body_sans_spaces)
        self.assertTrue('<retryAfter>4</retryAfter>' in body_sans_spaces)
        self.assertEqual(resp.headers['Retry-After'], 4)

    def test_raise(self):
        @webob.dec.wsgify
        def raiser(req):
            raise faults.Fault(webob.exc.HTTPNotFound(explanation='whut?'))
        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual(resp.status_int, 404)
        self.assertTrue('whut?' in resp.body)
