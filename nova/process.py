# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
# 
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
# 
#        http://www.apache.org/licenses/LICENSE-2.0
# 
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Process pool, still buggy right now.
"""

import logging
import multiprocessing

from nova import vendor
from twisted.internet import defer
from twisted.internet import reactor
from twisted.internet import protocol
from twisted.internet import threads

# NOTE(termie): this is copied from twisted.internet.utils but since
#               they don't export it I've copied.
class _BackRelay(protocol.ProcessProtocol):
    """
    Trivial protocol for communicating with a process and turning its output
    into the result of a L{Deferred}.

    @ivar deferred: A L{Deferred} which will be called back with all of stdout
        and, if C{errortoo} is true, all of stderr as well (mixed together in
        one string).  If C{errortoo} is false and any bytes are received over
        stderr, this will fire with an L{_UnexpectedErrorOutput} instance and
        the attribute will be set to C{None}.

    @ivar onProcessEnded: If C{errortoo} is false and bytes are received over
        stderr, this attribute will refer to a L{Deferred} which will be called
        back when the process ends.  This C{Deferred} is also associated with
        the L{_UnexpectedErrorOutput} which C{deferred} fires with earlier in
        this case so that users can determine when the process has actually
        ended, in addition to knowing when bytes have been received via stderr.
    """

    def __init__(self, deferred, errortoo=0):
        self.deferred = deferred
        self.s = StringIO.StringIO()
        if errortoo:
            self.errReceived = self.errReceivedIsGood
        else:
            self.errReceived = self.errReceivedIsBad

    def errReceivedIsBad(self, text):
        if self.deferred is not None:
            self.onProcessEnded = defer.Deferred()
            err = _UnexpectedErrorOutput(text, self.onProcessEnded)
            self.deferred.errback(failure.Failure(err))
            self.deferred = None
            self.transport.loseConnection()

    def errReceivedIsGood(self, text):
        self.s.write(text)

    def outReceived(self, text):
        self.s.write(text)

    def processEnded(self, reason):
        if self.deferred is not None:
            self.deferred.callback(self.s.getvalue())
        elif self.onProcessEnded is not None:
            self.onProcessEnded.errback(reason)


class BackRelayWithInput(_BackRelay):
    def __init__(self, deferred, errortoo=0, input=None):
        super(BackRelayWithInput, self).__init__(deferred, errortoo)
        self.input = input

    def connectionMade(self):
        if self.input:
            self.transport.write(self.input)
        self.transport.closeStdin()


def getProcessOutput(executable, args=None, env=None, path=None, reactor=None,
                     errortoo=0, input=None):
    if reactor is None:
        from twisted.internet import reactor
    args = args and args or ()
    env = env and env and {}
    d = defer.Deferred()
    p = BackRelayWithInput(d, errortoo=errortoo, input=input)
    reactor.spawnProcess(p, executable, (executable,)+tuple(args), env, path)
    return d


class Pool(object):
    """ A simple process pool implementation around mutliprocessing.

    Allows up to `size` processes at a time and queues the rest.

    Using workarounds for multiprocessing behavior described in:
    http://pypi.python.org/pypi/twisted.internet.processes/1.0b1
    """

    def __init__(self, size=None):
        self._size = size
        self._pool = multiprocessing.Pool(size)
        self._registerShutdown()

    def _registerShutdown(self):
        reactor.addSystemEventTrigger(
                'during', 'shutdown', self.shutdown, reactor)

    def shutdown(self, reactor=None):
        if not self._pool:
            return
        self._pool.close()
        # wait for workers to finish
        self._pool.terminate()
        self._pool = None

    def apply(self, f, *args, **kw):
        """ Add a task to the pool and return a deferred. """
        result = self._pool.apply_async(f, args, kw)
        return threads.deferToThread(result.get)
