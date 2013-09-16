# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Citrix Systems, Inc.
# Copyright 2010 OpenStack Foundation
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

from nova.compute import task_states
from nova.compute import vm_states
from nova import conductor
from nova import context
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.virt.xenapi import pool_states
from nova.virt.xenapi import vm_utils

LOG = logging.getLogger(__name__)


class Host(object):
    """
    Implements host related operations.
    """
    def __init__(self, session, virtapi):
        self._session = session
        self._virtapi = virtapi
        self._conductor_api = conductor.API()

    def host_power_action(self, _host, action):
        """Reboots or shuts down the host."""
        args = {"action": jsonutils.dumps(action)}
        methods = {"reboot": "host_reboot", "shutdown": "host_shutdown"}
        response = call_xenhost(self._session, methods[action], args)
        return response.get("power_action", response)

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation.
        """
        if not mode:
            return 'off_maintenance'
        host_list = [host_ref for host_ref in
                     self._session.call_xenapi('host.get_all')
                     if host_ref != self._session.get_xenapi_host()]
        migrations_counter = vm_counter = 0
        ctxt = context.get_admin_context()
        for vm_ref, vm_rec in vm_utils.list_vms(self._session):
            for host_ref in host_list:
                try:
                    # Ensure only guest instances are migrated
                    uuid = vm_rec['other_config'].get('nova_uuid')
                    if not uuid:
                        name = vm_rec['name_label']
                        uuid = _uuid_find(ctxt, host, name)
                        if not uuid:
                            LOG.info(_('Instance %(name)s running on %(host)s'
                                       ' could not be found in the database:'
                                       ' assuming it is a worker VM and skip'
                                       ' ping migration to a new host'),
                                     {'name': name, 'host': host})
                            continue
                    instance = instance_obj.Instance.get_by_uuid(ctxt, uuid)
                    vm_counter = vm_counter + 1

                    aggregate = self._virtapi.aggregate_get_by_host(
                        ctxt, host, key=pool_states.POOL_FLAG)
                    if not aggregate:
                        msg = _('Aggregate for host %(host)s count not be'
                                ' found.') % dict(host=host)
                        raise exception.NotFound(msg)

                    dest = _host_find(ctxt, self._session, aggregate[0],
                                      host_ref)
                    instance.host = dest
                    instance.task_state = task_states.MIGRATING
                    instance.save()

                    self._session.call_xenapi('VM.pool_migrate',
                                              vm_ref, host_ref,
                                              {"live": "true"})
                    migrations_counter = migrations_counter + 1

                    instance.vm_state = vm_states.ACTIVE
                    instance.save()

                    break
                except self._session.XenAPI.Failure:
                    LOG.exception(_('Unable to migrate VM %(vm_ref)s '
                                    'from %(host)s'),
                                  {'vm_ref': vm_ref, 'host': host})
                    instance.host = host
                    instance.vm_state = vm_states.ACTIVE
                    instance.save()

        if vm_counter == migrations_counter:
            return 'on_maintenance'
        else:
            raise exception.NoValidHost(reason='Unable to find suitable '
                                                   'host for VMs evacuation')

    def set_host_enabled(self, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        # Since capabilities are gone, use service table to disable a node
        # in scheduler
        status = {'disabled': not enabled,
                'disabled_reason': 'set by xenapi host_state'
                }
        cntxt = context.get_admin_context()
        service = self._conductor_api.service_get_by_args(
                cntxt,
                host,
                'nova-compute')
        self._conductor_api.service_update(
                cntxt,
                service,
                status)

        args = {"enabled": jsonutils.dumps(enabled)}
        response = call_xenhost(self._session, "set_host_enabled", args)
        return response.get("status", response)

    def get_host_uptime(self, _host):
        """Returns the result of calling "uptime" on the target host."""
        response = call_xenhost(self._session, "host_uptime", {})
        return response.get("uptime", response)


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
        if refresh or not self._stats:
            self.update_status()
        return self._stats

    def update_status(self):
        """Since under Xenserver, a compute node runs on a given host,
        we can get host status information using xenapi.
        """
        LOG.debug(_("Updating host stats"))
        data = call_xenhost(self._session, "host_data", {})
        if data:
            sr_ref = vm_utils.scan_default_sr(self._session)
            sr_rec = self._session.call_xenapi("SR.get_record", sr_ref)
            total = int(sr_rec["physical_size"])
            used = int(sr_rec["physical_utilisation"])
            data["disk_total"] = total
            data["disk_used"] = used
            data["disk_available"] = total - used
            data["supported_instances"] = to_supported_instances(
                data.get("host_capabilities")
            )
            host_memory = data.get('host_memory', None)
            if host_memory:
                data["host_memory_total"] = host_memory.get('total', 0)
                data["host_memory_overhead"] = host_memory.get('overhead', 0)
                data["host_memory_free"] = host_memory.get('free', 0)
                data["host_memory_free_computed"] = host_memory.get(
                                                    'free-computed', 0)
                del data['host_memory']
            if (data['host_hostname'] !=
                    self._stats.get('host_hostname', data['host_hostname'])):
                LOG.error(_('Hostname has changed from %(old)s '
                            'to %(new)s. A restart is required to take effect.'
                            ) % {'old': self._stats['host_hostname'],
                                 'new': data['host_hostname']})
                data['host_hostname'] = self._stats['host_hostname']
            data['hypervisor_hostname'] = data['host_hostname']
            self._stats = data


def to_supported_instances(host_capabilities):
    if not host_capabilities:
        return []

    result = []
    for capability in host_capabilities:
        try:
            ostype, _version, arch = capability.split("-")
            result.append((arch, 'xapi', ostype))
        except ValueError:
            LOG.warning(
                _("Failed to extract instance support from %s"), capability)

    return result


def call_xenhost(session, method, arg_dict):
    """There will be several methods that will need this general
    handling for interacting with the xenhost plugin, so this abstracts
    out that behavior.
    """
    # Create a task ID as something that won't match any instance ID
    try:
        result = session.call_plugin('xenhost', method, args=arg_dict)
        if not result:
            return ''
        return jsonutils.loads(result)
    except ValueError:
        LOG.exception(_("Unable to get updated status"))
        return None
    except session.XenAPI.Failure as e:
        LOG.error(_("The call to %(method)s returned "
                    "an error: %(e)s."), {'method': method, 'e': e})
        return e.details[1]


def _uuid_find(context, host, name_label):
    """Return instance uuid by name_label."""
    for i in instance_obj.InstanceList.get_by_host(context, host):
        if i.name == name_label:
            return i.uuid
    return None


def _host_find(context, session, src_aggregate, dst):
    """Return the host from the xenapi host reference.

    :param src_aggregate: the aggregate that the compute host being put in
                          maintenance (source of VMs) belongs to
    :param dst: the hypervisor host reference (destination of VMs)

    :return: the compute host that manages dst
    """
    # NOTE: this would be a lot simpler if nova-compute stored
    # CONF.host in the XenServer host's other-config map.
    # TODO(armando-migliaccio): improve according the note above
    uuid = session.call_xenapi('host.get_record', dst)['uuid']
    for compute_host, host_uuid in src_aggregate.metadetails.iteritems():
        if host_uuid == uuid:
            return compute_host
    raise exception.NoValidHost(reason='Host %(host_uuid)s could not be found '
                                'from aggregate metadata: %(metadata)s.' %
                                {'host_uuid': uuid,
                                 'metadata': src_aggregate.metadetails})
