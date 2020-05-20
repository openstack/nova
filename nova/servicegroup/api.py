# Copyright 2012 IBM Corp.
# Copyright (c) AT&T Labs Inc. 2012 Yun Mao <yunmao@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Define APIs for the servicegroup access."""

from oslo_log import log as logging
from oslo_utils import importutils

import nova.conf

LOG = logging.getLogger(__name__)

_driver_name_class_mapping = {
    'db': 'nova.servicegroup.drivers.db.DbDriver',
    'mc': 'nova.servicegroup.drivers.mc.MemcachedDriver'
}

CONF = nova.conf.CONF

# NOTE(geekinutah): By default drivers wait 5 seconds before reporting
INITIAL_REPORTING_DELAY = 5


class API(object):

    def __init__(self, *args, **kwargs):
        '''Create an instance of the servicegroup API.

        args and kwargs are passed down to the servicegroup driver when it gets
        created.
        '''
        # Make sure report interval is less than service down time
        report_interval = CONF.report_interval
        if CONF.service_down_time <= report_interval:
            new_service_down_time = int(report_interval * 2.5)
            LOG.warning("Report interval must be less than service down "
                        "time. Current config: <service_down_time: "
                        "%(service_down_time)s, report_interval: "
                        "%(report_interval)s>. Setting service_down_time "
                        "to: %(new_service_down_time)s",
                        {'service_down_time': CONF.service_down_time,
                         'report_interval': report_interval,
                         'new_service_down_time': new_service_down_time})
            CONF.set_override('service_down_time', new_service_down_time)

        driver_class = _driver_name_class_mapping[CONF.servicegroup_driver]
        self._driver = importutils.import_object(driver_class,
                                                 *args, **kwargs)

    def join(self, member, group, service=None):
        """Add a new member to a service group.

        :param member: the joined member ID/name
        :param group: the group ID/name, of the joined member
        :param service: a `nova.service.Service` object
        """
        return self._driver.join(member, group, service)

    def service_is_up(self, member):
        """Check if the given member is up."""
        # NOTE(johngarbutt) no logging in this method,
        # so this doesn't slow down the scheduler
        if member.get('forced_down'):
            return False

        return self._driver.is_up(member)

    def get_updated_time(self, member):
        """Get the updated time from drivers except db"""
        return self._driver.updated_time(member)
