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
import functools
import hashlib
import inspect
import os
import random
import re
import shutil
import tempfile

import eventlet
from keystoneauth1 import exceptions as ks_exc
from keystoneauth1 import loading as ks_loading
import netaddr
from openstack import connection
from openstack import exceptions as sdk_exc
import os_resource_classes as orc
from os_service_types import service_types
from oslo_concurrency import lockutils
from oslo_concurrency import processutils
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

import nova.conf
from nova import exception
from nova.i18n import _, _LE, _LW
import nova.network
from nova import safe_utils

profiler = importutils.try_import('osprofiler.profiler')


CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

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

_SERVICE_TYPES = service_types.ServiceTypes()


if hasattr(inspect, 'getfullargspec'):
    getargspec = inspect.getfullargspec
else:
    getargspec = inspect.getargspec


# NOTE(mikal): this seems to have to stay for now to handle os-brick
# requirements. This makes me a sad panda.
def get_root_helper():
    if CONF.workarounds.disable_rootwrap:
        cmd = 'sudo'
    else:
        cmd = 'sudo nova-rootwrap %s' % CONF.rootwrap_config
    return cmd


def ssh_execute(dest, *cmd, **kwargs):
    """Convenience wrapper to execute ssh command."""
    ssh_cmd = ['ssh', '-o', 'BatchMode=yes']
    ssh_cmd.append(dest)
    ssh_cmd.extend(cmd)
    return processutils.execute(*ssh_cmd, **kwargs)


def generate_uid(topic, size=8):
    random_string = generate_random_string(size)
    return '%s-%s' % (topic, random_string)


def generate_random_string(size=8):
    characters = '01234567890abcdefghijklmnopqrstuvwxyz'
    return ''.join([random.choice(characters) for _x in range(size)])


# Default symbols to use for passwords. Avoids visually confusing characters.
# ~6 bits per symbol
DEFAULT_PASSWORD_SYMBOLS = ('23456789',  # Removed: 0,1
                            'ABCDEFGHJKLMNPQRSTUVWXYZ',   # Removed: I, O
                            'abcdefghijkmnopqrstuvwxyz')  # Removed: l


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

    else:  # unit == 'hour'
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


# TODO(sfinucan): Replace this with the equivalent from oslo.utils
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


def get_shortened_ipv6(address):
    addr = netaddr.IPAddress(address, version=6)
    return str(addr.ipv6())


def get_shortened_ipv6_cidr(address):
    net = netaddr.IPNetwork(address, version=6)
    return str(net.cidr)


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


def format_remote_path(host, path):
    """Returns remote path in format acceptable for scp/rsync.

    If host is IPv6 address literal, return '[host]:path', otherwise
    'host:path' is returned.

    If host is None, only path is returned.
    """
    if host is None:
        return path

    return "%s:%s" % (safe_ip_format(host), path)


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
    hostname = re.sub(r'[^\w.-]+', '', hostname)
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
        return hasattr(thing, 'has_key') or isinstance(thing, dict)

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


# NOTE(mikal): I really wanted this code to go away, but I can't find a way
# to implement what the callers of this method want with privsep. Basically,
# if we could hand off either a file descriptor or a file like object then
# we could make this go away.
@contextlib.contextmanager
def temporary_chown(path, owner_uid=None):
    """Temporarily chown a path.

    :param owner_uid: UID of temporary owner (defaults to current user)
    """
    if owner_uid is None:
        owner_uid = os.getuid()

    orig_uid = os.stat(path).st_uid

    if orig_uid != owner_uid:
        nova.privsep.path.chown(path, uid=owner_uid)
    try:
        yield
    finally:
        if orig_uid != owner_uid:
            nova.privsep.path.chown(path, uid=orig_uid)


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


def metadata_to_dict(metadata, include_deleted=False):
    result = {}
    for item in metadata:
        if not include_deleted and item.get('deleted'):
            continue
        result[item['key']] = item['value']
    return result


def dict_to_metadata(metadata):
    result = []
    for key, value in metadata.items():
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
            argspec = getargspec(base_f)
            if argspec[1] or argspec[2] or set(args) <= set(argspec[0]):
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
    try:
        strutils.check_string_length(value, name=name,
                                     min_length=min_length,
                                     max_length=max_length)
    except (ValueError, TypeError) as exc:
        raise exception.InvalidInput(message=exc.args[0])


def validate_integer(value, name, min_value=None, max_value=None):
    """Make sure that value is a valid integer, potentially within range.

    :param value: value of the integer
    :param name: name of the integer
    :param min_value: min_value of the integer
    :param max_value: max_value of the integer
    :returns: integer
    :raise: InvalidInput If value is not a valid integer
    """
    try:
        return strutils.validate_integer(value, name, min_value, max_value)
    except ValueError as e:
        raise exception.InvalidInput(reason=six.text_type(e))


def _serialize_profile_info():
    if not profiler:
        return None
    prof = profiler.get()
    trace_info = None
    if prof:
        # FIXME(DinaBelova): we'll add profiler.get_info() method
        # to extract this info -> we'll need to update these lines
        trace_info = {
            "hmac_key": prof.hmac_key,
            "base_id": prof.get_base_id(),
            "parent_id": prof.get_id()
        }
    return trace_info


def spawn(func, *args, **kwargs):
    """Passthrough method for eventlet.spawn.

    This utility exists so that it can be stubbed for testing without
    interfering with the service spawns.

    It will also grab the context from the threadlocal store and add it to
    the store on the new thread.  This allows for continuity in logging the
    context when using this method to spawn a new thread.
    """
    _context = common_context.get_current()
    profiler_info = _serialize_profile_info()

    @functools.wraps(func)
    def context_wrapper(*args, **kwargs):
        # NOTE: If update_store is not called after spawn it won't be
        # available for the logger to pull from threadlocal storage.
        if _context is not None:
            _context.update_store()
        if profiler_info and profiler:
            profiler.init(**profiler_info)
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
    profiler_info = _serialize_profile_info()

    @functools.wraps(func)
    def context_wrapper(*args, **kwargs):
        # NOTE: If update_store is not called after spawn_n it won't be
        # available for the logger to pull from threadlocal storage.
        if _context is not None:
            _context.update_store()
        if profiler_info and profiler:
            profiler.init(**profiler_info)
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

    _IS_NEUTRON = nova.network.is_neutron()
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

    for key, value in image_meta.get('properties', {}).items():
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

    for key, value in system_meta.items():
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
    # NOTE(mriedem): Set the status to 'active' as a really old hack
    # from when this method was in the compute API class and is
    # needed for _validate_flavor_image which makes sure the image
    # is 'active'. For volume-backed servers, if the volume is not
    # available because the image backing the volume is not active,
    # then the compute API trying to reserve the volume should fail.
    image_meta['status'] = 'active'
    return image_meta


def get_hash_str(base_str):
    """Returns string that represents MD5 hash of base_str (in hex format).

    If base_str is a Unicode string, encode it to UTF-8.
    """
    if isinstance(base_str, six.text_type):
        base_str = base_str.encode('utf-8')
    return hashlib.md5(base_str).hexdigest()


def get_sha256_str(base_str):
    """Returns string that represents sha256 hash of base_str (in hex format).

    sha1 and md5 are known to be breakable, so sha256 is a better option
    when the hash is being used for security purposes. If hashing passwords
    or anything else that needs to be retained for a long period a salted
    hash is better.
    """
    if isinstance(base_str, six.text_type):
        base_str = base_str.encode('utf-8')
    return hashlib.sha256(base_str).hexdigest()


def get_obj_repr_unicode(obj):
    """Returns a string representation of an object converted to unicode.

    In the case of python 3, this just returns the repr() of the object,
    else it converts the repr() to unicode.
    """
    obj_repr = repr(obj)
    if not six.PY3:
        obj_repr = six.text_type(obj_repr, 'utf-8')
    return obj_repr


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
    date_string += ('Z' if tz in ['UTC', 'UTC+00:00'] else tz)
    return date_string


def strtime(at):
    return at.strftime("%Y-%m-%dT%H:%M:%S.%f")


def _get_conf_group(service_type):
    # Get the conf group corresponding to the service type.
    confgrp = _SERVICE_TYPES.get_project_name(service_type)
    if not confgrp or not hasattr(CONF, confgrp):
        # Try the service type as the conf group.  This is necessary for e.g.
        # placement, while it's still part of the nova project.
        # Note that this might become the first thing we try if/as we move to
        # using service types for conf group names in general.
        confgrp = service_type
        if not confgrp or not hasattr(CONF, confgrp):
            raise exception.ConfGroupForServiceTypeNotFound(stype=service_type)
    return confgrp


def _get_auth_and_session(confgrp, ksa_auth=None, ksa_session=None):
    # Ensure we have an auth.
    # NOTE(efried): This could be None, and that could be okay - e.g. if the
    # result is being used for get_endpoint() and the conf only contains
    # endpoint_override.
    if not ksa_auth:
        if ksa_session and ksa_session.auth:
            ksa_auth = ksa_session.auth
        else:
            ksa_auth = ks_loading.load_auth_from_conf_options(CONF, confgrp)

    if not ksa_session:
        ksa_session = ks_loading.load_session_from_conf_options(
            CONF, confgrp, auth=ksa_auth)

    return ksa_auth, ksa_session


def get_ksa_adapter(service_type, ksa_auth=None, ksa_session=None,
                    min_version=None, max_version=None):
    """Construct a keystoneauth1 Adapter for a given service type.

    We expect to find a conf group whose name corresponds to the service_type's
    project according to the service-types-authority.  That conf group must
    provide at least ksa adapter options.  Depending how the result is to be
    used, ksa auth and/or session options may also be required, or the relevant
    parameter supplied.

    A raise_exc=False adapter is returned, meaning responses >=400 return the
    Response object rather than raising an exception.  This behavior can be
    overridden on a per-request basis by setting raise_exc=True.

    :param service_type: String name of the service type for which the Adapter
                         is to be constructed.
    :param ksa_auth: A keystoneauth1 auth plugin. If not specified, we attempt
                     to find one in ksa_session.  Failing that, we attempt to
                     load one from the conf.
    :param ksa_session: A keystoneauth1 Session.  If not specified, we attempt
                        to load one from the conf.
    :param min_version: The minimum major version of the adapter's endpoint,
                        intended to be used as the lower bound of a range with
                        max_version.
                        If min_version is given with no max_version it is as
                        if max version is 'latest'.
    :param max_version: The maximum major version of the adapter's endpoint,
                        intended to be used as the upper bound of a range with
                        min_version.
    :return: A keystoneauth1 Adapter object for the specified service_type.
    :raise: ConfGroupForServiceTypeNotFound If no conf group name could be
            found for the specified service_type.
    """
    confgrp = _get_conf_group(service_type)

    ksa_auth, ksa_session = _get_auth_and_session(
        confgrp, ksa_auth, ksa_session)

    return ks_loading.load_adapter_from_conf_options(
        CONF, confgrp, session=ksa_session, auth=ksa_auth,
        min_version=min_version, max_version=max_version, raise_exc=False)


def get_sdk_adapter(service_type, check_service=False):
    """Construct an openstacksdk-brokered Adapter for a given service type.

    We expect to find a conf group whose name corresponds to the service_type's
    project according to the service-types-authority.  That conf group must
    provide ksa auth, session, and adapter options.

    :param service_type: String name of the service type for which the Adapter
                         is to be constructed.
    :param check_service: If True, we will query the endpoint to make sure the
            service is alive, raising ServiceUnavailable if it is not.
    :return: An openstack.proxy.Proxy object for the specified service_type.
    :raise: ConfGroupForServiceTypeNotFound If no conf group name could be
            found for the specified service_type.
    :raise: ServiceUnavailable if check_service is True and the service is down
    """
    confgrp = _get_conf_group(service_type)
    sess = _get_auth_and_session(confgrp)[1]
    try:
        conn = connection.Connection(
            session=sess, oslo_conf=CONF, service_types={service_type},
            strict_proxies=check_service)
    except sdk_exc.ServiceDiscoveryException as e:
        raise exception.ServiceUnavailable(
            _("The %(service_type)s service is unavailable: %(error)s") %
            {'service_type': service_type, 'error': six.text_type(e)})
    return getattr(conn, service_type)


def get_endpoint(ksa_adapter):
    """Get the endpoint URL represented by a keystoneauth1 Adapter.

    This method is equivalent to what

        ksa_adapter.get_endpoint()

    should do, if it weren't for a panoply of bugs.

    :param ksa_adapter: keystoneauth1.adapter.Adapter, appropriately set up
                        with an endpoint_override; or service_type, interface
                        (list) and auth/service_catalog.
    :return: String endpoint URL.
    :raise EndpointNotFound: If endpoint discovery fails.
    """
    # TODO(efried): This will be unnecessary once bug #1707993 is fixed.
    # (At least for the non-image case, until 1707995 is fixed.)
    if ksa_adapter.endpoint_override:
        return ksa_adapter.endpoint_override
    # TODO(efried): Remove this once bug #1707995 is fixed.
    if ksa_adapter.service_type == 'image':
        try:
            return ksa_adapter.get_endpoint_data().catalog_url
        except AttributeError:
            # ksa_adapter.auth is a _ContextAuthPlugin, which doesn't have
            # get_endpoint_data.  Fall through to using get_endpoint().
            pass
    # TODO(efried): The remainder of this method reduces to
    # TODO(efried):     return ksa_adapter.get_endpoint()
    # TODO(efried): once bug #1709118 is fixed.
    # NOTE(efried): Id9bd19cca68206fc64d23b0eaa95aa3e5b01b676 may also do the
    #               trick, once it's in a ksa release.
    # The EndpointNotFound exception happens when _ContextAuthPlugin is in play
    # because its get_endpoint() method isn't yet set up to handle interface as
    # a list.  (It could also happen with a real auth if the endpoint isn't
    # there; but that's covered below.)
    try:
        return ksa_adapter.get_endpoint()
    except ks_exc.EndpointNotFound:
        pass

    interfaces = list(ksa_adapter.interface)
    for interface in interfaces:
        ksa_adapter.interface = interface
        try:
            return ksa_adapter.get_endpoint()
        except ks_exc.EndpointNotFound:
            pass
    raise ks_exc.EndpointNotFound(
        "Could not find requested endpoint for any of the following "
        "interfaces: %s" % interfaces)


def generate_hostid(host, project_id):
    """Generate an obfuscated host id representing the host.

    This is a hashed value so will not actually look like a hostname, and is
    hashed with data from the project_id.

    :param host: The name of the compute host.
    :param project_id: The UUID of the project.
    :return: An obfuscated hashed host id string, return "" if host is empty
    """
    if host:
        data = (project_id + host).encode('utf-8')
        sha_hash = hashlib.sha224(data)
        return sha_hash.hexdigest()
    return ""


if six.PY2:
    nested_contexts = contextlib.nested
else:
    @contextlib.contextmanager
    def nested_contexts(*contexts):
        with contextlib.ExitStack() as stack:
            yield [stack.enter_context(c) for c in contexts]


def run_once(message, logger, cleanup=None):
    """This is a utility function decorator to ensure a function
    is run once and only once in an interpreter instance.
    The decorated function object can be reset by calling its
    reset function. All exceptions raised by the wrapped function,
    logger and cleanup function will be propagated to the caller.
    """
    def outer_wrapper(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not wrapper.called:
                # Note(sean-k-mooney): the called state is always
                # updated even if the wrapped function completes
                # by raising an exception. If the caller catches
                # the exception it is their responsibility to call
                # reset if they want to re-execute the wrapped function.
                try:
                    return func(*args, **kwargs)
                finally:
                    wrapper.called = True
            else:
                logger(message)

        wrapper.called = False

        def reset(wrapper, *args, **kwargs):
            # Note(sean-k-mooney): we conditionally call the
            # cleanup function if one is provided only when the
            # wrapped function has been called previously. We catch
            # and reraise any exception that may be raised and update
            # the called state in a finally block to ensure its
            # always updated if reset is called.
            try:
                if cleanup and wrapper.called:
                    return cleanup(*args, **kwargs)
            finally:
                wrapper.called = False

        wrapper.reset = functools.partial(reset, wrapper)
        return wrapper
    return outer_wrapper


def normalize_rc_name(rc_name):
    """Normalize a resource class name to standard form."""
    if rc_name is None:
        return None
    # Replace non-alphanumeric characters with underscores
    norm_name = re.sub('[^0-9A-Za-z]+', '_', rc_name)
    # Bug #1762789: Do .upper after replacing non alphanumerics.
    norm_name = norm_name.upper()
    norm_name = orc.CUSTOM_NAMESPACE + norm_name
    return norm_name
