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

from oslo.config import cfg
from oslo import messaging

from nova.compute import rpcapi as compute_rpcapi
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import exception
from nova import manager
from nova import objects
from nova.openstack.common import excutils
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import periodic_task
from nova import quota
from nova.scheduler import utils as scheduler_utils


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

    target = messaging.Target(version='3.0')

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = CONF.scheduler_driver
        self.driver = importutils.import_object(scheduler_driver)
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        super(SchedulerManager, self).__init__(service_name='scheduler',
                                               *args, **kwargs)

    # NOTE(alaski): Remove this method when the scheduler rpc interface is
    # bumped to 4.x as it is no longer used.
    def run_instance(self, context, request_spec, admin_password,
            injected_files, requested_networks, is_first_time,
            filter_properties, legacy_bdm_in_spec):
        """Tries to call schedule_run_instance on the driver.
        Sets instance vm_state to ERROR on exceptions
        """
        instance_uuids = request_spec['instance_uuids']
        with compute_utils.EventReporter(context, 'schedule', *instance_uuids):
            try:
                return self.driver.schedule_run_instance(context,
                        request_spec, admin_password, injected_files,
                        requested_networks, is_first_time, filter_properties,
                        legacy_bdm_in_spec)

            except exception.NoValidHost as ex:
                # don't re-raise
                self._set_vm_state_and_notify('run_instance',
                                              {'vm_state': vm_states.ERROR,
                                              'task_state': None},
                                              context, ex, request_spec)
            except Exception as ex:
                with excutils.save_and_reraise_exception():
                    self._set_vm_state_and_notify('run_instance',
                                                  {'vm_state': vm_states.ERROR,
                                                  'task_state': None},
                                                  context, ex, request_spec)

    # NOTE(sbauza): Remove this method when the scheduler rpc interface is
    # bumped to 4.x as it is no longer used.
    def prep_resize(self, context, image, request_spec, filter_properties,
                    instance, instance_type, reservations):
        """Tries to call schedule_prep_resize on the driver.
        Sets instance vm_state to ACTIVE on NoHostFound
        Sets vm_state to ERROR on other exceptions
        """
        instance_uuid = instance['uuid']
        with compute_utils.EventReporter(context, 'schedule', instance_uuid):
            try:
                request_spec['num_instances'] = len(
                        request_spec['instance_uuids'])
                hosts = self.driver.select_destinations(
                        context, request_spec, filter_properties)
                host_state = hosts[0]

                scheduler_utils.populate_filter_properties(filter_properties,
                                                           host_state)
                # context is not serializable
                filter_properties.pop('context', None)

                (host, node) = (host_state['host'], host_state['nodename'])
                attrs = ['metadata', 'system_metadata', 'info_cache',
                         'security_groups']
                inst_obj = objects.Instance._from_db_object(
                        context, objects.Instance(), instance,
                        expected_attrs=attrs)
                self.compute_rpcapi.prep_resize(
                    context, image, inst_obj, instance_type, host,
                    reservations, request_spec=request_spec,
                    filter_properties=filter_properties, node=node)

            except exception.NoValidHost as ex:
                vm_state = instance.get('vm_state', vm_states.ACTIVE)
                self._set_vm_state_and_notify('prep_resize',
                                             {'vm_state': vm_state,
                                              'task_state': None},
                                             context, ex, request_spec)
                if reservations:
                    QUOTAS.rollback(context, reservations)
            except Exception as ex:
                with excutils.save_and_reraise_exception():
                    self._set_vm_state_and_notify('prep_resize',
                                                 {'vm_state': vm_states.ERROR,
                                                  'task_state': None},
                                                 context, ex, request_spec)
                    if reservations:
                        QUOTAS.rollback(context, reservations)

    def _set_vm_state_and_notify(self, method, updates, context, ex,
                                 request_spec):
        scheduler_utils.set_vm_state_and_notify(
            context, 'scheduler', method, updates, ex, request_spec, self.db)

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
