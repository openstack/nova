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

"""
System-level utilities and helper functions.
"""

import base64
import datetime
import functools
import inspect
import json
import lockfile
import netaddr
import os
import random
import re
import socket
import string
import struct
import sys
import time
import types
from xml.sax import saxutils

from eventlet import event
from eventlet import greenthread
from eventlet import semaphore
from eventlet.green import subprocess
None
from nova import exception
from nova.exception import ProcessExecutionError
from nova import flags
from nova import log as logging


LOG = logging.getLogger("nova.utils")
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FLAGS = flags.FLAGS


def import_class(import_str):
    """Returns a class from a string including module and class"""
    mod_str, _sep, class_str = import_str.rpartition('.')
    try:
        __import__(mod_str)
        return getattr(sys.modules[mod_str], class_str)
    except (ImportError, ValueError, AttributeError), exc:
        LOG.debug(_('Inner Exception: %s'), exc)
        raise exception.NotFound(_('Class %s cannot be found') % class_str)


def import_object(import_str):
    """Returns an object including a module or module and class"""
    try:
        __import__(import_str)
        return sys.modules[import_str]
    except ImportError:
        cls = import_class(import_str)
        return cls()


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
    data = struct.pack("!BQxxxxxx", 0x38, session_id)
    sock.sendto(data, (address, port))
    sock.settimeout(timeout)
    try:
        received = sock.recv(2048)
    except socket.timeout:
        return False
    finally:
        sock.close()
    fmt = "!BQxxxxxQxxxx"
    if len(received) != struct.calcsize(fmt):
        print struct.calcsize(fmt)
        return False
    (identifier, server_sess, client_sess) = struct.unpack(fmt, received)
    if identifier == 0x40 and client_sess == session_id:
        return server_sess


def fetchfile(url, target):
    LOG.debug(_("Fetching %s") % url)
#    c = pycurl.Curl()
#    fp = open(target, "wb")
#    c.setopt(c.URL, url)
#    c.setopt(c.WRITEDATA, fp)
#    c.perform()
#    c.close()
#    fp.close()
    execute("curl", "--fail", url, "-o", target)


def execute(*cmd, **kwargs):
    process_input = kwargs.pop('process_input', None)
    addl_env = kwargs.pop('addl_env', None)
    check_exit_code = kwargs.pop('check_exit_code', 0)
    delay_on_retry = kwargs.pop('delay_on_retry', True)
    attempts = kwargs.pop('attempts', 1)
    if len(kwargs):
        raise exception.Error(_('Got unknown keyword args '
                                'to utils.execute: %r') % kwargs)
    cmd = map(str, cmd)

    while attempts > 0:
        attempts -= 1
        try:
            LOG.debug(_("Running cmd (subprocess): %s"), ' '.join(cmd))
            env = os.environ.copy()
            if addl_env:
                env.update(addl_env)
            obj = subprocess.Popen(cmd,
                                   stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   env=env)
            result = None
            if process_input is not None:
                result = obj.communicate(process_input)
            else:
                result = obj.communicate()
            obj.stdin.close()
            if obj.returncode:
                LOG.debug(_("Result was %s") % obj.returncode)
                if type(check_exit_code) == types.IntType \
                        and obj.returncode != check_exit_code:
                    (stdout, stderr) = result
                    raise ProcessExecutionError(exit_code=obj.returncode,
                                                stdout=stdout,
                                                stderr=stderr,
                                                cmd=' '.join(cmd))
            return result
        except ProcessExecutionError:
            if not attempts:
                raise
            else:
                LOG.debug(_("%r failed. Retrying."), cmd)
                if delay_on_retry:
                    greenthread.sleep(random.randint(20, 200) / 100.0)
        finally:
            # NOTE(termie): this appears to be necessary to let the subprocess
            #               call clean something up in between calls, without
            #               it two execute calls in a row hangs the second one
            greenthread.sleep(0)


def ssh_execute(ssh, cmd, process_input=None,
                addl_env=None, check_exit_code=True):
    LOG.debug(_("Running cmd (SSH): %s"), ' '.join(cmd))
    if addl_env:
        raise exception.Error("Environment not supported over SSH")

    if process_input:
        # This is (probably) fixable if we need it...
        raise exception.Error("process_input not supported over SSH")

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
        LOG.debug(_("Result was %s") % exit_status)
        if check_exit_code and exit_status != 0:
            raise exception.ProcessExecutionError(exit_code=exit_status,
                                                  stdout=stdout,
                                                  stderr=stderr,
                                                  cmd=' '.join(cmd))

    return (stdout, stderr)


def abspath(s):
    return os.path.join(os.path.dirname(__file__), s)


def novadir():
    import nova
    return os.path.abspath(nova.__file__).split('nova/__init__.pyc')[0]


def default_flagfile(filename='nova.conf'):
    for arg in sys.argv:
        if arg.find('flagfile') != -1:
            break
    else:
        if not os.path.isabs(filename):
            # turn relative filename into an absolute path
            script_dir = os.path.dirname(inspect.stack()[-1][1])
            filename = os.path.abspath(os.path.join(script_dir, filename))
        if os.path.exists(filename):
            flagfile = ['--flagfile=%s' % filename]
            sys.argv = sys.argv[:1] + flagfile + sys.argv[1:]


def debug(arg):
    LOG.debug(_('debug in callback: %s'), arg)
    return arg


def runthis(prompt, *cmd, **kwargs):
    LOG.debug(_("Running %s"), (" ".join(cmd)))
    rv, err = execute(*cmd, **kwargs)


def generate_uid(topic, size=8):
    characters = '01234567890abcdefghijklmnopqrstuvwxyz'
    choices = [random.choice(characters) for x in xrange(size)]
    return '%s-%s' % (topic, ''.join(choices))


def generate_mac():
    mac = [0x02, 0x16, 0x3e,
           random.randint(0x00, 0x7f),
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff)]
    return ':'.join(map(lambda x: "%02x" % x, mac))


# Default symbols to use for passwords. Avoids visually confusing characters.
# ~6 bits per symbol
DEFAULT_PASSWORD_SYMBOLS = ("23456789"  # Removed: 0,1
                            "ABCDEFGHJKLMNPQRSTUVWXYZ"  # Removed: I, O
                            "abcdefghijkmnopqrstuvwxyz")  # Removed: l


# ~5 bits per symbol
EASIER_PASSWORD_SYMBOLS = ("23456789"  # Removed: 0, 1
                           "ABCDEFGHJKLMNPQRSTUVWXYZ")  # Removed: I, O


def generate_password(length=20, symbols=DEFAULT_PASSWORD_SYMBOLS):
    """Generate a random password from the supplied symbols.

    Believed to be reasonably secure (with a reasonable password length!)
    """
    r = random.SystemRandom()
    return "".join([r.choice(symbols) for _i in xrange(length)])


def last_octet(address):
    return int(address.split(".")[-1])


def  get_my_linklocal(interface):
    try:
        if_str = execute("ip", "-f", "inet6", "-o", "addr", "show", interface)
        condition = "\s+inet6\s+([0-9a-f:]+)/\d+\s+scope\s+link"
        links = [re.search(condition, x) for x in if_str[0].split('\n')]
        address = [w.group(1) for w in links if w is not None]
        if address[0] is not None:
            return address[0]
        else:
            raise exception.Error(_("Link Local address is not found.:%s")
                                  % if_str)
    except Exception as ex:
        raise exception.Error(_("Couldn't get Link Local IP of %(interface)s"
                " :%(ex)s") % locals())


def to_global_ipv6(prefix, mac):
    try:
        mac64 = netaddr.EUI(mac).eui64().words
        int_addr = int(''.join(['%02x' % i for i in mac64]), 16)
        mac64_addr = netaddr.IPAddress(int_addr)
        maskIP = netaddr.IPNetwork(prefix).ip
        return (mac64_addr ^ netaddr.IPAddress('::0200:0:0:0') | maskIP).\
                                                                    format()
    except TypeError:
        raise TypeError(_("Bad mac for to_global_ipv6: %s") % mac)


def to_mac(ipv6_address):
    address = netaddr.IPAddress(ipv6_address)
    mask1 = netaddr.IPAddress("::ffff:ffff:ffff:ffff")
    mask2 = netaddr.IPAddress("::0200:0:0:0")
    mac64 = netaddr.EUI(int(address & mask1 ^ mask2)).words
    return ":".join(["%02x" % i for i in mac64[0:3] + mac64[5:8]])


def utcnow():
    """Overridable version of datetime.datetime.utcnow."""
    if utcnow.override_time:
        return utcnow.override_time
    return datetime.datetime.utcnow()


utcnow.override_time = None


def is_older_than(before, seconds):
    """Return True if before is older than seconds"""
    return utcnow() - before > datetime.timedelta(seconds=seconds)


def utcnow_ts():
    """Timestamp version of our utcnow function."""
    return time.mktime(utcnow().timetuple())


def set_time_override(override_time=datetime.datetime.utcnow()):
    """Override utils.utcnow to return a constant time."""
    utcnow.override_time = override_time


def advance_time_delta(timedelta):
    """Advance overriden time using a datetime.timedelta."""
    assert(not utcnow.override_time is None)
    utcnow.override_time += timedelta


def advance_time_seconds(seconds):
    """Advance overriden time by seconds."""
    advance_time_delta(datetime.timedelta(0, seconds))


def clear_time_override():
    """Remove the overridden time."""
    utcnow.override_time = None


def isotime(at=None):
    """Returns iso formatted utcnow."""
    if not at:
        at = utcnow()
    return at.strftime(TIME_FORMAT)


def parse_isotime(timestr):
    """Turn an iso formatted time back into a datetime"""
    return datetime.datetime.strptime(timestr, TIME_FORMAT)


def parse_mailmap(mailmap='.mailmap'):
    mapping = {}
    if os.path.exists(mailmap):
        fp = open(mailmap, 'r')
        for l in fp:
            l = l.strip()
            if not l.startswith('#') and ' ' in l:
                canonical_email, alias = l.split(' ')
                mapping[alias] = canonical_email
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
            backend_name = self.__pivot.value
            if backend_name not in self.__backends:
                raise exception.Error(_('Invalid backend: %s') % backend_name)

            backend = self.__backends[backend_name]
            if type(backend) == type(tuple()):
                name = backend[0]
                fromlist = backend[1]
            else:
                name = backend
                fromlist = backend

            self.__backend = __import__(name, None, None, fromlist)
            LOG.debug(_('backend %s'), self.__backend)
        return self.__backend

    def __getattr__(self, key):
        backend = self.__get_backend()
        return getattr(backend, key)


class LoopingCallDone(Exception):
    """The poll-function passed to LoopingCall can raise this exception to
    break out of the loop normally. This is somewhat analogous to
    StopIteration.

    An optional return-value can be included as the argument to the exception;
    this return-value will be returned by LoopingCall.wait()
    """

    def __init__(self, retvalue=True):
        """:param retvalue: Value that LoopingCall.wait() should return"""
        self.retvalue = retvalue


class LoopingCall(object):
    def __init__(self, f=None, *args, **kw):
        self.args = args
        self.kw = kw
        self.f = f
        self._running = False

    def start(self, interval, now=True):
        self._running = True
        done = event.Event()

        def _inner():
            if not now:
                greenthread.sleep(interval)
            try:
                while self._running:
                    self.f(*self.args, **self.kw)
                    greenthread.sleep(interval)
            except LoopingCallDone, e:
                self.stop()
                done.send(e.retvalue)
            except Exception:
                logging.exception('in looping call')
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


def xhtml_escape(value):
    """Escapes a string so it is valid within XML or XHTML.

    Code is directly from the utf8 function in
    http://github.com/facebook/tornado/blob/master/tornado/escape.py

    """
    return saxutils.escape(value, {'"': "&quot;"})


def utf8(value):
    """Try to turn a string into utf-8 if possible.

    Code is directly from the utf8 function in
    http://github.com/facebook/tornado/blob/master/tornado/escape.py

    """
    if isinstance(value, unicode):
        return value.encode("utf-8")
    assert isinstance(value, str)
    return value


def to_primitive(value):
    if type(value) is type([]) or type(value) is type((None,)):
        o = []
        for v in value:
            o.append(to_primitive(v))
        return o
    elif type(value) is type({}):
        o = {}
        for k, v in value.iteritems():
            o[k] = to_primitive(v)
        return o
    elif isinstance(value, datetime.datetime):
        return str(value)
    elif hasattr(value, 'iteritems'):
        return to_primitive(dict(value.iteritems()))
    elif hasattr(value, '__iter__'):
        return to_primitive(list(value))
    else:
        return value


def dumps(value):
    try:
        return json.dumps(value)
    except TypeError:
        pass
    return json.dumps(to_primitive(value))


def loads(s):
    return json.loads(s)


_semaphores = {}


class _NoopContextManager(object):
    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def synchronized(name, external=False):
    """Synchronization decorator

    Decorating a method like so:
    @synchronized('mylock')
    def foo(self, *args):
       ...

    ensures that only one thread will execute the bar method at a time.

    Different methods can share the same lock:
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
    """

    def wrap(f):
        @functools.wraps(f)
        def inner(*args, **kwargs):
            # NOTE(soren): If we ever go natively threaded, this will be racy.
            #              See http://stackoverflow.com/questions/5390569/dyn\
            #              amically-allocating-and-destroying-mutexes
            if name not in _semaphores:
                _semaphores[name] = semaphore.Semaphore()
            sem = _semaphores[name]
            LOG.debug(_('Attempting to grab semaphore "%(lock)s" for method '
                      '"%(method)s"...' % {"lock": name,
                                           "method": f.__name__}))
            with sem:
                if external:
                    LOG.debug(_('Attempting to grab file lock "%(lock)s" for '
                                'method "%(method)s"...' %
                                {"lock": name, "method": f.__name__}))
                    lock_file_path = os.path.join(FLAGS.lock_path,
                                                  'nova-%s.lock' % name)
                    lock = lockfile.FileLock(lock_file_path)
                else:
                    lock = _NoopContextManager()

                with lock:
                    retval = f(*args, **kwargs)

            # If no-one else is waiting for it, delete it.
            # See note about possible raciness above.
            if not sem.balance < 1:
                del _semaphores[name]

            return retval
        return inner
    return wrap


def get_from_path(items, path):
    """ Returns a list of items matching the specified path.  Takes an
    XPath-like expression e.g. prop1/prop2/prop3, and for each item in items,
    looks up items[prop1][prop2][prop3].  Like XPath, if any of the
    intermediate results are lists it will treat each list item individually.
    A 'None' in items or any child expressions will be ignored, this function
    will not throw because of None (anywhere) in items.  The returned list
    will contain no None values."""

    if path is None:
        raise exception.Error("Invalid mini_xpath")

    (first_token, sep, remainder) = path.partition("/")

    if first_token == "":
        raise exception.Error("Invalid mini_xpath")

    results = []

    if items is None:
        return results

    if not isinstance(items, types.ListType):
        # Wrap single objects in a list
        items = [items]

    for item in items:
        if item is None:
            continue
        get_method = getattr(item, "get", None)
        if get_method is None:
            continue
        child = get_method(first_token)
        if child is None:
            continue
        if isinstance(child, types.ListType):
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
    """Recursively flatten a nested dictionary"""
    flattened = flattened or {}
    for key, value in dict_.iteritems():
        if hasattr(value, 'iteritems'):
            flatten_dict(value, flattened)
        else:
            flattened[key] = value
    return flattened


def partition_dict(dict_, keys):
    """Return two dicts, one containing only `keys` the other containing
    everything but `keys`
    """
    intersection = {}
    difference = {}
    for key, value in dict_.iteritems():
        if key in keys:
            intersection[key] = value
        else:
            difference[key] = value
    return intersection, difference


def map_dict_keys(dict_, key_map):
    """Return a dictionary in which the dictionaries keys are mapped to
    new keys.
    """
    mapped = {}
    for key, value in dict_.iteritems():
        mapped_key = key_map[key] if key in key_map else key
        mapped[mapped_key] = value
    return mapped


def subset_dict(dict_, keys):
    """Return a dict that only contains a subset of keys"""
    subset = partition_dict(dict_, keys)[0]
    return subset


def check_isinstance(obj, cls):
    """Checks that obj is of type cls, and lets PyLint infer types"""
    if isinstance(obj, cls):
        return obj
    raise Exception(_("Expected object of type: %s") % (str(cls)))
    # TODO(justinsb): Can we make this better??
    return cls()  # Ugly PyLint hack
