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

from nova import flags
from nova import log as logging
from nova import utils
from nova.exception import ClassNotFound

flags.DEFINE_multistring('list_notifier_drivers',
                         ['nova.notifier.no_op_notifier'],
                         'List of drivers to send notifications')

FLAGS = flags.FLAGS

LOG = logging.getLogger('nova.notifier.list_notifier')

drivers = None


class ImportFailureNotifier(object):
    """Noisily re-raises some exception over-and-over when notify is called."""

    def __init__(self, exception):
        self.exception = exception

    def notify(self, message):
        raise self.exception


def _get_drivers():
    """Instantiates and returns drivers based on the flag values."""
    global drivers
    if not drivers:
        drivers = []
        for notification_driver in FLAGS.list_notifier_drivers:
            try:
                drivers.append(utils.import_object(notification_driver))
            except ClassNotFound as e:
                drivers.append(ImportFailureNotifier(e))
    return drivers


def notify(message):
    """Passes notification to mulitple notifiers in a list."""
    for driver in _get_drivers():
        try:
            driver.notify(message)
        except Exception as e:
            LOG.exception(_("Problem '%(e)s' attempting to send to "
                            "notification driver %(driver)s." % locals()))


def _reset_drivers():
    """Used by unit tests to reset the drivers."""
    global drivers
    drivers = None
