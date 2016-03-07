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
import copy
import datetime
import errno
import functools
import hashlib
import inspect
import logging as std_logging
import os
import pyclbr
import random
import re
import shutil
import socket
import struct
import sys
import tempfile
import time
from xml.sax import saxutils

import eventlet
import netaddr
from oslo_concurrency import lockutils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_context import context as common_context
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
import six
from six.moves import range

from nova import exception
from nova.i18n import _, _LE, _LI, _LW
import nova.network
from nova import safe_utils

notify_decorator = 'nova.notifications.notify_decorator'

monkey_patch_opts = [
    cfg.BoolOpt('monkey_patch',
                default=False,
                help='Whether to apply monkey patching'),
    cfg.ListOpt('monkey_patch_modules',
                default=[
                  'nova.compute.api:%s' % (notify_decorator)
                  ],
                help='List of modules/decorators to monkey patch'),
]
utils_opts = [
    cfg.IntOpt('password_length',
               default=12,
               help='Length of generated instance admin passwords'),
    cfg.StrOpt('instance_usage_audit_period',
               default='month',
               help='Time period to generate instance usages for.  '
                    'Time period must be hour, day, month or year'),
    cfg.BoolOpt('use_rootwrap_daemon', default=False,
                help="Start and use a daemon that can run the commands that "
                     "need to be run with root privileges. This option is "
                     "usually enabled on nodes that run nova compute "
                     "processes"),
    cfg.StrOpt('rootwrap_config',
               default="/etc/nova/rootwrap.conf",
               help='Path to the rootwrap configuration file to use for '
                    'running commands as root'),
    cfg.StrOpt('tempdir',
               help='Explicitly specify the temporary working directory'),
]

workarounds_opts = [
    cfg.BoolOpt('disable_rootwrap',
                default=False,
                help='This option allows a fallback to sudo for performance '
                     'reasons. For example see '
                     'https://bugs.launchpad.net/nova/+bug/1415106'),
    cfg.BoolOpt('disable_libvirt_livesnapshot',
                default=True,
                help='When using libvirt 1.2.2 live snapshots fail '
                     'intermittently under load.  This config option provides '
                     'a mechanism to enable live snapshot while this is '
                     'resolved.  See '
                     'https://bugs.launchpad.net/nova/+bug/1334398'),
    cfg.BoolOpt('destroy_after_evacuate',
                default=True,
                deprecated_for_removal=True,
                help='DEPRECATED: Whether to destroy '
                     'instances on startup when we suspect '
                     'they have previously been evacuated. This can result in '
                      'data loss if undesired. See '
                      'https://launchpad.net/bugs/1419785'),
    cfg.BoolOpt('handle_virt_lifecycle_events',
                default=True,
                help="Whether or not to handle events raised from the compute "
                     "driver's 'emit_event' method. These are lifecycle "
                     "events raised from compute drivers that implement the "
                     "method. An example of a lifecycle event is an instance "
                     "starting or stopping. If the instance is going through "
                     "task state changes due to an API operation, like "
                     "resize, the events are ignored. However, this is an "
                     "advanced feature which allows the hypervisor to signal "
                     "to the compute service that an unexpected state change "
                     "has occurred in an instance and the instance can be "
                     "shutdown automatically - which can inherently race in "
                     "reboot operations or when the compute service or host "
                     "is rebooted, either planned or due to an unexpected "
                     "outage. Care should be taken when using this and "
                     "sync_power_state_interval is negative since then if any "
                     "instances are out of sync between the hypervisor and "
                     "the Nova database they will have to be synchronized "
                     "manually. See https://bugs.launchpad.net/bugs/1444630"),
    ]
""" The workarounds_opts group is for very specific reasons.

If you're:

 - Working around an issue in a system tool (e.g. libvirt or qemu) where the
   fix is in flight/discussed in that community.
 - The tool can be/is fixed in some distributions and rather than patch the
   code those distributions can trivially set a config option to get the
   "correct" behavior.

Then this is a good place for your workaround.

.. warning::

  Please use with care! Document the BugID that your workaround is paired with.
"""

CONF = cfg.CONF
CONF.register_opts(monkey_patch_opts)
CONF.register_opts(utils_opts)
CONF.register_opts(workarounds_opts, group='workarounds')

LOG = logging.getLogger(__name__)

# used in limits
TIME_UNITS = {
    'SECOND': 1,
    'MINUTE': 60,
    'HOUR': 3600,
    'DAY': 86400
}


_IS_NEUTRON = None

synchronized = lockutils.synchronized_with_prefix('nova-')

SM_IMAGE_PROP_PREFIX = "image_"
SM_INHERITABLE_KEYS = (
    'min_ram', 'min_disk', 'disk_format', 'container_format',
)
# Keys which hold large structured data that won't fit in the
# size constraints of the system_metadata table, so we avoid
# storing and/or loading them.
SM_SKIP_KEYS = (
    # Legacy names
    'mappings', 'block_device_mapping',
    # Modern names
    'img_mappings', 'img_block_device_mapping',
)
# Image attributes which Cinder stores in volume image metadata
# as regular properties
VIM_IMAGE_ATTRIBUTES = (
    'image_id', 'image_name', 'size', 'checksum',
    'container_format', 'disk_format', 'min_ram', 'min_disk',
)

_FILE_CACHE = {}


def vpn_ping(address, port, timeout=0.05, session_id=None):
    """Sends a vpn negotiation packet and returns the server session.

    Returns Boolean indicating whether the vpn_server is listening.
    Basic packet structure is below.

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
    # NOTE(tonyb) session_id isn't used for a real VPN connection so using a
    #             cryptographically weak value is fine.
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
        LOG.warning(_LW('Expected to receive %(exp)s bytes, '
                        'but actually %(act)s'),
                    dict(exp=struct.calcsize(fmt), act=len(received)))
        return False
    (identifier, server_sess, client_sess) = struct.unpack(fmt, received)
    return (identifier == 0x40 and client_sess == session_id)


def get_root_helper():
    if CONF.workarounds.disable_rootwrap:
        cmd = 'sudo'
    else:
        cmd = 'sudo nova-rootwrap %s' % CONF.rootwrap_config
    return cmd


def _get_rootwrap_helper():
    if CONF.use_rootwrap_daemon:
        return RootwrapDaemonHelper(CONF.rootwrap_config)
    else:
        return RootwrapProcessHelper()


class RootwrapProcessHelper(object):
    def trycmd(self, *cmd, **kwargs):
        kwargs['root_helper'] = get_root_helper()
        return processutils.trycmd(*cmd, **kwargs)

    def execute(self, *cmd, **kwargs):
        kwargs['root_helper'] = get_root_helper()
        return processutils.execute(*cmd, **kwargs)


class RootwrapDaemonHelper(RootwrapProcessHelper):
    _clients = {}

    @synchronized('daemon-client-lock')
    def _get_client(cls, rootwrap_config):
        try:
            return cls._clients[rootwrap_config]
        except KeyError:
            from oslo_rootwrap import client
            new_client = client.Client([
                "sudo", "nova-rootwrap-daemon", rootwrap_config])
            cls._clients[rootwrap_config] = new_client
            return new_client

    def __init__(self, rootwrap_config):
        self.client = self._get_client(rootwrap_config)

    def trycmd(self, *args, **kwargs):
        discard_warnings = kwargs.pop('discard_warnings', False)
        try:
            out, err = self.execute(*args, **kwargs)
            failed = False
        except processutils.ProcessExecutionError as exn:
            out, err = '', six.text_type(exn)
            failed = True
        if not failed and discard_warnings and err:
            # Handle commands that output to stderr but otherwise succeed
            err = ''
        return out, err

    def execute(self, *cmd, **kwargs):
        # NOTE(dims): This method is to provide compatibility with the
        # processutils.execute interface. So that calling daemon or direct
        # rootwrap to honor the same set of flags in kwargs and to ensure
        # that we don't regress any current behavior.
        cmd = [str(c) for c in cmd]
        loglevel = kwargs.pop('loglevel', std_logging.DEBUG)
        log_errors = kwargs.pop('log_errors', None)
        process_input = kwargs.pop('process_input', None)
        delay_on_retry = kwargs.pop('delay_on_retry', True)
        attempts = kwargs.pop('attempts', 1)
        check_exit_code = kwargs.pop('check_exit_code', [0])
        ignore_exit_code = False
        if isinstance(check_exit_code, bool):
            ignore_exit_code = not check_exit_code
            check_exit_code = [0]
        elif isinstance(check_exit_code, int):
            check_exit_code = [check_exit_code]

        sanitized_cmd = strutils.mask_password(' '.join(cmd))
        LOG.info(_LI('Executing RootwrapDaemonHelper.execute '
                     'cmd=[%(cmd)r] kwargs=[%(kwargs)r]'),
                 {'cmd': sanitized_cmd, 'kwargs': kwargs})

        while attempts > 0:
            attempts -= 1
            try:
                start_time = time.time()
                LOG.log(loglevel, _('Running cmd (subprocess): %s'),
                        sanitized_cmd)

                (returncode, out, err) = self.client.execute(
                    cmd, process_input)

                end_time = time.time() - start_time
                LOG.log(loglevel,
                        'CMD "%(sanitized_cmd)s" returned: %(return_code)s '
                        'in %(end_time)0.3fs',
                        {'sanitized_cmd': sanitized_cmd,
                         'return_code': returncode,
                         'end_time': end_time})

                if not ignore_exit_code and returncode not in check_exit_code:
                    out = strutils.mask_password(out)
                    err = strutils.mask_password(err)
                    raise processutils.ProcessExecutionError(
                        exit_code=returncode,
                        stdout=out,
                        stderr=err,
                        cmd=sanitized_cmd)
                return (out, err)

            except processutils.ProcessExecutionError as err:
                # if we want to always log the errors or if this is
                # the final attempt that failed and we want to log that.
                if log_errors == processutils.LOG_ALL_ERRORS or (
                                log_errors == processutils.LOG_FINAL_ERROR and
                            not attempts):
                    format = _('%(desc)r\ncommand: %(cmd)r\n'
                               'exit code: %(code)r\nstdout: %(stdout)r\n'
                               'stderr: %(stderr)r')
                    LOG.log(loglevel, format, {"desc": err.description,
                                               "cmd": err.cmd,
                                               "code": err.exit_code,
                                               "stdout": err.stdout,
                                               "stderr": err.stderr})
                if not attempts:
                    LOG.log(loglevel, _('%r failed. Not Retrying.'),
                            sanitized_cmd)
                    raise
                else:
                    LOG.log(loglevel, _('%r failed. Retrying.'),
                            sanitized_cmd)
                    if delay_on_retry:
                        time.sleep(random.randint(20, 200) / 100.0)


def execute(*cmd, **kwargs):
    """Convenience wrapper around oslo's execute() method."""
    if 'run_as_root' in kwargs and kwargs.get('run_as_root'):
        if CONF.use_rootwrap_daemon:
            return RootwrapDaemonHelper(CONF.rootwrap_config).execute(
                *cmd, **kwargs)
        else:
            return RootwrapProcessHelper().execute(*cmd, **kwargs)
    return processutils.execute(*cmd, **kwargs)


def ssh_execute(dest, *cmd, **kwargs):
    """Convenience wrapper to execute ssh command."""
    ssh_cmd = ['ssh', '-o', 'BatchMode=yes']
    ssh_cmd.append(dest)
    ssh_cmd.extend(cmd)
    return execute(*ssh_cmd, **kwargs)


def trycmd(*args, **kwargs):
    """Convenience wrapper around oslo's trycmd() method."""
    if kwargs.get('run_as_root', False):
        if CONF.use_rootwrap_daemon:
            return RootwrapDaemonHelper(CONF.rootwrap_config).trycmd(
                *args, **kwargs)
        else:
            return RootwrapProcessHelper().trycmd(*args, **kwargs)
    return processutils.trycmd(*args, **kwargs)


def generate_uid(topic, size=8):
    characters = '01234567890abcdefghijklmnopqrstuvwxyz'
    choices = [random.choice(characters) for _x in range(size)]
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
              end of the previous.
    """
    if not unit:
        unit = CONF.instance_usage_audit_period

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


def generate_password(length=None, symbolgroups=DEFAULT_PASSWORD_SYMBOLS):
    """Generate a random password from the supplied symbol groups.

    At least one symbol from each group will be included. Unpredictable
    results if length is less than the number of symbol groups.

    Believed to be reasonably secure (with a reasonable password length!)

    """
    if length is None:
        length = CONF.password_length

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
    password.extend([r.choice(symbols) for _i in range(length)])

    # finally shuffle to ensure first x characters aren't from a
    # predictable group
    r.shuffle(password)

    return ''.join(password)


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
                " :%(ex)s") % {'interface': interface, 'ex': ex}
        raise exception.NovaException(msg)


def xhtml_escape(value):
    """Escapes a string so it is valid within XML or XHTML.

    """
    return saxutils.escape(value, {'"': '&quot;', "'": '&apos;'})


def utf8(value):
    """Try to turn a string into utf-8 if possible.

    The original code was copied from the utf8 function in
    http://github.com/facebook/tornado/blob/master/tornado/escape.py

    """
    if value is None or isinstance(value, six.binary_type):
        return value

    if not isinstance(value, six.text_type):
        value = six.text_type(value)

    return value.encode('utf-8')


def check_isinstance(obj, cls):
    """Checks that obj is of type cls, and lets PyLint infer types."""
    if isinstance(obj, cls):
        return obj
    raise Exception(_('Expected object of type: %s') % (str(cls)))


def parse_server_string(server_str):
    """Parses the given server_string and returns a tuple of host and port.
    If it's not a combination of host part and port, the port element
    is an empty string. If the input is invalid expression, return a tuple of
    two empty strings.
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

    except (ValueError, netaddr.AddrFormatError):
        LOG.error(_LE('Invalid server_string: %s'), server_str)
        return ('', '')


def is_valid_ipv6_cidr(address):
    try:
        netaddr.IPNetwork(address, version=6).cidr
        return True
    except (TypeError, netaddr.AddrFormatError):
        return False


def get_shortened_ipv6(address):
    addr = netaddr.IPAddress(address, version=6)
    return str(addr.ipv6())


def get_shortened_ipv6_cidr(address):
    net = netaddr.IPNetwork(address, version=6)
    return str(net.cidr)


def is_valid_cidr(address):
    """Check if address is valid

    The provided address can be a IPv6 or a IPv4
    CIDR address.
    """
    try:
        # Validate the correct CIDR Address
        netaddr.IPNetwork(address)
    except netaddr.AddrFormatError:
        return False

    # Prior validation partially verify /xx part
    # Verify it here
    ip_segment = address.split('/')

    if (len(ip_segment) <= 1 or
            ip_segment[1] == ''):
        return False

    return True


def get_ip_version(network):
    """Returns the IP version of a network (IPv4 or IPv6).

    Raises AddrFormatError if invalid network.
    """
    if netaddr.IPNetwork(network).version == 6:
        return "IPv6"
    elif netaddr.IPNetwork(network).version == 4:
        return "IPv4"


def safe_ip_format(ip):
    """Transform ip string to "safe" format.

    Will return ipv4 addresses unchanged, but will nest ipv6 addresses
    inside square brackets.
    """
    try:
        if netaddr.IPAddress(ip).version == 6:
            return '[%s]' % ip
    except (TypeError, netaddr.AddrFormatError):  # hostname
        pass
    # it's IPv4 or hostname
    return ip


def monkey_patch():
    """If the CONF.monkey_patch set as True,
    this function patches a decorator
    for all functions in specified modules.
    You can set decorators for each modules
    using CONF.monkey_patch_modules.
    The format is "Module path:Decorator function".
    Example:
    'nova.api.ec2.cloud:nova.notifications.notify_decorator'

    Parameters of the decorator is as follows.
    (See nova.notifications.notify_decorator)

    name - name of the function
    function - object of the function
    """
    # If CONF.monkey_patch is not True, this function do nothing.
    if not CONF.monkey_patch:
        return
    if six.PY2:
        is_method = inspect.ismethod
    else:
        def is_method(obj):
            # Unbound methods became regular functions on Python 3
            return inspect.ismethod(obj) or inspect.isfunction(obj)
    # Get list of modules and decorators
    for module_and_decorator in CONF.monkey_patch_modules:
        module, decorator_name = module_and_decorator.split(':')
        # import decorator function
        decorator = importutils.import_class(decorator_name)
        __import__(module)
        # Retrieve module information using pyclbr
        module_data = pyclbr.readmodule_ex(module)
        for key, value in module_data.items():
            # set the decorator for the class methods
            if isinstance(value, pyclbr.Class):
                clz = importutils.import_class("%s.%s" % (module, key))
                for method, func in inspect.getmembers(clz, is_method):
                    setattr(clz, method,
                        decorator("%s.%s.%s" % (module, key, method), func))
            # set the decorator for the function
            if isinstance(value, pyclbr.Function):
                func = importutils.import_class("%s.%s" % (module, key))
                setattr(sys.modules[module], key,
                    decorator("%s.%s" % (module, key), func))


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


def sanitize_hostname(hostname, default_name=None):
    """Return a hostname which conforms to RFC-952 and RFC-1123 specs except
       the length of hostname.

       Window, Linux, and Dnsmasq has different limitation:

       Windows: 255 (net_bios limits to 15, but window will truncate it)
       Linux: 64
       Dnsmasq: 63

       Due to nova-network will leverage dnsmasq to set hostname, so we chose
       63.

       """

    def truncate_hostname(name):
        if len(name) > 63:
            LOG.warning(_LW("Hostname %(hostname)s is longer than 63, "
                            "truncate it to %(truncated_name)s"),
                            {'hostname': name, 'truncated_name': name[:63]})
        return name[:63]

    if isinstance(hostname, six.text_type):
        # Remove characters outside the Unicode range U+0000-U+00FF
        hostname = hostname.encode('latin-1', 'ignore')
        if six.PY3:
            hostname = hostname.decode('latin-1')

    hostname = truncate_hostname(hostname)
    hostname = re.sub('[ _]', '-', hostname)
    hostname = re.sub('[^\w.-]+', '', hostname)
    hostname = hostname.lower()
    hostname = hostname.strip('.-')
    # NOTE(eliqiao): set hostname to default_display_name to avoid
    # empty hostname
    if hostname == "" and default_name is not None:
        return truncate_hostname(default_name)
    return hostname


@contextlib.contextmanager
def temporary_mutation(obj, **kwargs):
    """Temporarily set the attr on a particular object to a given value then
    revert when finished.

    One use of this is to temporarily set the read_deleted flag on a context
    object:

        with temporary_mutation(context, read_deleted="yes"):
            do_something_that_needed_deleted_objects()
    """
    def is_dict_like(thing):
        return hasattr(thing, 'has_key')

    def get(thing, attr, default):
        if is_dict_like(thing):
            return thing.get(attr, default)
        else:
            return getattr(thing, attr, default)

    def set_value(thing, attr, val):
        if is_dict_like(thing):
            thing[attr] = val
        else:
            setattr(thing, attr, val)

    def delete(thing, attr):
        if is_dict_like(thing):
            del thing[attr]
        else:
            delattr(thing, attr)

    NOT_PRESENT = object()

    old_values = {}
    for attr, new_value in kwargs.items():
        old_values[attr] = get(obj, attr, NOT_PRESENT)
        set_value(obj, attr, new_value)

    try:
        yield
    finally:
        for attr, old_value in old_values.items():
            if old_value is NOT_PRESENT:
                delete(obj, attr)
            else:
                set_value(obj, attr, old_value)


def generate_mac_address():
    """Generate an Ethernet MAC address."""
    # NOTE(vish): We would prefer to use 0xfe here to ensure that linux
    #             bridge mac addresses don't change, but it appears to
    #             conflict with libvirt, so we use the next highest octet
    #             that has the unicast and locally administered bits set
    #             properly: 0xfa.
    #             Discussion: https://bugs.launchpad.net/nova/+bug/921838
    mac = [0xfa, 0x16, 0x3e,
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff),
           random.randint(0x00, 0xff)]
    return ':'.join(map(lambda x: "%02x" % x, mac))


def read_file_as_root(file_path):
    """Secure helper to read file as root."""
    try:
        out, _err = execute('cat', file_path, run_as_root=True)
        return out
    except processutils.ProcessExecutionError:
        raise exception.FileNotFound(file_path=file_path)


@contextlib.contextmanager
def temporary_chown(path, owner_uid=None):
    """Temporarily chown a path.

    :param owner_uid: UID of temporary owner (defaults to current user)
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
    argdict = kwargs.copy()
    if 'dir' not in argdict:
        argdict['dir'] = CONF.tempdir
    tmpdir = tempfile.mkdtemp(**argdict)
    try:
        yield tmpdir
    finally:
        try:
            shutil.rmtree(tmpdir)
        except OSError as e:
            LOG.error(_LE('Could not remove tmpdir: %s'), e)


def walk_class_hierarchy(clazz, encountered=None):
    """Walk class hierarchy, yielding most derived classes first."""
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


def mkfs(fs, path, label=None, run_as_root=False):
    """Format a file or block device

    :param fs: Filesystem type (examples include 'swap', 'ext3', 'ext4'
               'btrfs', etc.)
    :param path: Path to file or block device to format
    :param label: Volume label to use
    """
    if fs == 'swap':
        args = ['mkswap']
    else:
        args = ['mkfs', '-t', fs]
    # add -F to force no interactive execute on non-block device.
    if fs in ('ext3', 'ext4', 'ntfs'):
        args.extend(['-F'])
    if label:
        if fs in ('msdos', 'vfat'):
            label_opt = '-n'
        else:
            label_opt = '-L'
        args.extend([label_opt, label])
    args.append(path)
    execute(*args, run_as_root=run_as_root)


def last_bytes(file_like_object, num):
    """Return num bytes from the end of the file, and remaining byte count.

    :param file_like_object: The file to read
    :param num: The number of bytes to return

    :returns (data, remaining)
    """

    try:
        file_like_object.seek(-num, os.SEEK_END)
    except IOError as e:
        # seek() fails with EINVAL when trying to go before the start of the
        # file. It means that num is larger than the file size, so just
        # go to the start.
        if e.errno == errno.EINVAL:
            file_like_object.seek(0, os.SEEK_SET)
        else:
            raise

    remaining = file_like_object.tell()
    return (file_like_object.read(), remaining)


def metadata_to_dict(metadata, include_deleted=False):
    result = {}
    for item in metadata:
        if not include_deleted and item.get('deleted'):
            continue
        result[item['key']] = item['value']
    return result


def dict_to_metadata(metadata):
    result = []
    for key, value in six.iteritems(metadata):
        result.append(dict(key=key, value=value))
    return result


def instance_meta(instance):
    if isinstance(instance['metadata'], dict):
        return instance['metadata']
    else:
        return metadata_to_dict(instance['metadata'])


def instance_sys_meta(instance):
    if not instance.get('system_metadata'):
        return {}
    if isinstance(instance['system_metadata'], dict):
        return instance['system_metadata']
    else:
        return metadata_to_dict(instance['system_metadata'],
                                include_deleted=True)


def expects_func_args(*args):
    def _decorator_checker(dec):
        @functools.wraps(dec)
        def _decorator(f):
            base_f = safe_utils.get_wrapped_function(f)
            arg_names, a, kw, _default = inspect.getargspec(base_f)
            if a or kw or set(args) <= set(arg_names):
                # NOTE (ndipanov): We can't really tell if correct stuff will
                # be passed if it's a function with *args or **kwargs so
                # we still carry on and hope for the best
                return dec(f)
            else:
                raise TypeError("Decorated function %(f_name)s does not "
                                "have the arguments expected by the "
                                "decorator %(d_name)s" %
                                {'f_name': base_f.__name__,
                                 'd_name': dec.__name__})
        return _decorator
    return _decorator_checker


class ExceptionHelper(object):
    """Class to wrap another and translate the ClientExceptions raised by its
    function calls to the actual ones.
    """

    def __init__(self, target):
        self._target = target

    def __getattr__(self, name):
        func = getattr(self._target, name)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except messaging.ExpectedException as e:
                six.reraise(*e.exc_info)
        return wrapper


def check_string_length(value, name=None, min_length=0, max_length=None):
    """Check the length of specified string
    :param value: the value of the string
    :param name: the name of the string
    :param min_length: the min_length of the string
    :param max_length: the max_length of the string
    """
    if not isinstance(value, six.string_types):
        if name is None:
            msg = _("The input is not a string or unicode")
        else:
            msg = _("%s is not a string or unicode") % name
        raise exception.InvalidInput(message=msg)

    if name is None:
        name = value

    if len(value) < min_length:
        msg = _("%(name)s has a minimum character requirement of "
                "%(min_length)s.") % {'name': name, 'min_length': min_length}
        raise exception.InvalidInput(message=msg)

    if max_length and len(value) > max_length:
        msg = _("%(name)s has more than %(max_length)s "
                "characters.") % {'name': name, 'max_length': max_length}
        raise exception.InvalidInput(message=msg)


def validate_integer(value, name, min_value=None, max_value=None):
    """Make sure that value is a valid integer, potentially within range."""
    try:
        value = int(str(value))
    except (ValueError, UnicodeEncodeError):
        msg = _('%(value_name)s must be an integer')
        raise exception.InvalidInput(reason=(
            msg % {'value_name': name}))

    if min_value is not None:
        if value < min_value:
            msg = _('%(value_name)s must be >= %(min_value)d')
            raise exception.InvalidInput(
                reason=(msg % {'value_name': name,
                               'min_value': min_value}))
    if max_value is not None:
        if value > max_value:
            msg = _('%(value_name)s must be <= %(max_value)d')
            raise exception.InvalidInput(
                reason=(
                    msg % {'value_name': name,
                           'max_value': max_value})
            )
    return value


def spawn(func, *args, **kwargs):
    """Passthrough method for eventlet.spawn.

    This utility exists so that it can be stubbed for testing without
    interfering with the service spawns.

    It will also grab the context from the threadlocal store and add it to
    the store on the new thread.  This allows for continuity in logging the
    context when using this method to spawn a new thread.
    """
    _context = common_context.get_current()

    @functools.wraps(func)
    def context_wrapper(*args, **kwargs):
        # NOTE: If update_store is not called after spawn it won't be
        # available for the logger to pull from threadlocal storage.
        if _context is not None:
            _context.update_store()
        return func(*args, **kwargs)

    return eventlet.spawn(context_wrapper, *args, **kwargs)


def spawn_n(func, *args, **kwargs):
    """Passthrough method for eventlet.spawn_n.

    This utility exists so that it can be stubbed for testing without
    interfering with the service spawns.

    It will also grab the context from the threadlocal store and add it to
    the store on the new thread.  This allows for continuity in logging the
    context when using this method to spawn a new thread.
    """
    _context = common_context.get_current()

    @functools.wraps(func)
    def context_wrapper(*args, **kwargs):
        # NOTE: If update_store is not called after spawn_n it won't be
        # available for the logger to pull from threadlocal storage.
        if _context is not None:
            _context.update_store()
        func(*args, **kwargs)

    eventlet.spawn_n(context_wrapper, *args, **kwargs)


def is_none_string(val):
    """Check if a string represents a None value.
    """
    if not isinstance(val, six.string_types):
        return False

    return val.lower() == 'none'


def is_neutron():
    global _IS_NEUTRON

    if _IS_NEUTRON is not None:
        return _IS_NEUTRON

    # TODO(sdague): As long as network_api_class is importable
    # is_neutron can return None to mean we have no idea what their
    # class is.
    _IS_NEUTRON = (nova.network.is_neutron() is True)
    return _IS_NEUTRON


def is_auto_disk_config_disabled(auto_disk_config_raw):
    auto_disk_config_disabled = False
    if auto_disk_config_raw is not None:
        adc_lowered = auto_disk_config_raw.strip().lower()
        if adc_lowered == "disabled":
            auto_disk_config_disabled = True
    return auto_disk_config_disabled


def get_auto_disk_config_from_instance(instance=None, sys_meta=None):
    if sys_meta is None:
        sys_meta = instance_sys_meta(instance)
    return sys_meta.get("image_auto_disk_config")


def get_auto_disk_config_from_image_props(image_properties):
    return image_properties.get("auto_disk_config")


def get_system_metadata_from_image(image_meta, flavor=None):
    system_meta = {}
    prefix_format = SM_IMAGE_PROP_PREFIX + '%s'

    for key, value in six.iteritems(image_meta.get('properties', {})):
        if key in SM_SKIP_KEYS:
            continue

        new_value = safe_truncate(six.text_type(value), 255)
        system_meta[prefix_format % key] = new_value

    for key in SM_INHERITABLE_KEYS:
        value = image_meta.get(key)

        if key == 'min_disk' and flavor:
            if image_meta.get('disk_format') == 'vhd':
                value = flavor['root_gb']
            else:
                value = max(value or 0, flavor['root_gb'])

        if value is None:
            continue

        system_meta[prefix_format % key] = value

    return system_meta


def get_image_from_system_metadata(system_meta):
    image_meta = {}
    properties = {}

    if not isinstance(system_meta, dict):
        system_meta = metadata_to_dict(system_meta, include_deleted=True)

    for key, value in six.iteritems(system_meta):
        if value is None:
            continue

        # NOTE(xqueralt): Not sure this has to inherit all the properties or
        # just the ones we need. Leaving it for now to keep the old behaviour.
        if key.startswith(SM_IMAGE_PROP_PREFIX):
            key = key[len(SM_IMAGE_PROP_PREFIX):]

        if key in SM_SKIP_KEYS:
            continue

        if key in SM_INHERITABLE_KEYS:
            image_meta[key] = value
        else:
            properties[key] = value

    image_meta['properties'] = properties

    return image_meta


def get_image_metadata_from_volume(volume):
    properties = copy.copy(volume.get('volume_image_metadata', {}))
    image_meta = {'properties': properties}
    # Volume size is no longer related to the original image size,
    # so we take it from the volume directly. Cinder creates
    # volumes in Gb increments, and stores size in Gb, whereas
    # glance reports size in bytes. As we're returning glance
    # metadata here, we need to convert it.
    image_meta['size'] = volume.get('size', 0) * units.Gi
    # NOTE(yjiang5): restore the basic attributes
    # NOTE(mdbooth): These values come from volume_glance_metadata
    # in cinder. This is a simple key/value table, and all values
    # are strings. We need to convert them to ints to avoid
    # unexpected type errors.
    for attr in VIM_IMAGE_ATTRIBUTES:
        val = properties.pop(attr, None)
        if attr in ('min_ram', 'min_disk'):
            image_meta[attr] = int(val or 0)
    # NOTE(yjiang5): Always set the image status as 'active'
    # and depends on followed volume_api.check_attach() to
    # verify it. This hack should be harmless with that check.
    image_meta['status'] = 'active'
    return image_meta


def get_hash_str(base_str):
    """Returns string that represents MD5 hash of base_str (in hex format).

    If base_str is a Unicode string, encode it to UTF-8.
    """
    if isinstance(base_str, six.text_type):
        base_str = base_str.encode('utf-8')
    return hashlib.md5(base_str).hexdigest()


def filter_and_format_resource_metadata(resource_type, resource_list,
        search_filts, metadata_type=None):
    """Get all metadata for a list of resources after filtering.

    Search_filts is a list of dictionaries, where the values in the dictionary
    can be string or regex string, or a list of strings/regex strings.

    Let's call a dict a 'filter block' and an item in the dict
    a 'filter'. A tag is returned if it matches ALL the filters in
    a filter block. If more than one values are specified for a
    filter, a tag is returned if it matches ATLEAST ONE value of the filter. If
    more than one filter blocks are specified, the tag should match ALL the
    filter blocks.

    For example:

        search_filts = [{'key': ['key1', 'key2'], 'value': 'val1'},
                        {'value': 'val2'}]

    The filter translates to 'match any tag for which':
        ((key=key1 AND value=val1) OR (key=key2 AND value=val1)) AND
            (value=val2)

    This example filter will never match a tag.

        :param resource_type: The resource type as a string, e.g. 'instance'
        :param resource_list: List of resource objects
        :param search_filts: Filters to filter metadata to be returned. Can be
            dict (e.g. {'key': 'env', 'value': 'prod'}, or a list of dicts
            (e.g. [{'key': 'env'}, {'value': 'beta'}]. Note that the values
            of the dict can be regular expressions.
        :param metadata_type: Provided to search for a specific metadata type
            (e.g. 'system_metadata')

        :returns: List of dicts where each dict is of the form {'key':
            'somekey', 'value': 'somevalue', 'instance_id':
            'some-instance-uuid-aaa'} if resource_type is 'instance'.
    """

    if isinstance(search_filts, dict):
        search_filts = [search_filts]

    def _get_id(resource):
        if resource_type == 'instance':
            return resource.get('uuid')

    def _match_any(pattern_list, string):
        if isinstance(pattern_list, str):
            pattern_list = [pattern_list]
        return any([re.match(pattern, string)
                    for pattern in pattern_list])

    def _filter_metadata(resource, search_filt, input_metadata):
        ids = search_filt.get('resource_id', [])
        keys_filter = search_filt.get('key', [])
        values_filter = search_filt.get('value', [])
        output_metadata = {}

        if ids and _get_id(resource) not in ids:
            return {}

        for k, v in six.iteritems(input_metadata):
            # Both keys and value defined -- AND
            if (keys_filter and values_filter and
               not _match_any(keys_filter, k) and
               not _match_any(values_filter, v)):
                continue
            # Only keys or value is defined
            elif ((keys_filter and not _match_any(keys_filter, k)) or
                  (values_filter and not _match_any(values_filter, v))):
                continue

            output_metadata[k] = v
        return output_metadata

    formatted_metadata_list = []
    for res in resource_list:

        if resource_type == 'instance':
            # NOTE(rushiagr): metadata_type should be 'metadata' or
            # 'system_metadata' if resource_type is instance. Defaulting to
            # 'metadata' if not specified.
            if metadata_type is None:
                metadata_type = 'metadata'
            metadata = res.get(metadata_type, {})

        for filt in search_filts:
            # By chaining the input to the output, the filters are
            # ANDed together
            metadata = _filter_metadata(res, filt, metadata)

        for (k, v) in metadata.items():
            formatted_metadata_list.append({'key': k, 'value': v,
                             '%s_id' % resource_type: _get_id(res)})

    return formatted_metadata_list


def safe_truncate(value, length):
    """Safely truncates unicode strings such that their encoded length is
    no greater than the length provided.
    """
    b_value = encodeutils.safe_encode(value)[:length]

    # NOTE(chaochin) UTF-8 character byte size varies from 1 to 6. If
    # truncating a long byte string to 255, the last character may be
    # cut in the middle, so that UnicodeDecodeError will occur when
    # converting it back to unicode.
    decode_ok = False
    while not decode_ok:
        try:
            u_value = encodeutils.safe_decode(b_value)
            decode_ok = True
        except UnicodeDecodeError:
            b_value = b_value[:-1]
    return u_value


def read_cached_file(filename, force_reload=False):
    """Read from a file if it has been modified.

    :param force_reload: Whether to reload the file.
    :returns: A tuple with a boolean specifying if the data is fresh
              or not.
    """
    global _FILE_CACHE

    if force_reload:
        delete_cached_file(filename)

    reloaded = False
    mtime = os.path.getmtime(filename)
    cache_info = _FILE_CACHE.setdefault(filename, {})

    if not cache_info or mtime > cache_info.get('mtime', 0):
        LOG.debug("Reloading cached file %s", filename)
        with open(filename) as fap:
            cache_info['data'] = fap.read()
        cache_info['mtime'] = mtime
        reloaded = True
    return (reloaded, cache_info['data'])


def delete_cached_file(filename):
    """Delete cached file if present.

    :param filename: filename to delete
    """
    global _FILE_CACHE

    if filename in _FILE_CACHE:
        del _FILE_CACHE[filename]


def isotime(at=None):
    """Current time as ISO string,
    as timeutils.isotime() is deprecated

    :returns: Current time in ISO format
    """
    if not at:
        at = timeutils.utcnow()
    date_string = at.strftime("%Y-%m-%dT%H:%M:%S")
    tz = at.tzinfo.tzname(None) if at.tzinfo else 'UTC'
    date_string += ('Z' if tz == 'UTC' else tz)
    return date_string


def strtime(at):
    return at.strftime("%Y-%m-%dT%H:%M:%S.%f")
