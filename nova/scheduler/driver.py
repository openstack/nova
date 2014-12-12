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

import sys

from oslo.config import cfg
from oslo.utils import importutils
from oslo.utils import timeutils

from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova import db
from nova import exception
from nova.i18n import _, _LE, _LW
from nova import notifications
from nova.openstack.common import log as logging
from nova import rpc
from nova import servicegroup

LOG = logging.getLogger(__name__)

scheduler_driver_opts = [
    cfg.StrOpt('scheduler_host_manager',
               default='nova.scheduler.host_manager.HostManager',
               help='The scheduler host manager class to use'),
    ]

CONF = cfg.CONF
CONF.register_opts(scheduler_driver_opts)


def handle_schedule_error(context, ex, instance_uuid, request_spec):
    """On run_instance failure, update instance state and
    send notifications.
    """

    if isinstance(ex, exception.NoValidHost):
        LOG.warning(_LW("NoValidHost exception with message: \'%s\'"),
                    ex.format_message().strip(),
                    instance_uuid=instance_uuid)
    else:
        LOG.exception(_LE("Exception during scheduler.run_instance"))
    state = vm_states.ERROR.upper()
    LOG.warning(_LW('Setting instance to %s state.'), state,
                instance_uuid=instance_uuid)

    (old_ref, new_ref) = db.instance_update_and_get_original(context,
            instance_uuid, {'vm_state': vm_states.ERROR,
                            'task_state': None})
    notifications.send_update(context, old_ref, new_ref,
            service="scheduler")
    compute_utils.add_instance_fault_from_exc(context,
            new_ref, ex, sys.exc_info())

    properties = request_spec.get('instance_properties', {})
    payload = dict(request_spec=request_spec,
                   instance_properties=properties,
                   instance_id=instance_uuid,
                   state=vm_states.ERROR,
                   method='run_instance',
                   reason=ex)

    rpc.get_notifier('scheduler').error(context,
                                        'scheduler.run_instance', payload)


def instance_update_db(context, instance_uuid, extra_values=None):
    """Clear the host and node - set the scheduled_at field of an Instance.

    :returns: An Instance with the updated fields set properly.
    """
    now = timeutils.utcnow()
    values = {'host': None, 'node': None, 'scheduled_at': now}
    if extra_values:
        values.update(extra_values)

    return db.instance_update(context, instance_uuid, values)


class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    def __init__(self):
        self.host_manager = importutils.import_object(
                CONF.scheduler_host_manager)
        self.servicegroup_api = servicegroup.API()

    def run_periodic_tasks(self, context):
        """Manager calls this so drivers can perform periodic tasks."""
        pass

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = db.service_get_all_by_topic(context, topic)
        return [service['host']
                for service in services
                if self.servicegroup_api.service_is_up(service)]

    def select_destinations(self, context, request_spec, filter_properties):
        """Must override select_destinations method.

        :return: A list of dicts with 'host', 'nodename' and 'limits' as keys
            that satisfies the request_spec and filter_properties.
        """
        msg = _("Driver must implement select_destinations")
        raise NotImplementedError(msg)
