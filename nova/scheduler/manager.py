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
Scheduler Service
"""

from oslo_config import cfg
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils import importutils

from nova import exception
from nova import manager
from nova import objects
from nova.openstack.common import log as logging
from nova.openstack.common import periodic_task
from nova import quota


LOG = logging.getLogger(__name__)

scheduler_driver_opts = [
    cfg.StrOpt('scheduler_driver',
               default='nova.scheduler.filter_scheduler.FilterScheduler',
               help='Default driver to use for the scheduler'),
    cfg.IntOpt('scheduler_driver_task_period',
               default=60,
               help='How often (in seconds) to run periodic tasks in '
                    'the scheduler driver of your choice. '
                    'Please note this is likely to interact with the value '
                    'of service_down_time, but exactly how they interact '
                    'will depend on your choice of scheduler driver.'),
]
CONF = cfg.CONF
CONF.register_opts(scheduler_driver_opts)

QUOTAS = quota.QUOTAS


class SchedulerManager(manager.Manager):
    """Chooses a host to run instances on."""

    target = messaging.Target(version='4.0')

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = CONF.scheduler_driver
        self.driver = importutils.import_object(scheduler_driver)
        super(SchedulerManager, self).__init__(service_name='scheduler',
                                               *args, **kwargs)
        self.additional_endpoints.append(_SchedulerManagerV3Proxy(self))

    @periodic_task.periodic_task
    def _expire_reservations(self, context):
        QUOTAS.expire(context)

    @periodic_task.periodic_task(spacing=CONF.scheduler_driver_task_period,
                                 run_immediately=True)
    def _run_periodic_tasks(self, context):
        self.driver.run_periodic_tasks(context)

    @messaging.expected_exceptions(exception.NoValidHost)
    def select_destinations(self, context, request_spec, filter_properties):
        """Returns destinations(s) best suited for this request_spec and
        filter_properties.

        The result should be a list of dicts with 'host', 'nodename' and
        'limits' as keys.
        """
        dests = self.driver.select_destinations(context, request_spec,
            filter_properties)
        return jsonutils.to_primitive(dests)


class _SchedulerManagerV3Proxy(object):

    target = messaging.Target(version='3.0')

    def __init__(self, manager):
        self.manager = manager

    # NOTE(sbauza): Previous run_instance() and prep_resize() methods were
    # removed from the Juno branch before Juno released, so we can safely
    # remove them even from the V3.1 proxy as there is no Juno RPC client
    # that can call them
    @messaging.expected_exceptions(exception.NoValidHost)
    def select_destinations(self, context, request_spec, filter_properties):
        """Returns destinations(s) best suited for this request_spec and
        filter_properties.

        The result should be a list of dicts with 'host', 'nodename' and
        'limits' as keys.
        """
        # TODO(melwitt): Remove this in version 4.0 of the RPC API
        flavor = filter_properties.get('instance_type')
        if flavor and not isinstance(flavor, objects.Flavor):
            # Code downstream may expect extra_specs to be populated since it
            # is receiving an object, so lookup the flavor to ensure this.
            flavor = objects.Flavor.get_by_id(context, flavor['id'])
            filter_properties = dict(filter_properties, instance_type=flavor)
        dests = self.manager.select_destinations(context, request_spec,
            filter_properties)
        return dests
