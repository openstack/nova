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

"""
Process pool, still buggy right now.
"""

import logging
import multiprocessing
import StringIO
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


# This is based on _BackRelay from twister.internal.utils, but modified to capture 
#  both stdout and stderr without odd stderr handling,  and also to handle stdin
class BackRelayWithInput(protocol.ProcessProtocol):
    """
    Trivial protocol for communicating with a process and turning its output
    into the result of a L{Deferred}.

    @ivar deferred: A L{Deferred} which will be called back with all of stdout
        and all of stderr as well (as a tuple).  C{terminate_on_stderr} is true
        and any bytes are received over stderr, this will fire with an
        L{_UnexpectedErrorOutput} instance and the attribute will be set to 
        C{None}.

    @ivar onProcessEnded: If C{terminate_on_stderr} is false and bytes are received over
        stderr, this attribute will refer to a L{Deferred} which will be called
        back when the process ends.  This C{Deferred} is also associated with
        the L{_UnexpectedErrorOutput} which C{deferred} fires with earlier in
        this case so that users can determine when the process has actually
        ended, in addition to knowing when bytes have been received via stderr.
    """

    def __init__(self, deferred, startedDeferred=None, terminate_on_stderr=False,
                    check_exit_code=True, input=None):
        self.deferred = deferred
        self.stdout = StringIO.StringIO()
        self.stderr = StringIO.StringIO()
        self.startedDeferred = startedDeferred
        self.terminate_on_stderr = terminate_on_stderr
        self.check_exit_code = check_exit_code
        self.input = input
    
    def errReceived(self, text):
        self.sterr.write(text)
        if self.terminate_on_stderr and (self.deferred is not None):
            self.onProcessEnded = defer.Deferred()
            self.deferred.errback(UnexpectedErrorOutput(stdout=self.stdout.getvalue(), stderr=self.stderr.getvalue()))
            self.deferred = None
            self.transport.loseConnection()

    def errReceived(self, text):
        self.stderr.write(text)

    def outReceived(self, text):
        self.stdout.write(text)

    def processEnded(self, reason):
        if self.deferred is not None:
            stdout, stderr = self.stdout.getvalue(), self.stderr.getvalue()
            try:
                if self.check_exit_code:
                    reason.trap(error.ProcessDone)
                self.deferred.callback((stdout, stderr))
            except:
                self.deferred.errback(UnexpectedErrorOutput(stdout, stderr))
        elif self.onProcessEnded is not None:
            self.onProcessEnded.errback(reason)


    def connectionMade(self):
        if self.startedDeferred:
            self.startedDeferred.callback(self)
        if self.input:
            self.transport.write(self.input)
        self.transport.closeStdin()

def getProcessOutput(executable, args=None, env=None, path=None, reactor=None,
                     check_exit_code=True, input=None, startedDeferred=None):
    if reactor is None:
        from twisted.internet import reactor
    args = args and args or ()
    env = env and env and {}
    d = defer.Deferred()
    p = BackRelayWithInput(
            d, startedDeferred=startedDeferred, check_exit_code=check_exit_code, input=input)
    # NOTE(vish): commands come in as unicode, but self.executes needs
    #             strings or process.spawn raises a deprecation warning
    executable = str(executable)
    if not args is None:
        args = [str(x) for x in args]
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

    def simple_execute(self, cmd, **kw):
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

class SharedPool(object):
    _instance = None
    def __init__(self):
        if SharedPool._instance is None:
            self.__class__._instance = ProcessPool()
    def __getattr__(self, key):
        return getattr(self._instance, key)

def simple_execute(cmd, **kwargs):
    return SharedPool().simple_execute(cmd, **kwargs)
