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

from oslo_config import cfg
from oslo_utils import importutils

from nova.i18n import _, _LW
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)
_default_driver = 'db'
servicegroup_driver_opt = cfg.StrOpt('servicegroup_driver',
                                     default=_default_driver,
                                     help='The driver for servicegroup '
                                          'service (valid options are: '
                                          'db, zk, mc)')

CONF = cfg.CONF
CONF.register_opt(servicegroup_driver_opt)

# NOTE(geekinutah): By default drivers wait 5 seconds before reporting
INITIAL_REPORTING_DELAY = 5


class API(object):

    _driver = None
    _driver_name_class_mapping = {
        'db': 'nova.servicegroup.drivers.db.DbDriver',
        'zk': 'nova.servicegroup.drivers.zk.ZooKeeperDriver',
        'mc': 'nova.servicegroup.drivers.mc.MemcachedDriver'
    }

    def __new__(cls, *args, **kwargs):
        '''Create an instance of the servicegroup API.

        args and kwargs are passed down to the servicegroup driver when it gets
        created.  No args currently exist, though.  Valid kwargs are:

        db_allowed - Boolean. False if direct db access is not allowed and
                     alternative data access (conductor) should be used
                     instead.
        '''

        if not cls._driver:
            LOG.debug('ServiceGroup driver defined as an instance of %s',
                      str(CONF.servicegroup_driver))
            driver_name = CONF.servicegroup_driver
            try:
                driver_class = cls._driver_name_class_mapping[driver_name]
            except KeyError:
                raise TypeError(_("unknown ServiceGroup driver name: %s")
                                % driver_name)
            cls._driver = importutils.import_object(driver_class,
                                                    *args, **kwargs)
        return super(API, cls).__new__(cls)

    def __init__(self, *args, **kwargs):
        self.basic_config_check()

    def basic_config_check(self):
        """Perform basic config check."""
        # Make sure report interval is less than service down time
        report_interval = CONF.report_interval
        if CONF.service_down_time <= report_interval:
            new_service_down_time = int(report_interval * 2.5)
            LOG.warning(_LW("Report interval must be less than service down "
                            "time. Current config: <service_down_time: "
                            "%(service_down_time)s, report_interval: "
                            "%(report_interval)s>. Setting service_down_time "
                            "to: %(new_service_down_time)s"),
                        {'service_down_time': CONF.service_down_time,
                         'report_interval': report_interval,
                         'new_service_down_time': new_service_down_time})
            CONF.set_override('service_down_time', new_service_down_time)

    def join(self, member_id, group_id, service=None):
        """Add a new member to the ServiceGroup

        @param member_id: the joined member ID
        @param group_id: the group name, of the joined member
        @param service: the parameter can be used for notifications about
        disconnect mode and update some internals
        """

        LOG.debug('Join new ServiceGroup member %(member_id)s to the '
                  '%(group_id)s group, service = %(service)s',
                  {'member_id': member_id,
                   'group_id': group_id,
                   'service': service})
        return self._driver.join(member_id, group_id, service)

    def service_is_up(self, member):
        """Check if the given member is up."""
        # NOTE(johngarbutt) no logging in this method,
        # so this doesn't slow down the scheduler
        return self._driver.is_up(member)

    def leave(self, member_id, group_id):
        """Explicitly remove the given member from the ServiceGroup
        monitoring.
        """
        LOG.debug('Explicitly remove the given member %(member_id)s from the'
                  '%(group_id)s group monitoring',
                  {'member_id': member_id, 'group_id': group_id})
        return self._driver.leave(member_id, group_id)

    def get_all(self, group_id):
        """Returns ALL members of the given group."""
        LOG.debug('Returns ALL members of the [%s] '
                  'ServiceGroup', group_id)
        return self._driver.get_all(group_id)

    def get_one(self, group_id):
        """Returns one member of the given group. The strategy to select
        the member is decided by the driver (e.g. random or round-robin).
        """
        LOG.debug('Returns one member of the [%s] group', group_id)
        return self._driver.get_one(group_id)
