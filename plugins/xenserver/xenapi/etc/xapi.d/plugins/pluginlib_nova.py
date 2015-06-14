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

# NOTE: XenServer still only supports Python 2.4 in it's dom0 userspace
# which means the Nova xenapi plugins must use only Python 2.4 features

#
# Helper functions for the Nova xapi plugins.  In time, this will merge
# with the pluginlib.py shipped with xapi, but for now, that file is not
# very stable, so it's easiest just to have a copy of all the functions
# that we need.
#

import gettext
import logging
import logging.handlers
import time

import XenAPI


translations = gettext.translation('nova', fallback=True)
_ = translations.ugettext


# Logging setup

def configure_logging(name):
    log = logging.getLogger()
    log.setLevel(logging.DEBUG)
    sysh = logging.handlers.SysLogHandler('/dev/log')
    sysh.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%s: %%(levelname)-8s %%(message)s' % name)
    sysh.setFormatter(formatter)
    log.addHandler(sysh)


# Exceptions

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


# Argument validation

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
    return None
    """
    return key in args and args[key] or None


def _get_domain_0(session):
    this_host_ref = session.xenapi.session.get_this_host(session.handle)
    expr = 'field "is_control_domain" = "true" and field "resident_on" = "%s"'
    expr = expr % this_host_ref
    return session.xenapi.VM.get_all_records_where(expr).keys()[0]


def with_vdi_in_dom0(session, vdi, read_only, f):
    dom0 = _get_domain_0(session)
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
        _vbd_unplug_with_retry(session, vbd)
        try:
            session.xenapi.VBD.destroy(vbd)
        except XenAPI.Failure, e:   # noqa
            logging.error(_('Ignoring XenAPI.Failure %s'), e)
        logging.debug(_('Destroying VBD for VDI %s done.'), vdi)


def _vbd_unplug_with_retry(session, vbd):
    """Call VBD.unplug on the given VBD, with a retry if we get
    DEVICE_DETACH_REJECTED.  For reasons which I don't understand, we're
    seeing the device still in use, even when all processes using the device
    should be dead.
    """
    while True:
        try:
            session.xenapi.VBD.unplug(vbd)
            logging.debug(_('VBD.unplug successful first time.'))
            return
        except XenAPI.Failure, e:   # noqa
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
