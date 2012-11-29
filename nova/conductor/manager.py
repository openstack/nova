#    Copyright 2012 IBM Corp.
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

"""Handles database requests from other nova services"""

from nova import manager
from nova import notifications
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils


LOG = logging.getLogger(__name__)

# Instead of having a huge list of arguments to instance_update(), we just
# accept a dict of fields to update and use this whitelist to validate it.
allowed_updates = ['task_state', 'vm_state', 'expected_task_state',
                   'power_state', 'access_ip_v4', 'access_ip_v6',
                   'launched_at', 'terminated_at', 'host', 'node',
                   'memory_mb', 'vcpus', 'root_gb', 'ephemeral_gb',
                   'instance_type_id', 'root_device_name', 'host',
                   'progress', 'vm_mode', 'default_ephemeral_device',
                   'default_swap_device', 'root_device_name',
                   ]

# Fields that we want to convert back into a datetime object.
datetime_fields = ['launched_at', 'terminated_at']


class ConductorManager(manager.SchedulerDependentManager):
    """Mission: TBD"""

    RPC_API_VERSION = '1.1'

    def __init__(self, *args, **kwargs):
        super(ConductorManager, self).__init__(service_name='conductor',
                                               *args, **kwargs)

    def instance_update(self, context, instance_uuid, updates):
        for key, value in updates.iteritems():
            if key not in allowed_updates:
                LOG.error(_("Instance update attempted for "
                            "'%(key)s' on %(instance_uuid)s") % locals())
                raise KeyError("unexpected update keyword '%s'" % key)
            if key in datetime_fields and isinstance(value, basestring):
                updates[key] = timeutils.parse_strtime(value)

        old_ref, instance_ref = self.db.instance_update_and_get_original(
            context, instance_uuid, updates)
        notifications.send_update(context, old_ref, instance_ref)
        return jsonutils.to_primitive(instance_ref)

    def migration_update(self, context, migration, status):
        migration_ref = self.db.migration_update(context.elevated(),
                                                 migration['id'],
                                                 {'status': status})
        return jsonutils.to_primitive(migration_ref)
