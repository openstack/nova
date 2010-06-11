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
import StringIO

from nova import vendor
from twisted.internet import defer
from twisted.internet import error
from twisted.internet import process
from twisted.internet import protocol
from twisted.internet import reactor
from twisted.internet import threads
from twisted.python import failure

from nova import flags

FLAGS = flags.FLAGS
flags.DEFINE_integer('process_pool_size', 4,
                     'Number of processes to use in the process pool')


# NOTE(termie): this is copied from twisted.internet.utils but since
#               they don't export it I've copied and modified
class UnexpectedErrorOutput(IOError):
    """
    Standard error data was received where it was not expected.  This is a
    subclass of L{IOError} to preserve backward compatibility with the previous
    error behavior of L{getProcessOutput}.

    @ivar processEnded: A L{Deferred} which will fire when the process which
        produced the data on stderr has ended (exited and all file descriptors
        closed).
    """
    def __init__(self, stdout=None, stderr=None):
        IOError.__init__(self, "got stdout: %r\nstderr: %r" % (stdout, stderr))


# NOTE(termie): this too
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
    def __init__(self, deferred, startedDeferred=None, error_ok=0,
                 input=None):
        # Twisted doesn't use new-style classes in most places :(
        _BackRelay.__init__(self, deferred, errortoo=error_ok)
        self.error_ok = error_ok
        self.input = input
        self.stderr = StringIO.StringIO()
        self.startedDeferred = startedDeferred

    def errReceivedIsBad(self, text):
        self.stderr.write(text)
        self.transport.loseConnection()

    def errReceivedIsGood(self, text):
        self.stderr.write(text)
    
    def connectionMade(self):
        if self.startedDeferred:
            self.startedDeferred.callback(self)
        if self.input:
            self.transport.write(self.input)
        self.transport.closeStdin()

    def processEnded(self, reason):
        if self.deferred is not None:
            stdout, stderr = self.s.getvalue(), self.stderr.getvalue()
            try:
                # NOTE(termie): current behavior means if error_ok is True
                #               we won't throw an error even if the process
                #               exited with a non-0 status, so you can't be
                #               okay with stderr output and not with bad exit
                #               codes.
                if not self.error_ok:
                    reason.trap(error.ProcessDone)
                self.deferred.callback((stdout, stderr))
            except:
                self.deferred.errback(UnexpectedErrorOutput(stdout, stderr))


def getProcessOutput(executable, args=None, env=None, path=None, reactor=None,
                     error_ok=0, input=None, startedDeferred=None):
    if reactor is None:
        from twisted.internet import reactor
    args = args and args or ()
    env = env and env and {}
    d = defer.Deferred()
    p = BackRelayWithInput(
            d, startedDeferred=startedDeferred, error_ok=error_ok, input=input)
    reactor.spawnProcess(p, executable, (executable,)+tuple(args), env, path)
    return d


class ProcessPool(object):
    """ A simple process pool implementation using Twisted's Process bits.

    This is pretty basic right now, but hopefully the API will be the correct
    one so that it can be optimized later.
    """
    def __init__(self, size=None):
        self.size = size and size or FLAGS.process_pool_size
        self._pool = defer.DeferredSemaphore(self.size)

    def simpleExecute(self, cmd, **kw):
        """ Weak emulation of the old utils.execute() function.
        
        This only exists as a way to quickly move old execute methods to
        this new style of code.

        NOTE(termie): This will break on args with spaces in them.
        """
        parsed = cmd.split(' ')
        executable, args = parsed[0], parsed[1:]
        return self.execute(executable, args, **kw)

    def execute(self, *args, **kw):
        d = self._pool.acquire()

        def _associateProcess(proto):
            d.process = proto.transport
            return proto.transport

        started = defer.Deferred()
        started.addCallback(_associateProcess)
        kw.setdefault('startedDeferred', started)

        d.process = None
        d.started = started
        
        d.addCallback(lambda _: getProcessOutput(*args, **kw))
        d.addBoth(self._release)
        return d

    def _release(self, rv=None):
        self._pool.release()
        return rv


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
