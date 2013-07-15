# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor import api as conductor_api
from nova import db
from nova import exception
from nova import notifications
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier
from nova.openstack.common import timeutils
from nova import servicegroup

LOG = logging.getLogger(__name__)

scheduler_driver_opts = [
    cfg.StrOpt('scheduler_host_manager',
               default='nova.scheduler.host_manager.HostManager',
               help='The scheduler host manager class to use'),
    cfg.IntOpt('scheduler_max_attempts',
               default=3,
               help='Maximum number of attempts to schedule an instance'),
    ]

CONF = cfg.CONF
CONF.register_opts(scheduler_driver_opts)


def handle_schedule_error(context, ex, instance_uuid, request_spec):
    if not isinstance(ex, exception.NoValidHost):
        LOG.exception(_("Exception during scheduler.run_instance"))
    state = vm_states.ERROR.upper()
    LOG.warning(_('Setting instance to %s state.'), state,
                instance_uuid=instance_uuid)

    # update instance state and notify on the transition
    (old_ref, new_ref) = db.instance_update_and_get_original(context,
            instance_uuid, {'vm_state': vm_states.ERROR,
                            'task_state': None})
    notifications.send_update(context, old_ref, new_ref,
            service="scheduler")
    compute_utils.add_instance_fault_from_exc(context,
            conductor_api.LocalAPI(),
            new_ref, ex, sys.exc_info())

    properties = request_spec.get('instance_properties', {})
    payload = dict(request_spec=request_spec,
                   instance_properties=properties,
                   instance_id=instance_uuid,
                   state=vm_states.ERROR,
                   method='run_instance',
                   reason=ex)

    notifier.notify(context, notifier.publisher_id("scheduler"),
                    'scheduler.run_instance', notifier.ERROR, payload)


def instance_update_db(context, instance_uuid, extra_values=None):
    '''Clear the host and node - set the scheduled_at field of an Instance.

    :returns: An Instance with the updated fields set properly.
    '''
    now = timeutils.utcnow()
    values = {'host': None, 'node': None, 'scheduled_at': now}
    if extra_values:
        values.update(extra_values)

    return db.instance_update(context, instance_uuid, values)


def encode_instance(instance, local=True):
    """Encode locally created instance for return via RPC."""
    # TODO(comstud): I would love to be able to return the full
    # instance information here, but we'll need some modifications
    # to the RPC code to handle datetime conversions with the
    # json encoding/decoding.  We should be able to set a default
    # json handler somehow to do it.
    #
    # For now, I'll just return the instance ID and let the caller
    # do a DB lookup :-/
    if local:
        return dict(id=instance['id'], _is_precooked=False)
    else:
        inst = dict(instance)
        inst['_is_precooked'] = True
        return inst


class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    def __init__(self):
        self.host_manager = importutils.import_object(
                CONF.scheduler_host_manager)
        self.servicegroup_api = servicegroup.API()

    def update_service_capabilities(self, service_name, host, capabilities):
        """Process a capability update from a service node."""
        self.host_manager.update_service_capabilities(service_name,
                host, capabilities)

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = db.service_get_all_by_topic(context, topic)
        return [service['host']
                for service in services
                if self.servicegroup_api.service_is_up(service)]

    def group_hosts(self, context, group):
        """Return the list of hosts that have VM's from the group."""

        # The system_metadata 'group' will be filtered
        members = db.instance_get_all_by_filters(context,
                {'deleted': False, 'group': group})
        return [member['host']
                for member in members
                if member.get('host') is not None]

    def schedule_run_instance(self, context, request_spec,
                              admin_password, injected_files,
                              requested_networks, is_first_time,
                              filter_properties, legacy_bdm_in_spec):
        """Must override schedule_run_instance method for scheduler to work."""
        msg = _("Driver must implement schedule_run_instance")
        raise NotImplementedError(msg)

    def select_destinations(self, context, request_spec, filter_properties):
        """Must override select_destinations method.

        :return: A list of dicts with 'host', 'nodename' and 'limits' as keys
            that satisifies the request_spec and filter_properties.
        """
        msg = _("Driver must implement select_destinations")
        raise NotImplementedError(msg)

    def select_hosts(self, context, request_spec, filter_properties):
        """Must override select_hosts method for scheduler to work."""
        msg = _("Driver must implement select_hosts")
        raise NotImplementedError(msg)
