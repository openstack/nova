# Copyright 2011 OpenStack LLC.
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

from nova.openstack.common import cfg
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import log as logging


list_notifier_drivers_opt = cfg.MultiStrOpt('list_notifier_drivers',
        default=['nova.openstack.common.notifier.no_op_notifier'],
        help='List of drivers to send notifications')

CONF = cfg.CONF
CONF.register_opt(list_notifier_drivers_opt)

LOG = logging.getLogger(__name__)

drivers = None


class ImportFailureNotifier(object):
    """Noisily re-raises some exception over-and-over when notify is called."""

    def __init__(self, exception):
        self.exception = exception

    def notify(self, context, message):
        raise self.exception


def _get_drivers():
    """Instantiates and returns drivers based on the flag values."""
    global drivers
    if drivers is None:
        drivers = []
        for notification_driver in CONF.list_notifier_drivers:
            try:
                drivers.append(importutils.import_module(notification_driver))
            except ImportError as e:
                drivers.append(ImportFailureNotifier(e))
    return drivers


def add_driver(notification_driver):
    """Add a notification driver at runtime."""
    # Make sure the driver list is initialized.
    _get_drivers()
    if isinstance(notification_driver, basestring):
        # Load and add
        try:
            drivers.append(importutils.import_module(notification_driver))
        except ImportError as e:
            drivers.append(ImportFailureNotifier(e))
    else:
        # Driver is already loaded; just add the object.
        drivers.append(notification_driver)


def _object_name(obj):
    name = []
    if hasattr(obj, '__module__'):
        name.append(obj.__module__)
    if hasattr(obj, '__name__'):
        name.append(obj.__name__)
    else:
        name.append(obj.__class__.__name__)
    return '.'.join(name)


def remove_driver(notification_driver):
    """Remove a notification driver at runtime."""
    # Make sure the driver list is initialized.
    _get_drivers()
    removed = False
    if notification_driver in drivers:
        # We're removing an object.  Easy.
        drivers.remove(notification_driver)
        removed = True
    else:
        # We're removing a driver by name.  Search for it.
        for driver in drivers:
            if _object_name(driver) == notification_driver:
                drivers.remove(driver)
                removed = True

    if not removed:
        raise ValueError("Cannot remove; %s is not in list" %
                         notification_driver)


def notify(context, message):
    """Passes notification to multiple notifiers in a list."""
    for driver in _get_drivers():
        try:
            driver.notify(context, message)
        except Exception as e:
            LOG.exception(_("Problem '%(e)s' attempting to send to "
                            "notification driver %(driver)s."), locals())


def _reset_drivers():
    """Used by unit tests to reset the drivers."""
    global drivers
    drivers = None
