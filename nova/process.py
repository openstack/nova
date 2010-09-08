# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010 FathomDB Inc.
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

import StringIO

from twisted.internet import defer
from twisted.internet import error
from twisted.internet import protocol
from twisted.internet import reactor

from nova import flags
from nova.exception import ProcessExecutionError

FLAGS = flags.FLAGS
flags.DEFINE_integer('process_pool_size', 4,
                     'Number of processes to use in the process pool')

# This is based on _BackRelay from twister.internal.utils, but modified to
#  capture both stdout and stderr, without odd stderr handling, and also to
#  handle stdin
class BackRelayWithInput(protocol.ProcessProtocol):
    """
    Trivial protocol for communicating with a process and turning its output
    into the result of a L{Deferred}.

    @ivar deferred: A L{Deferred} which will be called back with all of stdout
        and all of stderr as well (as a tuple).  C{terminate_on_stderr} is true
        and any bytes are received over stderr, this will fire with an
        L{_ProcessExecutionError} instance and the attribute will be set to
        C{None}.

    @ivar onProcessEnded: If C{terminate_on_stderr} is false and bytes are
        received over stderr, this attribute will refer to a L{Deferred} which
        will be called back when the process ends.  This C{Deferred} is also
        associated with the L{_ProcessExecutionError} which C{deferred} fires
        with earlier in this case so that users can determine when the process
        has actually ended, in addition to knowing when bytes have been received
        via stderr.
    """

    def __init__(self, deferred, cmd, started_deferred=None,
                 terminate_on_stderr=False, check_exit_code=True,
                 process_input=None):
        self.deferred = deferred
        self.cmd = cmd
        self.stdout = StringIO.StringIO()
        self.stderr = StringIO.StringIO()
        self.started_deferred = started_deferred
        self.terminate_on_stderr = terminate_on_stderr
        self.check_exit_code = check_exit_code
        self.process_input = process_input
        self.on_process_ended = None

    def _build_execution_error(self, exit_code=None):
        return ProcessExecutionError(cmd=self.cmd,
                                     exit_code=exit_code,
                                     stdout=self.stdout.getvalue(),
                                     stderr=self.stderr.getvalue())

    def errReceived(self, text):
        self.stderr.write(text)
        if self.terminate_on_stderr and (self.deferred is not None):
            self.on_process_ended = defer.Deferred()
            self.deferred.errback(self._build_execution_error())
            self.deferred = None
            self.transport.loseConnection()

    def outReceived(self, text):
        self.stdout.write(text)

    def processEnded(self, reason):
        if self.deferred is not None:
            stdout, stderr = self.stdout.getvalue(), self.stderr.getvalue()
            exit_code = reason.value.exitCode
            if self.check_exit_code and exit_code <> 0:
                self.deferred.errback(self._build_execution_error(exit_code))
            else:
                try:
                    if self.check_exit_code:
                        reason.trap(error.ProcessDone)
                    self.deferred.callback((stdout, stderr))
                except:
                    # NOTE(justinsb): This logic is a little suspicious to me...
                    # If the callback throws an exception, then errback will be
                    # called also. However, this is what the unit tests test for...
                    self.deferred.errback(self._build_execution_error(exit_code))
        elif self.on_process_ended is not None:
            self.on_process_ended.errback(reason)


    def connectionMade(self):
        if self.started_deferred:
            self.started_deferred.callback(self)
        if self.process_input:
            self.transport.write(self.process_input)
        self.transport.closeStdin()

def get_process_output(executable, args=None, env=None, path=None,
                       process_reactor=None, check_exit_code=True,
                       process_input=None, started_deferred=None,
                       terminate_on_stderr=False):
    if process_reactor is None:
        process_reactor = reactor
    args = args and args or ()
    env = env and env and {}
    deferred = defer.Deferred()
    cmd = executable
    if args:
        cmd = " ".join([cmd] + args)
    process_handler = BackRelayWithInput(
            deferred,
            cmd,
            started_deferred=started_deferred,
            check_exit_code=check_exit_code,
            process_input=process_input,
            terminate_on_stderr=terminate_on_stderr)
    # NOTE(vish): commands come in as unicode, but self.executes needs
    #             strings or process.spawn raises a deprecation warning
    executable = str(executable)
    if not args is None:
        args = [str(x) for x in args]
    process_reactor.spawnProcess(process_handler, executable,
                                 (executable,)+tuple(args), env, path)
    return deferred


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
        deferred = self._pool.acquire()

        def _associate_process(proto):
            deferred.process = proto.transport
            return proto.transport

        started = defer.Deferred()
        started.addCallback(_associate_process)
        kw.setdefault('started_deferred', started)

        deferred.process = None
        deferred.started = started

        deferred.addCallback(lambda _: get_process_output(*args, **kw))
        deferred.addBoth(self._release)
        return deferred

    def _release(self, retval=None):
        self._pool.release()
        return retval


class SharedPool(object):
    _instance = None
    def __init__(self):
        if SharedPool._instance is None:
            self.__class__._instance = ProcessPool()
    def __getattr__(self, key):
        return getattr(self._instance, key)


def simple_execute(cmd, **kwargs):
    return SharedPool().simple_execute(cmd, **kwargs)
