# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Citrix Systems, Inc.
# Copyright 2010 OpenStack LLC.
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
Management class for host-related functions (start, reboot, etc).
"""

import logging
import json

from nova.compute import vm_states
from nova import context
from nova import db
from nova import exception
from nova.virt.xenapi import vm_utils

LOG = logging.getLogger(__name__)


class Host(object):
    """
    Implements host related operations.
    """
    def __init__(self, session):
        self.XenAPI = session.get_imported_xenapi()
        self._session = session

    def host_power_action(self, _host, action):
        """Reboots or shuts down the host."""
        args = {"action": json.dumps(action)}
        methods = {"reboot": "host_reboot", "shutdown": "host_shutdown"}
        response = call_xenhost(self._session, methods[action], args)
        return response.get("power_action", response)

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation."""
        if mode:
            host_list = [host_ref for host_ref in
                         self._session.call_xenapi('host.get_all') \
                         if host_ref != self._session.get_xenapi_host()]
            migrations_counter = vm_counter = 0
            ctxt = context.get_admin_context()
            for vm_ref, vm_rec in vm_utils.VMHelper.list_vms(self._session):
                for host_ref in host_list:
                    try:
                        # Ensure only guest instances are migrated
                        uuid = vm_rec['other_config'].get('nova_uuid')
                        if not uuid:
                            name = vm_rec['name_label']
                            uuid = _uuid_find(ctxt, host, name)
                            if not uuid:
                                msg = _('Instance %(name)s running on %(host)s'
                                        ' could not be found in the database:'
                                        ' assuming it is a worker VM and skip'
                                        'ping migration to a new host')
                                LOG.info(msg % locals())
                                continue
                        instance = db.instance_get_by_uuid(ctxt, uuid)
                        vm_counter = vm_counter + 1

                        dest = _host_find(ctxt, self._session, host, host_ref)
                        db.instance_update(ctxt, instance.id,
                                           {'host': dest,
                                            'vm_state': vm_states.MIGRATING})
                        self._session.call_xenapi('VM.pool_migrate',
                                                  vm_ref, host_ref, {})
                        migrations_counter = migrations_counter + 1
                        db.instance_update(ctxt, instance.id,
                                           {'vm_state': vm_states.ACTIVE})
                        break
                    except self.XenAPI.Failure:
                        LOG.exception('Unable to migrate VM %(vm_ref)s'
                                      'from %(host)s' % locals())
                        db.instance_update(ctxt, instance.id,
                                           {'host': host,
                                            'vm_state': vm_states.ACTIVE})
            if vm_counter == migrations_counter:
                return 'on_maintenance'
            else:
                raise exception.NoValidHost(reason='Unable to find suitable '
                                                   'host for VMs evacuation')
        else:
            return 'off_maintenance'

    def set_host_enabled(self, _host, enabled):
        """Sets the specified host's ability to accept new instances."""
        args = {"enabled": json.dumps(enabled)}
        response = call_xenhost(self._session, "set_host_enabled", args)
        return response.get("status", response)


class HostState(object):
    """Manages information about the XenServer host this compute
    node is running on.
    """
    def __init__(self, session):
        super(HostState, self).__init__()
        self._session = session
        self._stats = {}
        self.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
        True, run the update first.
        """
        if refresh:
            self.update_status()
        return self._stats

    def update_status(self):
        """Since under Xenserver, a compute node runs on a given host,
        we can get host status information using xenapi.
        """
        LOG.debug(_("Updating host stats"))
        data = call_xenhost(self._session, "host_data", {})
        if data:
            try:
                # Get the SR usage
                sr_ref = vm_utils.VMHelper.safe_find_sr(self._session)
            except exception.NotFound as e:
                # No SR configured
                LOG.error(_("Unable to get SR for this host: %s") % e)
                return
            sr_rec = self._session.call_xenapi("SR.get_record", sr_ref)
            total = int(sr_rec["virtual_allocation"])
            used = int(sr_rec["physical_utilisation"])
            data["disk_total"] = total
            data["disk_used"] = used
            data["disk_available"] = total - used
            host_memory = data.get('host_memory', None)
            if host_memory:
                data["host_memory_total"] = host_memory.get('total', 0)
                data["host_memory_overhead"] = host_memory.get('overhead', 0)
                data["host_memory_free"] = host_memory.get('free', 0)
                data["host_memory_free_computed"] = host_memory.get(
                                                    'free-computed', 0)
                del data['host_memory']
            self._stats = data


def call_xenhost(session, method, arg_dict):
    """There will be several methods that will need this general
    handling for interacting with the xenhost plugin, so this abstracts
    out that behavior.
    """
    # Create a task ID as something that won't match any instance ID
    XenAPI = session.get_imported_xenapi()
    try:
        result = session.call_plugin('xenhost', method, args=arg_dict)
        if not result:
            return ''
        return json.loads(result)
    except ValueError:
        LOG.exception(_("Unable to get updated status"))
        return None
    except XenAPI.Failure as e:
        LOG.error(_("The call to %(method)s returned "
                    "an error: %(e)s.") % locals())
        return e.details[1]


def _uuid_find(context, host, name_label):
    """Return instance uuid by name_label."""
    for i in db.instance_get_all_by_host(context, host):
        if i.name == name_label:
            return i['uuid']
    return None


def _host_find(context, session, src, dst):
    """Return the host from the xenapi host reference.

    :param src: the compute host being put in maintenance (source of VMs)
    :param dst: the hypervisor host reference (destination of VMs)

    :return: the compute host that manages dst
    """
    # NOTE: this would be a lot simpler if nova-compute stored
    # FLAGS.host in the XenServer host's other-config map.
    # TODO: improve according the note above
    aggregate = db.aggregate_get_by_host(context, src)
    uuid = session.call_xenapi('host.get_record', dst)['uuid']
    for compute_host, host_uuid in aggregate.metadetails.iteritems():
        if host_uuid == uuid:
            return compute_host
    raise exception.NoValidHost(reason='Host %(host_uuid)s could not be found '
                                'from aggregate metadata: %(metadata)s.' %
                                {'host_uuid': uuid,
                                 'metadata': aggregate.metadetails})
