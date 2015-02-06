# Copyright (c) 2011 OpenStack Foundation
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
SchedulerOptions monitors a local .json file for changes and loads
it if needed. This file is converted to a data structure and passed
into the filtering and weighing functions which can use it for
dynamic configuration.
"""

import datetime
import os

from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import timeutils

from nova.i18n import _LE
from nova.openstack.common import log as logging


scheduler_json_config_location_opt = cfg.StrOpt(
        'scheduler_json_config_location',
        default='',
        help='Absolute path to scheduler configuration JSON file.')

CONF = cfg.CONF
CONF.register_opt(scheduler_json_config_location_opt)

LOG = logging.getLogger(__name__)


class SchedulerOptions(object):
    """SchedulerOptions monitors a local .json file for changes and loads it
    if needed. This file is converted to a data structure and passed into
    the filtering and weighing functions which can use it for dynamic
    configuration.
    """

    def __init__(self):
        super(SchedulerOptions, self).__init__()
        self.data = {}
        self.last_modified = None
        self.last_checked = None

    def _get_file_handle(self, filename):
        """Get file handle. Broken out for testing."""
        return open(filename)

    def _get_file_timestamp(self, filename):
        """Get the last modified datetime. Broken out for testing."""
        try:
            return os.path.getmtime(filename)
        except os.error as e:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Could not stat scheduler options file "
                                  "%(filename)s: '%(e)s'"),
                              {'filename': filename, 'e': e})

    def _load_file(self, handle):
        """Decode the JSON file. Broken out for testing."""
        try:
            return jsonutils.load(handle)
        except ValueError as e:
            LOG.exception(_LE("Could not decode scheduler options: '%s'"), e)
            return {}

    def _get_time_now(self):
        """Get current UTC. Broken out for testing."""
        return timeutils.utcnow()

    def get_configuration(self, filename=None):
        """Check the json file for changes and load it if needed."""
        if not filename:
            filename = CONF.scheduler_json_config_location
        if not filename:
            return self.data
        if self.last_checked:
            now = self._get_time_now()
            if now - self.last_checked < datetime.timedelta(minutes=5):
                return self.data

        last_modified = self._get_file_timestamp(filename)
        if (not last_modified or not self.last_modified or
                last_modified > self.last_modified):
            self.data = self._load_file(self._get_file_handle(filename))
            self.last_modified = last_modified
        if not self.data:
            self.data = {}

        return self.data
