# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging
from twisted.internet import defer
from twisted.internet import reactor
from xml.etree import ElementTree

from nova import exception
from nova import flags
from nova import process
from nova import test
from nova import utils

FLAGS = flags.FLAGS


class ProcessTestCase(test.TrialTestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.DEBUG)
        super(ProcessTestCase, self).setUp()

    def test_execute_stdout(self):
        pool = process.ProcessPool(2)
        d = pool.simple_execute('echo test')
        def _check(rv):
            self.assertEqual(rv[0], 'test\n')
            self.assertEqual(rv[1], '')

        d.addCallback(_check)
        d.addErrback(self.fail)
        return d

    def test_execute_stderr(self):
        pool = process.ProcessPool(2)
        d = pool.simple_execute('cat BAD_FILE', error_ok=1)
        def _check(rv):
            self.assertEqual(rv[0], '')
            self.assert_('No such file' in rv[1])

        d.addCallback(_check)
        d.addErrback(self.fail)
        return d

    def test_execute_unexpected_stderr(self):
        pool = process.ProcessPool(2)
        d = pool.simple_execute('cat BAD_FILE')
        d.addCallback(lambda x: self.fail('should have raised an error'))
        d.addErrback(lambda failure: failure.trap(IOError))
        return d

    def test_max_processes(self):
        pool = process.ProcessPool(2)
        d1 = pool.simple_execute('sleep 0.01')
        d2 = pool.simple_execute('sleep 0.01')
        d3 = pool.simple_execute('sleep 0.005')
        d4 = pool.simple_execute('sleep 0.005')

        called = []
        def _called(rv, name):
            called.append(name)

        d1.addCallback(_called, 'd1')
        d2.addCallback(_called, 'd2')
        d3.addCallback(_called, 'd3')
        d4.addCallback(_called, 'd4')

        # Make sure that d3 and d4 had to wait on the other two and were called
        # in order
        # NOTE(termie): there may be a race condition in this test if for some
        #               reason one of the sleeps takes longer to complete
        #               than it should
        d4.addCallback(lambda x: self.assertEqual(called[2], 'd3'))
        d4.addCallback(lambda x: self.assertEqual(called[3], 'd4'))
        d4.addErrback(self.fail)
        return d4

    def test_kill_long_process(self):
        pool = process.ProcessPool(2)

        d1 = pool.simple_execute('sleep 1')
        d2 = pool.simple_execute('sleep 0.005')

        timeout = reactor.callLater(0.1, self.fail, 'should have been killed')

        # kill d1 and wait on it to end then cancel the timeout
        d2.addCallback(lambda _: d1.process.signalProcess('KILL'))
        d2.addCallback(lambda _: d1)
        d2.addBoth(lambda _: timeout.active() and timeout.cancel())
        d2.addErrback(self.fail)
        return d2

    def test_process_exit_is_contained(self):
        pool = process.ProcessPool(2)

        d1 = pool.simple_execute('sleep 1')
        d1.addCallback(lambda x: self.fail('should have errbacked'))
        d1.addErrback(lambda fail: fail.trap(IOError))
        reactor.callLater(0.05, d1.process.signalProcess, 'KILL')

        return d1

    def test_shared_pool_is_singleton(self):
        pool1 = process.SharedPool()
        pool2 = process.SharedPool()
        self.assertEqual(id(pool1._instance), id(pool2._instance))

    def test_shared_pool_works_as_singleton(self):
        d1 = process.simple_execute('sleep 1')
        d2 = process.simple_execute('sleep 0.005')
        # lp609749: would have failed with
        # exceptions.AssertionError: Someone released me too many times:
        # too many tokens!
        return d1
