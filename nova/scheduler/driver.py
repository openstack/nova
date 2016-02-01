# Copyright (c) 2010 OpenStack Foundation
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Scheduler base class that all Schedulers should inherit from
"""

import abc

from oslo_log import log as logging
from oslo_utils import importutils
import six
from stevedore import driver

import nova.conf
from nova.i18n import _, _LW
from nova import objects
from nova import servicegroup

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    def __init__(self):
        try:
            self.host_manager = driver.DriverManager(
                    "nova.scheduler.host_manager",
                    CONF.scheduler_host_manager,
                    invoke_on_load=True).driver
        # TODO(Yingxin): Change to catch stevedore.exceptions.NoMatches
        # after stevedore v1.9.0
        except RuntimeError:
            # NOTE(Yingxin): Loading full class path is deprecated and
            # should be removed in the N release.
            try:
                self.host_manager = importutils.import_object(
                    CONF.scheduler_host_manager)
                LOG.warning(_LW("DEPRECATED: scheduler_host_manager uses "
                                "classloader to load %(path)s. This legacy "
                                "loading style will be removed in the "
                                "N release."),
                            {'path': CONF.scheduler_host_manager})
            except (ImportError, ValueError):
                raise RuntimeError(
                        _("Cannot load host manager from configuration "
                          "scheduler_host_manager = %(conf)s."),
                        {'conf': CONF.scheduler_host_manager})
        self.servicegroup_api = servicegroup.API()

    def run_periodic_tasks(self, context):
        """Manager calls this so drivers can perform periodic tasks."""
        pass

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = objects.ServiceList.get_by_topic(context, topic)
        return [service.host
                for service in services
                if self.servicegroup_api.service_is_up(service)]

    @abc.abstractmethod
    def select_destinations(self, context, spec_obj):
        """Must override select_destinations method.

        :return: A list of dicts with 'host', 'nodename' and 'limits' as keys
            that satisfies the request_spec and filter_properties.
        """
        return []
