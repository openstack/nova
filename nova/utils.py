# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

"""Utilities and helper functions."""

import contextlib
import datetime
import errno
import functools
import hashlib
import inspect
import os
import pyclbr
import random
import re
import shlex
import shutil
import signal
import socket
import struct
import sys
import tempfile
import time
import uuid
import weakref
from xml.dom import minidom
from xml.parsers import expat
from xml import sax
from xml.sax import expatreader
from xml.sax import saxutils

from eventlet import event
from eventlet.green import subprocess
from eventlet import greenthread
from eventlet import semaphore
import netaddr

from nova.common import deprecated
from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import excutils
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS

FLAGS.register_opt(
    cfg.BoolOpt('disable_process_locking', default=False,
                help='Whether to disable inter-process locks'))


def vpn_ping(address, port, timeout=0.05, session_id=None):
    """Sends a vpn negotiation packet and returns the server session.

    Returns False on a failure. Basic packet structure is below.

    Client packet (14 bytes)::

         0 1      8 9  13
        +-+--------+-----+
        |x| cli_id |?????|
        +-+--------+-----+
        x = packet identifier 0x38
        cli_id = 64 bit identifier
        ? = unknown, probably flags/padding

    Server packet (26 bytes)::

         0 1      8 9  13 14    21 2225
        +-+--------+-----+--------+----+
        |x| srv_id |?????| cli_id |????|
        +-+--------+-----+--------+----+
        x = packet identifier 0x40
        cli_id = 64 bit identifier
        ? = unknown, probably flags/padding
        bit 9 was 1 and the rest were 0 in testing

    """
    if session_id is None:
        session_id = random.randint(0, 0xffffffffffffffff)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = struct.pack('!BQxxxxx', 0x38, session_id)
    sock.sendto(data, (address, port))
    sock.settimeout(timeout)
    try:
        received = sock.recv(2048)
    except socket.timeout:
        return False
    finally:
        sock.close()
    fmt = '!BQxxxxxQxxxx'
    if len(received) != struct.calcsize(fmt):
        print struct.calcsize(fmt)
        return False
    (identifier, server_sess, client_sess) = struct.unpack(fmt, received)
    if identifier == 0x40 and client_sess == session_id:
        return server_sess


def _subprocess_setup():
    # Python installs a SIGPIPE handler by default. This is usually not what
    # non-Python subprocesses expect.
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def execute(*cmd, **kwargs):
    """Helper method to execute command with optional retry.

    If you add a run_as_root=True command, don't forget to add the
    corresponding filter to etc/nova/rootwrap.d !

    :param cmd:                Passed to subprocess.Popen.
    :param process_input:      Send to opened process.
    :param check_exit_code:    Single bool, int, or list of allowed exit
                               codes.  Defaults to [0].  Raise
                               exception.ProcessExecutionError unless
                               program exits with one of these code.
    :param delay_on_retry:     True | False. Defaults to True. If set to
                               True, wait a short amount of time
                               before retrying.
    :param attempts:           How many times to retry cmd.
    :param run_as_root:        True | False. Defaults to False. If set to True,
                               the command is prefixed by the command specified
                               in the root_helper FLAG.

    :raises exception.NovaException: on receiving unknown arguments
    :raises exception.ProcessExecutionError:

    :returns: a tuple, (stdout, stderr) from the spawned process, or None if
             the command fails.
    """
    process_input = kwargs.pop('process_input', None)
    check_exit_code = kwargs.pop('check_exit_code', [0])
    ignore_exit_code = False
    if isinstance(check_exit_code, bool):
        ignore_exit_code = not check_exit_code
        check_exit_code = [0]
    elif isinstance(check_exit_code, int):
        check_exit_code = [check_exit_code]
    delay_on_retry = kwargs.pop('delay_on_retry', True)
    attempts = kwargs.pop('attempts', 1)
    run_as_root = kwargs.pop('run_as_root', False)
    shell = kwargs.pop('shell', False)

    if len(kwargs):
        raise exception.NovaException(_('Got unknown keyword args '
                                        'to utils.execute: %r') % kwargs)

    if run_as_root:

        if FLAGS.rootwrap_config is None or FLAGS.root_helper != 'sudo':
            deprecated.warn(_('The root_helper option (which lets you specify '
                              'a root wrapper different from nova-rootwrap, '
                              'and defaults to using sudo) is now deprecated. '
                              'You should use the rootwrap_config option '
                              'instead.'))

        if (FLAGS.rootwrap_config is not None):
            cmd = ['sudo', 'nova-rootwrap', FLAGS.rootwrap_config] + list(cmd)
        else:
            cmd = shlex.split(FLAGS.root_helper) + list(cmd)
    cmd = map(str, cmd)

    while attempts > 0:
        attempts -= 1
        try:
            LOG.debug(_('Running cmd (subprocess): %s'), ' '.join(cmd))
            _PIPE = subprocess.PIPE  # pylint: disable=E1101
            obj = subprocess.Popen(cmd,
                                   stdin=_PIPE,
                                   stdout=_PIPE,
                                   stderr=_PIPE,
                                   close_fds=True,
                                   preexec_fn=_subprocess_setup,
                                   shell=shell)
            result = None
            if process_input is not None:
                result = obj.communicate(process_input)
            else:
                result = obj.communicate()
            obj.stdin.close()  # pylint: disable=E1101
            _returncode = obj.returncode  # pylint: disable=E1101
            LOG.debug(_('Result was %s') % _returncode)
            if not ignore_exit_code and _returncode not in check_exit_code:
                (stdout, stderr) = result
                raise exception.ProcessExecutionError(
                        exit_code=_returncode,
                        stdout=stdout,
                        stderr=stderr,
                        cmd=' '.join(cmd))
            return result
        except exception.ProcessExecutionError:
            if not attempts:
                raise
            else:
                LOG.debug(_('%r failed. Retrying.'), cmd)
                if delay_on_retry:
                    greenthread.sleep(random.randint(20, 200) / 100.0)
        finally:
            # NOTE(termie): this appears to be necessary to let the subprocess
            #               call clean something up in between calls, without
            #               it two execute calls in a row hangs the second one
            greenthread.sleep(0)


def trycmd(*args, **kwargs):
    """
    A wrapper around execute() to more easily handle warnings and errors.

    Returns an (out, err) tuple of strings containing the output of
    the command's stdout and stderr.  If 'err' is not empty then the
    command can be considered to have failed.

    :discard_warnings   True | False. Defaults to False. If set to True,
                        then for succeeding commands, stderr is cleared

    """
    discard_warnings = kwargs.pop('discard_warnings', False)

    try:
        out, err = execute(*args, **kwargs)
        failed = False
    except exception.ProcessExecutionError, exn:
        out, err = '', str(exn)
        failed = True

    if not failed and discard_warnings and err:
        # Handle commands that output to stderr but otherwise succeed
        err = ''

    return out, err


def ssh_execute(ssh, cmd, process_input=None,
                addl_env=None, check_exit_code=True):
    LOG.debug(_('Running cmd (SSH): %s'), ' '.join(cmd))
    if addl_env:
        raise exception.NovaException(_('Environment not supported over SSH'))

    if process_input:
        # This is (probably) fixable if we need it...
        msg = _('process_input not supported over SSH')
        raise exception.NovaException(msg)

    stdin_stream, stdout_stream, stderr_stream = ssh.exec_command(cmd)
    channel = stdout_stream.channel

    #stdin.write('process_input would go here')
    #stdin.flush()

    # NOTE(justinsb): This seems suspicious...
    # ...other SSH clients have buffering issues with this approach
    stdout = stdout_stream.read()
    stderr = stderr_stream.read()
    stdin_stream.close()

    exit_status = channel.recv_exit_status()

    # exit_status == -1 if no exit code was returned
    if exit_status != -1:
        LOG.debug(_('Result was %s') % exit_status)
        if check_exit_code and exit_status != 0:
            raise exception.ProcessExecutionError(exit_code=exit_status,
                                                  stdout=stdout,
                                                  stderr=stderr,
                                                  cmd=' '.join(cmd))

    return (stdout, stderr)


def novadir():
    import nova
    return os.path.abspath(nova.__file__).split('nova/__init__.py')[0]


def debug(arg):
    LOG.debug(_('debug in callback: %s'), arg)
    return arg


def generate_uid(topic, size=8):
    characters = '01234567890abcdefghijklmnopqrstuvwxyz'
    choices = [random.choice(characters) for _x in xrange(size)]
    return '%s-%s' % (topic, ''.join(choices))


# Default symbols to use for passwords. Avoids visually confusing characters.
# ~6 bits per symbol
DEFAULT_PASSWORD_SYMBOLS = ('23456789',  # Removed: 0,1
                            'ABCDEFGHJKLMNPQRSTUVWXYZ',   # Removed: I, O
                            'abcdefghijkmnopqrstuvwxyz')  # Removed: l


# ~5 bits per symbol
EASIER_PASSWORD_SYMBOLS = ('23456789',  # Removed: 0, 1
                           'ABCDEFGHJKLMNPQRSTUVWXYZ')  # Removed: I, O


def last_completed_audit_period(unit=None, before=None):
    """This method gives you the most recently *completed* audit period.

    arguments:
            units: string, one of 'hour', 'day', 'month', 'year'
                    Periods normally begin at the beginning (UTC) of the
                    period unit (So a 'day' period begins at midnight UTC,
                    a 'month' unit on the 1st, a 'year' on Jan, 1)
                    unit string may be appended with an optional offset
                    like so:  'day@18'  This will begin the period at 18:00
                    UTC.  'month@15' starts a monthly period on the 15th,
                    and year@3 begins a yearly one on March 1st.
            before: Give the audit period most recently completed before
                    <timestamp>. Defaults to now.


    returns:  2 tuple of datetimes (begin, end)
              The begin timestamp of this audit period is the same as the
              end of the previous."""
    if not unit:
        unit = FLAGS.instance_usage_audit_period

    offset = 0
    if '@' in unit:
        unit, offset = unit.split("@", 1)
        offset = int(offset)

    if before is not None:
        rightnow = before
    else:
        rightnow = timeutils.utcnow()
    if unit not in ('month', 'day', 'year', 'hour'):
        raise ValueError('Time period must be hour, day, month or year')
    if unit == 'month':
        if offset == 0:
            offset = 1
        end = datetime.datetime(day=offset,
                                month=rightnow.month,
                                year=rightnow.year)
        if end >= rightnow:
            year = rightnow.year
            if 1 >= rightnow.month:
                year -= 1
                month = 12 + (rightnow.month - 1)
            else:
                month = rightnow.month - 1
            end = datetime.datetime(day=offset,
                                    month=month,
                                    year=year)
        year = end.year
        if 1 >= end.month:
            year -= 1
            month = 12 + (end.month - 1)
        else:
            month = end.month - 1
        begin = datetime.datetime(day=offset, month=month, year=year)

    elif unit == 'year':
        if offset == 0:
            offset = 1
        end = datetime.datetime(day=1, month=offset, year=rightnow.year)
        if end >= rightnow:
            end = datetime.datetime(day=1,
                                    month=offset,
                                    year=rightnow.year - 1)
            begin = datetime.datetime(day=1,
                                      month=offset,
                                      year=rightnow.year - 2)
        else:
            begin = datetime.datetime(day=1,
                                      month=offset,
                                      year=rightnow.year - 1)

    elif unit == 'day':
        end = datetime.datetime(hour=offset,
                               day=rightnow.day,
                               month=rightnow.month,
                               year=rightnow.year)
        if end >= rightnow:
            end = end - datetime.timedelta(days=1)
        begin = end - datetime.timedelta(days=1)

    elif unit == 'hour':
        end = rightnow.replace(minute=offset, second=0, microsecond=0)
        if end >= rightnow:
            end = end - datetime.timedelta(hours=1)
        begin = end - datetime.timedelta(hours=1)

    return (begin, end)


def generate_password(length=20, symbolgroups=DEFAULT_PASSWORD_SYMBOLS):
    """Generate a random password from the supplied symbol groups.

    At least one symbol from each group will be included. Unpredictable
    results if length is less than the number of symbol groups.

    Believed to be reasonably secure (with a reasonable password length!)

    """
    r = random.SystemRandom()

    # NOTE(jerdfelt): Some password policies require at least one character
    # from each group of symbols, so start off with one random character
    # from each symbol group
    password = [r.choice(s) for s in symbolgroups]
    # If length < len(symbolgroups), the leading characters will only
    # be from the first length groups. Try our best to not be predictable
    # by shuffling and then truncating.
    r.shuffle(password)
    password = password[:length]
    length -= len(password)

    # then fill with random characters from all symbol groups
    symbols = ''.join(symbolgroups)
    password.extend([r.choice(symbols) for _i in xrange(length)])

    # finally shuffle to ensure first x characters aren't from a
    # predictable group
    r.shuffle(password)

    return ''.join(password)


def last_octet(address):
    return int(address.split('.')[-1])


def get_my_linklocal(interface):
    try:
        if_str = execute('ip', '-f', 'inet6', '-o', 'addr', 'show', interface)
        condition = '\s+inet6\s+([0-9a-f:]+)/\d+\s+scope\s+link'
        links = [re.search(condition, x) for x in if_str[0].split('\n')]
        address = [w.group(1) for w in links if w is not None]
        if address[0] is not None:
            return address[0]
        else:
            msg = _('Link Local address is not found.:%s') % if_str
            raise exception.NovaException(msg)
    except Exception as ex:
        msg = _("Couldn't get Link Local IP of %(interface)s"
                " :%(ex)s") % locals()
        raise exception.NovaException(msg)


def parse_mailmap(mailmap='.mailmap'):
    mapping = {}
    if os.path.exists(mailmap):
        fp = open(mailmap, 'r')
        for l in fp:
            l = l.strip()
            if not l.startswith('#') and ' ' in l:
                canonical_email, alias = l.split(' ')
                mapping[alias.lower()] = canonical_email.lower()
    return mapping


def str_dict_replace(s, mapping):
    for s1, s2 in mapping.iteritems():
        s = s.replace(s1, s2)
    return s


class LazyPluggable(object):
    """A pluggable backend loaded lazily based on some value."""

    def __init__(self, pivot, **backends):
        self.__backends = backends
        self.__pivot = pivot
        self.__backend = None

    def __get_backend(self):
        if not self.__backend:
            backend_name = FLAGS[self.__pivot]
            if backend_name not in self.__backends:
                msg = _('Invalid backend: %s') % backend_name
                raise exception.NovaException(msg)

            backend = self.__backends[backend_name]
            if isinstance(backend, tuple):
                name = backend[0]
                fromlist = backend[1]
            else:
                name = backend
                fromlist = backend

            self.__backend = __import__(name, None, None, fromlist)
        return self.__backend

    def __getattr__(self, key):
        backend = self.__get_backend()
        return getattr(backend, key)


class LoopingCallDone(Exception):
    """Exception to break out and stop a LoopingCall.

    The poll-function passed to LoopingCall can raise this exception to
    break out of the loop normally. This is somewhat analogous to
    StopIteration.

    An optional return-value can be included as the argument to the exception;
    this return-value will be returned by LoopingCall.wait()

    """

    def __init__(self, retvalue=True):
        """:param retvalue: Value that LoopingCall.wait() should return."""
        self.retvalue = retvalue


class LoopingCall(object):
    def __init__(self, f=None, *args, **kw):
        self.args = args
        self.kw = kw
        self.f = f
        self._running = False

    def start(self, interval, initial_delay=None):
        self._running = True
        done = event.Event()

        def _inner():
            if initial_delay:
                greenthread.sleep(initial_delay)

            try:
                while self._running:
                    self.f(*self.args, **self.kw)
                    if not self._running:
                        break
                    greenthread.sleep(interval)
            except LoopingCallDone, e:
                self.stop()
                done.send(e.retvalue)
            except Exception:
                LOG.exception(_('in looping call'))
                done.send_exception(*sys.exc_info())
                return
            else:
                done.send(True)

        self.done = done

        greenthread.spawn(_inner)
        return self.done

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()


class ProtectedExpatParser(expatreader.ExpatParser):
    """An expat parser which disables DTD's and entities by default."""

    def __init__(self, forbid_dtd=True, forbid_entities=True,
                 *args, **kwargs):
        # Python 2.x old style class
        expatreader.ExpatParser.__init__(self, *args, **kwargs)
        self.forbid_dtd = forbid_dtd
        self.forbid_entities = forbid_entities

    def start_doctype_decl(self, name, sysid, pubid, has_internal_subset):
        raise ValueError("Inline DTD forbidden")

    def entity_decl(self, entityName, is_parameter_entity, value, base,
                    systemId, publicId, notationName):
        raise ValueError("<!ENTITY> forbidden")

    def unparsed_entity_decl(self, name, base, sysid, pubid, notation_name):
        # expat 1.2
        raise ValueError("<!ENTITY> forbidden")

    def reset(self):
        expatreader.ExpatParser.reset(self)
        if self.forbid_dtd:
            self._parser.StartDoctypeDeclHandler = self.start_doctype_decl
        if self.forbid_entities:
            self._parser.EntityDeclHandler = self.entity_decl
            self._parser.UnparsedEntityDeclHandler = self.unparsed_entity_decl


def safe_minidom_parse_string(xml_string):
    """Parse an XML string using minidom safely.

    """
    try:
        return minidom.parseString(xml_string, parser=ProtectedExpatParser())
    except sax.SAXParseException as se:
        raise expat.ExpatError()


def xhtml_escape(value):
    """Escapes a string so it is valid within XML or XHTML.

    """
    return saxutils.escape(value, {'"': '&quot;', "'": '&apos;'})


def utf8(value):
    """Try to turn a string into utf-8 if possible.

    Code is directly from the utf8 function in
    http://github.com/facebook/tornado/blob/master/tornado/escape.py

    """
    if isinstance(value, unicode):
        return value.encode('utf-8')
    assert isinstance(value, str)
    return value


class _InterProcessLock(object):
    """Lock implementation which allows multiple locks, working around
    issues like bugs.debian.org/cgi-bin/bugreport.cgi?bug=632857 and does
    not require any cleanup. Since the lock is always held on a file
    descriptor rather than outside of the process, the lock gets dropped
    automatically if the process crashes, even if __exit__ is not executed.

    There are no guarantees regarding usage by multiple green threads in a
    single process here. This lock works only between processes. Exclusive
    access between local threads should be achieved using the semaphores
    in the @synchronized decorator.

    Note these locks are released when the descriptor is closed, so it's not
    safe to close the file descriptor while another green thread holds the
    lock. Just opening and closing the lock file can break synchronisation,
    so lock files must be accessed only using this abstraction.
    """

    def __init__(self, name):
        self.lockfile = None
        self.fname = name

    def __enter__(self):
        self.lockfile = open(self.fname, 'w')

        while True:
            try:
                # Using non-blocking locks since green threads are not
                # patched to deal with blocking locking calls.
                # Also upon reading the MSDN docs for locking(), it seems
                # to have a laughable 10 attempts "blocking" mechanism.
                self.trylock()
                return self
            except IOError, e:
                if e.errno in (errno.EACCES, errno.EAGAIN):
                    # external locks synchronise things like iptables
                    # updates - give it some time to prevent busy spinning
                    time.sleep(0.01)
                else:
                    raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.unlock()
            self.lockfile.close()
        except IOError:
            LOG.exception(_("Could not release the acquired lock `%s`")
                             % self.fname)

    def trylock(self):
        raise NotImplementedError()

    def unlock(self):
        raise NotImplementedError()


class _WindowsLock(_InterProcessLock):
    def trylock(self):
        msvcrt.locking(self.lockfile, msvcrt.LK_NBLCK, 1)

    def unlock(self):
        msvcrt.locking(self.lockfile, msvcrt.LK_UNLCK, 1)


class _PosixLock(_InterProcessLock):
    def trylock(self):
        fcntl.lockf(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock(self):
        fcntl.lockf(self.lockfile, fcntl.LOCK_UN)


if os.name == 'nt':
    import msvcrt
    InterProcessLock = _WindowsLock
else:
    import fcntl
    InterProcessLock = _PosixLock

_semaphores = weakref.WeakValueDictionary()


def synchronized(name, external=False, lock_path=None):
    """Synchronization decorator.

    Decorating a method like so::

        @synchronized('mylock')
        def foo(self, *args):
           ...

    ensures that only one thread will execute the bar method at a time.

    Different methods can share the same lock::

        @synchronized('mylock')
        def foo(self, *args):
           ...

        @synchronized('mylock')
        def bar(self, *args):
           ...

    This way only one of either foo or bar can be executing at a time.

    The external keyword argument denotes whether this lock should work across
    multiple processes. This means that if two different workers both run a
    a method decorated with @synchronized('mylock', external=True), only one
    of them will execute at a time.

    The lock_path keyword argument is used to specify a special location for
    external lock files to live. If nothing is set, then FLAGS.lock_path is
    used as a default.
    """

    def wrap(f):
        @functools.wraps(f)
        def inner(*args, **kwargs):
            # NOTE(soren): If we ever go natively threaded, this will be racy.
            #              See http://stackoverflow.com/questions/5390569/dyn
            #              amically-allocating-and-destroying-mutexes
            sem = _semaphores.get(name, semaphore.Semaphore())
            if name not in _semaphores:
                # this check is not racy - we're already holding ref locally
                # so GC won't remove the item and there was no IO switch
                # (only valid in greenthreads)
                _semaphores[name] = sem

            with sem:
                LOG.debug(_('Got semaphore "%(lock)s" for method '
                            '"%(method)s"...'), {'lock': name,
                                                 'method': f.__name__})
                if external and not FLAGS.disable_process_locking:
                    LOG.debug(_('Attempting to grab file lock "%(lock)s" for '
                                'method "%(method)s"...'),
                              {'lock': name, 'method': f.__name__})
                    cleanup_dir = False

                    # We need a copy of lock_path because it is non-local
                    local_lock_path = lock_path
                    if not local_lock_path:
                        local_lock_path = FLAGS.lock_path

                    if not local_lock_path:
                        cleanup_dir = True
                        local_lock_path = tempfile.mkdtemp()

                    if not os.path.exists(local_lock_path):
                        cleanup_dir = True
                        ensure_tree(local_lock_path)

                    # NOTE(mikal): the lock name cannot contain directory
                    # separators
                    safe_name = name.replace(os.sep, '_')
                    lock_file_path = os.path.join(local_lock_path,
                                                  'nova-%s' % safe_name)
                    try:
                        lock = InterProcessLock(lock_file_path)
                        with lock:
                            LOG.debug(_('Got file lock "%(lock)s" for '
                                        'method "%(method)s"...'),
                                      {'lock': name, 'method': f.__name__})
                            retval = f(*args, **kwargs)
                    finally:
                        # NOTE(vish): This removes the tempdir if we needed
                        #             to create one. This is used to cleanup
                        #             the locks left behind by unit tests.
                        if cleanup_dir:
                            shutil.rmtree(local_lock_path)
                else:
                    retval = f(*args, **kwargs)

            return retval
        return inner
    return wrap


def delete_if_exists(pathname):
    """delete a file, but ignore file not found error"""

    try:
        os.unlink(pathname)
    except OSError as e:
        if e.errno == errno.ENOENT:
            return
        else:
            raise


def get_from_path(items, path):
    """Returns a list of items matching the specified path.

    Takes an XPath-like expression e.g. prop1/prop2/prop3, and for each item
    in items, looks up items[prop1][prop2][prop3].  Like XPath, if any of the
    intermediate results are lists it will treat each list item individually.
    A 'None' in items or any child expressions will be ignored, this function
    will not throw because of None (anywhere) in items.  The returned list
    will contain no None values.

    """
    if path is None:
        raise exception.NovaException('Invalid mini_xpath')

    (first_token, sep, remainder) = path.partition('/')

    if first_token == '':
        raise exception.NovaException('Invalid mini_xpath')

    results = []

    if items is None:
        return results

    if not isinstance(items, list):
        # Wrap single objects in a list
        items = [items]

    for item in items:
        if item is None:
            continue
        get_method = getattr(item, 'get', None)
        if get_method is None:
            continue
        child = get_method(first_token)
        if child is None:
            continue
        if isinstance(child, list):
            # Flatten intermediate lists
            for x in child:
                results.append(x)
        else:
            results.append(child)

    if not sep:
        # No more tokens
        return results
    else:
        return get_from_path(results, remainder)


def flatten_dict(dict_, flattened=None):
    """Recursively flatten a nested dictionary."""
    flattened = flattened or {}
    for key, value in dict_.iteritems():
        if hasattr(value, 'iteritems'):
            flatten_dict(value, flattened)
        else:
            flattened[key] = value
    return flattened


def partition_dict(dict_, keys):
    """Return two dicts, one with `keys` the other with everything else."""
    intersection = {}
    difference = {}
    for key, value in dict_.iteritems():
        if key in keys:
            intersection[key] = value
        else:
            difference[key] = value
    return intersection, difference


def map_dict_keys(dict_, key_map):
    """Return a dict in which the dictionaries keys are mapped to new keys."""
    mapped = {}
    for key, value in dict_.iteritems():
        mapped_key = key_map[key] if key in key_map else key
        mapped[mapped_key] = value
    return mapped


def subset_dict(dict_, keys):
    """Return a dict that only contains a subset of keys."""
    subset = partition_dict(dict_, keys)[0]
    return subset


def diff_dict(orig, new):
    """
    Return a dict describing how to change orig to new.  The keys
    correspond to values that have changed; the value will be a list
    of one or two elements.  The first element of the list will be
    either '+' or '-', indicating whether the key was updated or
    deleted; if the key was updated, the list will contain a second
    element, giving the updated value.
    """
    # Figure out what keys went away
    result = dict((k, ['-']) for k in set(orig.keys()) - set(new.keys()))
    # Compute the updates
    for key, value in new.items():
        if key not in orig or value != orig[key]:
            result[key] = ['+', value]
    return result


def check_isinstance(obj, cls):
    """Checks that obj is of type cls, and lets PyLint infer types."""
    if isinstance(obj, cls):
        return obj
    raise Exception(_('Expected object of type: %s') % (str(cls)))


def parse_server_string(server_str):
    """
    Parses the given server_string and returns a list of host and port.
    If it's not a combination of host part and port, the port element
    is a null string. If the input is invalid expression, return a null
    list.
    """
    try:
        # First of all, exclude pure IPv6 address (w/o port).
        if netaddr.valid_ipv6(server_str):
            return (server_str, '')

        # Next, check if this is IPv6 address with a port number combination.
        if server_str.find("]:") != -1:
            (address, port) = server_str.replace('[', '', 1).split(']:')
            return (address, port)

        # Third, check if this is a combination of an address and a port
        if server_str.find(':') == -1:
            return (server_str, '')

        # This must be a combination of an address and a port
        (address, port) = server_str.split(':')
        return (address, port)

    except Exception:
        LOG.error(_('Invalid server_string: %s'), server_str)
        return ('', '')


def gen_uuid():
    return uuid.uuid4()


def is_uuid_like(val):
    """For our purposes, a UUID is a string in canonical form:

        aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa
    """
    try:
        uuid.UUID(val)
        return True
    except (TypeError, ValueError, AttributeError):
        return False


def bool_from_str(val):
    """Convert a string representation of a bool into a bool value"""

    if not val:
        return False
    try:
        return True if int(val) else False
    except ValueError:
        return val.lower() == 'true' or \
               val.lower() == 'yes' or \
               val.lower() == 'y'


def is_valid_boolstr(val):
    """Check if the provided string is a valid bool string or not. """
    val = str(val).lower()
    return val == 'true' or val == 'false' or \
           val == 'yes' or val == 'no' or \
           val == 'y' or val == 'n' or \
           val == '1' or val == '0'


def is_valid_ipv4(address):
    """valid the address strictly as per format xxx.xxx.xxx.xxx.
    where xxx is a value between 0 and 255.
    """
    parts = address.split(".")
    if len(parts) != 4:
        return False
    for item in parts:
        try:
            if not 0 <= int(item) <= 255:
                return False
        except ValueError:
            return False
    return True


def is_valid_cidr(address):
    """Check if the provided ipv4 or ipv6 address is a valid
    CIDR address or not"""
    try:
        # Validate the correct CIDR Address
        netaddr.IPNetwork(address)
    except netaddr.core.AddrFormatError:
        return False
    except UnboundLocalError:
        # NOTE(MotoKen): work around bug in netaddr 0.7.5 (see detail in
        # https://github.com/drkjam/netaddr/issues/2)
        return False

    # Prior validation partially verify /xx part
    # Verify it here
    ip_segment = address.split('/')

    if (len(ip_segment) <= 1 or
        ip_segment[1] == ''):
        return False

    return True


def monkey_patch():
    """  If the Flags.monkey_patch set as True,
    this function patches a decorator
    for all functions in specified modules.
    You can set decorators for each modules
    using FLAGS.monkey_patch_modules.
    The format is "Module path:Decorator function".
    Example: 'nova.api.ec2.cloud:nova.notifier.api.notify_decorator'

    Parameters of the decorator is as follows.
    (See nova.notifier.api.notify_decorator)

    name - name of the function
    function - object of the function
    """
    # If FLAGS.monkey_patch is not True, this function do nothing.
    if not FLAGS.monkey_patch:
        return
    # Get list of modules and decorators
    for module_and_decorator in FLAGS.monkey_patch_modules:
        module, decorator_name = module_and_decorator.split(':')
        # import decorator function
        decorator = importutils.import_class(decorator_name)
        __import__(module)
        # Retrieve module information using pyclbr
        module_data = pyclbr.readmodule_ex(module)
        for key in module_data.keys():
            # set the decorator for the class methods
            if isinstance(module_data[key], pyclbr.Class):
                clz = importutils.import_class("%s.%s" % (module, key))
                for method, func in inspect.getmembers(clz, inspect.ismethod):
                    setattr(clz, method,
                        decorator("%s.%s.%s" % (module, key, method), func))
            # set the decorator for the function
            if isinstance(module_data[key], pyclbr.Function):
                func = importutils.import_class("%s.%s" % (module, key))
                setattr(sys.modules[module], key,
                    decorator("%s.%s" % (module, key), func))


def convert_to_list_dict(lst, label):
    """Convert a value or list into a list of dicts"""
    if not lst:
        return None
    if not isinstance(lst, list):
        lst = [lst]
    return [{label: x} for x in lst]


def timefunc(func):
    """Decorator that logs how long a particular function took to execute"""
    @functools.wraps(func)
    def inner(*args, **kwargs):
        start_time = time.time()
        try:
            return func(*args, **kwargs)
        finally:
            total_time = time.time() - start_time
            LOG.debug(_("timefunc: '%(name)s' took %(total_time).2f secs") %
                      dict(name=func.__name__, total_time=total_time))
    return inner


def generate_glance_url():
    """Generate the URL to glance."""
    # TODO(jk0): This will eventually need to take SSL into consideration
    # when supported in glance.
    return "http://%s:%d" % (FLAGS.glance_host, FLAGS.glance_port)


def generate_image_url(image_ref):
    """Generate an image URL from an image_ref."""
    return "%s/images/%s" % (generate_glance_url(), image_ref)


@contextlib.contextmanager
def remove_path_on_error(path):
    """Protect code that wants to operate on PATH atomically.
    Any exception will cause PATH to be removed.
    """
    try:
        yield
    except Exception:
        with excutils.save_and_reraise_exception():
            delete_if_exists(path)


def make_dev_path(dev, partition=None, base='/dev'):
    """Return a path to a particular device.

    >>> make_dev_path('xvdc')
    /dev/xvdc

    >>> make_dev_path('xvdc', 1)
    /dev/xvdc1
    """
    path = os.path.join(base, dev)
    if partition:
        path += str(partition)
    return path


def total_seconds(td):
    """Local total_seconds implementation for compatibility with python 2.6"""
    if hasattr(td, 'total_seconds'):
        return td.total_seconds()
    else:
        return ((td.days * 86400 + td.seconds) * 10 ** 6 +
                td.microseconds) / 10.0 ** 6


def sanitize_hostname(hostname):
    """Return a hostname which conforms to RFC-952 and RFC-1123 specs."""
    if isinstance(hostname, unicode):
        hostname = hostname.encode('latin-1', 'ignore')

    hostname = re.sub('[ _]', '-', hostname)
    hostname = re.sub('[^\w.-]+', '', hostname)
    hostname = hostname.lower()
    hostname = hostname.strip('.-')

    return hostname


def read_cached_file(filename, cache_info, reload_func=None):
    """Read from a file if it has been modified.

    :param cache_info: dictionary to hold opaque cache.
    :param reload_func: optional function to be called with data when
                        file is reloaded due to a modification.

    :returns: data from file

    """
    mtime = os.path.getmtime(filename)
    if not cache_info or mtime != cache_info.get('mtime'):
        LOG.debug(_("Reloading cached file %s") % filename)
        with open(filename) as fap:
            cache_info['data'] = fap.read()
        cache_info['mtime'] = mtime
        if reload_func:
            reload_func(cache_info['data'])
    return cache_info['data']


def file_open(*args, **kwargs):
    """Open file

    see built-in file() documentation for more details

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return file(*args, **kwargs)


def hash_file(file_like_object):
    """Generate a hash for the contents of a file."""
    checksum = hashlib.sha1()
    for chunk in iter(lambda: file_like_object.read(32768), b''):
        checksum.update(chunk)
    return checksum.hexdigest()


@contextlib.contextmanager
def temporary_mutation(obj, **kwargs):
    """Temporarily set the attr on a particular object to a given value then
    revert when finished.

    One use of this is to temporarily set the read_deleted flag on a context
    object:

        with temporary_mutation(context, read_deleted="yes"):
            do_something_that_needed_deleted_objects()
    """
    NOT_PRESENT = object()

    old_values = {}
    for attr, new_value in kwargs.items():
        old_values[attr] = getattr(obj, attr, NOT_PRESENT)
        setattr(obj, attr, new_value)

    try:
        yield
    finally:
        for attr, old_value in old_values.items():
            if old_value is NOT_PRESENT:
                del obj[attr]
            else:
                setattr(obj, attr, old_value)


def service_is_up(service):
    """Check whether a service is up based on last heartbeat."""
    last_heartbeat = service['updated_at'] or service['created_at']
    # Timestamps in DB are UTC.
    elapsed = total_seconds(timeutils.utcnow() - last_heartbeat)
    return abs(elapsed) <= FLAGS.service_down_time


def generate_mac_address():
    """Generate an Ethernet MAC address."""
    # NOTE(vish): We would prefer to use 0xfe here to ensure that linux
    #             bridge mac addresses don't change, but it appears to
    #             conflict with libvirt, so we use the next highest octet
    #             that has the unicast and locally administered bits set
    #             properly: 0xfa.
    #             Discussion: https://bugs.launchpad.net/nova/+bug/921838
    mac = [0xfa, 0x16, 0x3e,
           random.randint(0x00, 0x7f),
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff)]
    return ':'.join(map(lambda x: "%02x" % x, mac))


def read_file_as_root(file_path):
    """Secure helper to read file as root."""
    try:
        out, _err = execute('cat', file_path, run_as_root=True)
        return out
    except exception.ProcessExecutionError:
        raise exception.FileNotFound(file_path=file_path)


@contextlib.contextmanager
def temporary_chown(path, owner_uid=None):
    """Temporarily chown a path.

    :params owner_uid: UID of temporary owner (defaults to current user)
    """
    if owner_uid is None:
        owner_uid = os.getuid()

    orig_uid = os.stat(path).st_uid

    if orig_uid != owner_uid:
        execute('chown', owner_uid, path, run_as_root=True)
    try:
        yield
    finally:
        if orig_uid != owner_uid:
            execute('chown', orig_uid, path, run_as_root=True)


@contextlib.contextmanager
def tempdir(**kwargs):
    tmpdir = tempfile.mkdtemp(**kwargs)
    try:
        yield tmpdir
    finally:
        try:
            shutil.rmtree(tmpdir)
        except OSError, e:
            LOG.error(_('Could not remove tmpdir: %s'), str(e))


def strcmp_const_time(s1, s2):
    """Constant-time string comparison.

    :params s1: the first string
    :params s2: the second string

    :return: True if the strings are equal.

    This function takes two strings and compares them.  It is intended to be
    used when doing a comparison for authentication purposes to help guard
    against timing attacks.
    """
    if len(s1) != len(s2):
        return False
    result = 0
    for (a, b) in zip(s1, s2):
        result |= ord(a) ^ ord(b)
    return result == 0


def walk_class_hierarchy(clazz, encountered=None):
    """Walk class hierarchy, yielding most derived classes first"""
    if not encountered:
        encountered = []
    for subclass in clazz.__subclasses__():
        if subclass not in encountered:
            encountered.append(subclass)
            # drill down to leaves first
            for subsubclass in walk_class_hierarchy(subclass, encountered):
                yield subsubclass
            yield subclass


class UndoManager(object):
    """Provides a mechanism to facilitate rolling back a series of actions
    when an exception is raised.
    """
    def __init__(self):
        self.undo_stack = []

    def undo_with(self, undo_func):
        self.undo_stack.append(undo_func)

    def _rollback(self):
        for undo_func in reversed(self.undo_stack):
            undo_func()

    def rollback_and_reraise(self, msg=None, **kwargs):
        """Rollback a series of actions then re-raise the exception.

        .. note:: (sirp) This should only be called within an
                  exception handler.
        """
        with excutils.save_and_reraise_exception():
            if msg:
                LOG.exception(msg, **kwargs)

            self._rollback()


def ensure_tree(path):
    """Create a directory (and any ancestor directories required)

    :param path: Directory to create
    """
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            if not os.path.isdir(path):
                raise
        else:
            raise


def last_bytes(file_like_object, num):
    """Return num bytes from the end of the file, and remaining byte count.

    :param file_like_object: The file to read
    :param num: The number of bytes to return

    :returns (data, remaining)
    """

    try:
        file_like_object.seek(-num, os.SEEK_END)
    except IOError, e:
        if e.errno == 22:
            file_like_object.seek(0, os.SEEK_SET)
        else:
            raise

    remaining = file_like_object.tell()
    return (file_like_object.read(), remaining)
