# Copyright (c) 2010 Citrix Systems, Inc.
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

#
# Helper functions for the Nova xapi plugins.  In time, this will merge
# with the pluginlib.py shipped with xapi, but for now, that file is not
# very stable, so it's easiest just to have a copy of all the functions
# that we need.
#

import gettext
gettext.install('nova', unicode=1)
import httplib
import logging
import logging.handlers
import re
import time
import XenAPI


##### Logging setup

def configure_logging(name):
    log = logging.getLogger()
    log.setLevel(logging.DEBUG)
    sysh = logging.handlers.SysLogHandler('/dev/log')
    sysh.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%s: %%(levelname)-8s %%(message)s' % name)
    sysh.setFormatter(formatter)
    log.addHandler(sysh)


##### Exceptions

class PluginError(Exception):
    """Base Exception class for all plugin errors."""
    def __init__(self, *args):
        Exception.__init__(self, *args)


class ArgumentError(PluginError):
    """Raised when required arguments are missing, argument values are invalid,
    or incompatible arguments are given.
    """
    def __init__(self, *args):
        PluginError.__init__(self, *args)


##### Helpers

def ignore_failure(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except XenAPI.Failure, e:
        logging.error(_('Ignoring XenAPI.Failure %s'), e)
        return None


##### Argument validation

ARGUMENT_PATTERN = re.compile(r'^[a-zA-Z0-9_:\.\-,]+$')


def validate_exists(args, key, default=None):
    """Validates that a string argument to a RPC method call is given, and
    matches the shell-safe regex, with an optional default value in case it
    does not exist.

    Returns the string.
    """
    if key in args:
        if len(args[key]) == 0:
            raise ArgumentError(_('Argument %(key)s value %(value)s is too '
                                  'short.') %
                                {'key': key,
                                 'value': args[key]})
        if not ARGUMENT_PATTERN.match(args[key]):
            raise ArgumentError(_('Argument %(key)s value %(value)s contains '
                                  'invalid characters.') %
                                  {'key': key,
                                   'value': args[key]})
        if args[key][0] == '-':
            raise ArgumentError(_('Argument %(key)s value %(value)s starts '
                                  'with a hyphen.') %
                                {'key': key,
                                 'value': args[key]})
        return args[key]
    elif default is not None:
        return default
    else:
        raise ArgumentError(_('Argument %s is required.') % key)


def validate_bool(args, key, default=None):
    """Validates that a string argument to a RPC method call is a boolean
    string, with an optional default value in case it does not exist.

    Returns the python boolean value.
    """
    value = validate_exists(args, key, default)
    if value.lower() == 'true':
        return True
    elif value.lower() == 'false':
        return False
    else:
        raise ArgumentError(_("Argument %(key)s may not take value %(value)s. "
                              "Valid values are ['true', 'false'].")
                            % {'key': key,
                               'value': value})


def exists(args, key):
    """Validates that a freeform string argument to a RPC method call is given.
    Returns the string.
    """
    if key in args:
        return args[key]
    else:
        raise ArgumentError(_('Argument %s is required.') % key)


def optional(args, key):
    """If the given key is in args, return the corresponding value, otherwise
    return None"""
    return key in args and args[key] or None


def get_this_host(session):
    return session.xenapi.session.get_this_host(session.handle)


def get_domain_0(session):
    this_host_ref = get_this_host(session)
    expr = 'field "is_control_domain" = "true" and field "resident_on" = "%s"'
    expr = expr % this_host_ref
    return session.xenapi.VM.get_all_records_where(expr).keys()[0]


def create_vdi(session, sr_ref, name_label, virtual_size, read_only):
    vdi_ref = session.xenapi.VDI.create(
         {'name_label': name_label,
          'name_description': '',
          'SR': sr_ref,
          'virtual_size': str(virtual_size),
          'type': 'User',
          'sharable': False,
          'read_only': read_only,
          'xenstore_data': {},
          'other_config': {},
          'sm_config': {},
          'tags': []})
    logging.debug(_('Created VDI %(vdi_ref)s (%(label)s, %(size)s, '
                    '%(read_only)s) on %(sr_ref)s.') %
                  {'vdi_ref': vdi_ref,
                   'label': name_label,
                   'size': virtual_size,
                   'read_only': read_only,
                   'sr_ref': sr_ref})
    return vdi_ref


def with_vdi_in_dom0(session, vdi, read_only, f):
    dom0 = get_domain_0(session)
    vbd_rec = {}
    vbd_rec['VM'] = dom0
    vbd_rec['VDI'] = vdi
    vbd_rec['userdevice'] = 'autodetect'
    vbd_rec['bootable'] = False
    vbd_rec['mode'] = read_only and 'RO' or 'RW'
    vbd_rec['type'] = 'disk'
    vbd_rec['unpluggable'] = True
    vbd_rec['empty'] = False
    vbd_rec['other_config'] = {}
    vbd_rec['qos_algorithm_type'] = ''
    vbd_rec['qos_algorithm_params'] = {}
    vbd_rec['qos_supported_algorithms'] = []
    logging.debug(_('Creating VBD for VDI %s ... '), vdi)
    vbd = session.xenapi.VBD.create(vbd_rec)
    logging.debug(_('Creating VBD for VDI %s done.'), vdi)
    try:
        logging.debug(_('Plugging VBD %s ... '), vbd)
        session.xenapi.VBD.plug(vbd)
        logging.debug(_('Plugging VBD %s done.'), vbd)
        return f(session.xenapi.VBD.get_device(vbd))
    finally:
        logging.debug(_('Destroying VBD for VDI %s ... '), vdi)
        vbd_unplug_with_retry(session, vbd)
        ignore_failure(session.xenapi.VBD.destroy, vbd)
        logging.debug(_('Destroying VBD for VDI %s done.'), vdi)


def vbd_unplug_with_retry(session, vbd):
    """Call VBD.unplug on the given VBD, with a retry if we get
    DEVICE_DETACH_REJECTED.  For reasons which I don't understand, we're
    seeing the device still in use, even when all processes using the device
    should be dead."""
    while True:
        try:
            session.xenapi.VBD.unplug(vbd)
            logging.debug(_('VBD.unplug successful first time.'))
            return
        except XenAPI.Failure, e:
            if (len(e.details) > 0 and
                e.details[0] == 'DEVICE_DETACH_REJECTED'):
                logging.debug(_('VBD.unplug rejected: retrying...'))
                time.sleep(1)
            elif (len(e.details) > 0 and
                  e.details[0] == 'DEVICE_ALREADY_DETACHED'):
                logging.debug(_('VBD.unplug successful eventually.'))
                return
            else:
                logging.error(_('Ignoring XenAPI.Failure in VBD.unplug: %s'),
                              e)
                return


def with_http_connection(proto, netloc, f):
    conn = (proto == 'https' and
            httplib.HTTPSConnection(netloc) or
            httplib.HTTPConnection(netloc))
    try:
        return f(conn)
    finally:
        conn.close()


def with_file(dest_path, mode, f):
    dest = open(dest_path, mode)
    try:
        return f(dest)
    finally:
        dest.close()
