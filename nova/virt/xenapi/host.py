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

import re

from os_xenapi.client import host_management
from os_xenapi.client import XenAPI
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils


from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import fields as obj_fields
from nova.virt.xenapi import pool_states
from nova.virt.xenapi import vm_utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class Host(object):
    """Implements host related operations."""
    def __init__(self, session, virtapi):
        self._session = session
        self._virtapi = virtapi

    def host_power_action(self, action):
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
                     self._session.host.get_all()
                     if host_ref != self._session.host_ref]
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
                            LOG.info('Instance %(name)s running on '
                                     '%(host)s could not be found in '
                                     'the database: assuming it is a '
                                     'worker VM and skip ping migration '
                                     'to a new host',
                                     {'name': name, 'host': host})
                            continue
                    instance = objects.Instance.get_by_uuid(ctxt, uuid)
                    vm_counter = vm_counter + 1

                    aggregate = objects.AggregateList.get_by_host(
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

                    self._session.VM.pool_migrate(vm_ref, host_ref,
                                                  {"live": "true"})
                    migrations_counter = migrations_counter + 1

                    instance.vm_state = vm_states.ACTIVE
                    instance.save()

                    break
                except XenAPI.Failure:
                    LOG.exception(_('Unable to migrate VM %(vm_ref)s '
                                    'from %(host)s'),
                                  {'vm_ref': vm_ref, 'host': host})
                    instance.host = host
                    instance.vm_state = vm_states.ACTIVE
                    instance.save()

        if vm_counter == migrations_counter:
            return 'on_maintenance'
        else:
            raise exception.NoValidHost(reason=_('Unable to find suitable '
                                                 'host for VMs evacuation'))

    def set_host_enabled(self, enabled):
        """Sets the compute host's ability to accept new instances."""
        # Since capabilities are gone, use service table to disable a node
        # in scheduler
        cntxt = context.get_admin_context()
        service = objects.Service.get_by_args(cntxt, CONF.host,
                                              'nova-compute')
        service.disabled = not enabled
        service.disabled_reason = 'set by xenapi host_state'
        service.save()

        response = _call_host_management(self._session,
                                         host_management.set_host_enabled,
                                         jsonutils.dumps(enabled))
        return response.get("status", response)

    def get_host_uptime(self):
        """Returns the result of calling "uptime" on the target host."""
        response = _call_host_management(self._session,
                                         host_management.get_host_uptime)
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

    def _get_passthrough_devices(self):
        """Get a list pci devices that are available for pci passthtough.

        We use a plugin to get the output of the lspci command runs on dom0.
        From this list we will extract pci devices that are using the pciback
        kernel driver.

        :returns: a list of pci devices on the node
        """
        def _compile_hex(pattern):
            r"""Return a compiled regular expression pattern into which we have
            replaced occurrences of hex by [\da-fA-F].
            """
            return re.compile(pattern.replace("hex", r"[\da-fA-F]"))

        def _parse_pci_device_string(dev_string):
            """Exctract information from the device string about the slot, the
            vendor and the product ID. The string is as follow:
                "Slot:\tBDF\nClass:\txxxx\nVendor:\txxxx\nDevice:\txxxx\n..."
            Return a dictionary with information about the device.
            """
            slot_regex = _compile_hex(r"Slot:\t"
                                      r"((?:hex{4}:)?"  # Domain: (optional)
                                      r"hex{2}:"        # Bus:
                                      r"hex{2}\."       # Device.
                                      r"hex{1})")       # Function
            vendor_regex = _compile_hex(r"\nVendor:\t(hex+)")
            product_regex = _compile_hex(r"\nDevice:\t(hex+)")

            slot_id = slot_regex.findall(dev_string)
            vendor_id = vendor_regex.findall(dev_string)
            product_id = product_regex.findall(dev_string)

            if not slot_id or not vendor_id or not product_id:
                raise exception.NovaException(
                    _("Failed to parse information about"
                      " a pci device for passthrough"))

            type_pci = host_management.get_pci_type(self._session, slot_id[0])

            return {'label': '_'.join(['label',
                                       vendor_id[0],
                                       product_id[0]]),
                    'vendor_id': vendor_id[0],
                    'product_id': product_id[0],
                    'address': slot_id[0],
                    'dev_id': '_'.join(['pci', slot_id[0]]),
                    'dev_type': type_pci,
                    'status': 'available'}

        # Devices are separated by a blank line. That is why we
        # use "\n\n" as separator.
        lspci_out = host_management.get_pci_device_details(self._session)

        pci_list = lspci_out.split("\n\n")

        # For each device of the list, check if it uses the pciback
        # kernel driver and if it does, get information and add it
        # to the list of passthrough_devices. Ignore it if the driver
        # is not pciback.
        passthrough_devices = []

        for dev_string_info in pci_list:
            if "Driver:\tpciback" in dev_string_info:
                new_dev = _parse_pci_device_string(dev_string_info)
                passthrough_devices.append(new_dev)

        return passthrough_devices

    def _get_vgpu_stats(self):
        """Invoke XenAPI to get the stats for VGPUs.

        The return value is a dict which has GPU groups' uuid as
        the keys:
            dict(grp_uuid_1=dict_vgpu_stats_in_grp_1,
                 grp_uuid_2=dict_vgpu_stats_in_grp_2,
                 ...,
                 grp_uuid_n=dict_vgpu_stats_in_grp_n)
        The `dict_vgpu_stats_in_grp_x` is a dict represents the
        vGPU stats in GPU group x. For details, please refer to
        the return value of the function of _get_vgpu_stats_in_group().
        """
        if not CONF.devices.enabled_vgpu_types:
            return {}

        vgpu_stats = {}

        # NOTE(jianghuaw): If there are multiple vGPU types enabled in
        # the configure option, we only choose the first one so that
        # we support only one vGPU type per compute node at the moment.
        # Once we switch to use the nested resource providers, we will
        # remove these lines to allow multiple vGPU types within multiple
        # GPU groups (each group has a different vGPU type enabled).
        if len(CONF.devices.enabled_vgpu_types) > 1:
            LOG.warning('XenAPI only supports one GPU type per compute node,'
                        ' only first type will be used.')
        cfg_enabled_types = CONF.devices.enabled_vgpu_types[:1]

        vgpu_grp_refs = self._session.call_xenapi('GPU_group.get_all')
        for ref in vgpu_grp_refs:
            grp_uuid = self._session.call_xenapi('GPU_group.get_uuid', ref)
            stat = self._get_vgpu_stats_in_group(ref, cfg_enabled_types)
            if stat:
                vgpu_stats[grp_uuid] = stat

        LOG.debug("Returning vGPU stats: %s", vgpu_stats)

        return vgpu_stats

    def _get_vgpu_stats_in_group(self, grp_ref, vgpu_types):
        """Get stats for the specified vGPU types in a GPU group.

        NOTE(Jianghuaw): In XenAPI, a GPU group is the minimal unit
        from where to create a vGPU for an instance. So here, we
        report vGPU resources for a particular GPU group. When we use
        nested resource providers to represent the vGPU resources,
        each GPU group will be a child resource provider under the
        compute node.

        The return value is a dict. For example:
        {'uuid': '6444c6ee-3a49-42f5-bebb-606b52175e67',
         'type_name': 'Intel GVT-g',
         'max_heads': 1,
         'total': 7,
         'remaining': 7,
         }
        """
        type_refs_in_grp = self._session.call_xenapi(
            'GPU_group.get_enabled_VGPU_types', grp_ref)

        type_names_in_grp = {self._session.call_xenapi(
                                 'VGPU_type.get_model_name',
                                 type_ref): type_ref
                             for type_ref in type_refs_in_grp}
        # Get the vGPU types enabled both in this GPU group and in the
        # nova conf.
        enabled_types = set(vgpu_types) & set(type_names_in_grp)
        if not enabled_types:
            return

        stat = {}
        # Get the sorted enabled types, so that we can always choose the same
        # type when there are multiple enabled vGPU types.
        sorted_types = sorted(enabled_types)
        chosen_type = sorted_types[0]
        if len(sorted_types) > 1:
            LOG.warning('XenAPI only supports one vGPU type per GPU group,'
                        ' but enabled multiple vGPU types: %(available)s.'
                        ' Choosing the first one: %(chosen)s.',
                       dict(available=sorted_types,
                            chosen=chosen_type))
        type_ref = type_names_in_grp[chosen_type]
        type_uuid = self._session.call_xenapi('VGPU_type.get_uuid', type_ref)
        stat['uuid'] = type_uuid
        stat['type_name'] = chosen_type
        stat['max_heads'] = int(self._session.call_xenapi(
            'VGPU_type.get_max_heads', type_ref))

        stat['total'] = self._get_total_vgpu_in_grp(grp_ref, type_ref)
        stat['remaining'] = int(self._session.call_xenapi(
                                    'GPU_group.get_remaining_capacity',
                                    grp_ref,
                                    type_ref))
        return stat

    def _get_total_vgpu_in_grp(self, grp_ref, type_ref):
        """Get the total capacity of vGPUs in the group."""
        pgpu_recs = self._session.call_xenapi(
            'PGPU.get_all_records_where', 'field "GPU_group" = "%s"' % grp_ref)

        total = 0
        for pgpu_ref in pgpu_recs:
            pgpu_rec = pgpu_recs[pgpu_ref]
            if type_ref in pgpu_rec['enabled_VGPU_types']:
                cap = pgpu_rec['supported_VGPU_max_capacities'][type_ref]
                total += int(cap)
        return total

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
        True, run the update first.
        """
        if refresh or not self._stats:
            self.update_status()
        return self._stats

    def get_disk_used(self, sr_ref):
        """Since glance images are downloaded and snapshotted before they are
        used, only a small proportion of its VDI will be in use and it will
        never grow.  We only need to count the virtual size for disks that
        are attached to a VM - every other disk can count physical.
        """

        def _vdi_attached(vdi_ref):
            try:
                vbds = self._session.VDI.get_VBDs(vdi_ref)
                for vbd in vbds:
                    if self._session.VBD.get_currently_attached(vbd):
                        return True
            except self._session.XenAPI.Failure:
                # VDI or VBD may no longer exist - in which case, it's
                # not attached
                pass
            return False

        allocated = 0
        physical_used = 0

        all_vdis = self._session.SR.get_VDIs(sr_ref)
        for vdi_ref in all_vdis:
            try:
                vdi_physical = \
                    int(self._session.VDI.get_physical_utilisation(vdi_ref))
                if _vdi_attached(vdi_ref):
                    allocated += \
                        int(self._session.VDI.get_virtual_size(vdi_ref))
                else:
                    allocated += vdi_physical
                physical_used += vdi_physical
            except (ValueError, self._session.XenAPI.Failure):
                LOG.exception(_('Unable to get size for vdi %s'), vdi_ref)

        return (allocated, physical_used)

    def update_status(self):
        """Since under Xenserver, a compute node runs on a given host,
        we can get host status information using xenapi.
        """
        LOG.debug("Updating host stats")
        data = _call_host_management(self._session,
                                     host_management.get_host_data)
        if data:
            sr_ref = vm_utils.scan_default_sr(self._session)
            sr_rec = self._session.SR.get_record(sr_ref)
            total = int(sr_rec["physical_size"])
            (allocated, used) = self.get_disk_used(sr_ref)
            data["disk_total"] = total
            data["disk_used"] = used
            data["disk_allocated"] = allocated
            data["disk_available"] = total - used
            data["supported_instances"] = to_supported_instances(
                data.get("host_capabilities")
            )
            data["cpu_model"] = to_cpu_model(
                data.get("host_cpu_info")
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
                LOG.error('Hostname has changed from %(old)s to %(new)s. '
                          'A restart is required to take effect.',
                          {'old': self._stats['host_hostname'],
                           'new': data['host_hostname']})
                data['host_hostname'] = self._stats['host_hostname']
            data['hypervisor_hostname'] = data['host_hostname']
            vcpus_used = 0
            for vm_ref, vm_rec in vm_utils.list_vms(self._session):
                vcpus_used = vcpus_used + int(vm_rec['VCPUs_max'])
            data['vcpus_used'] = vcpus_used
            data['pci_passthrough_devices'] = self._get_passthrough_devices()
            data['vgpu_stats'] = self._get_vgpu_stats()
            self._stats = data


def to_supported_instances(host_capabilities):
    if not host_capabilities:
        return []

    result = []
    for capability in host_capabilities:
        try:
            # 'capability'is unicode but we want arch/ostype
            # to be strings to match the standard constants
            capability = str(capability)

            ostype, _version, guestarch = capability.split("-")

            guestarch = obj_fields.Architecture.canonicalize(guestarch)
            ostype = obj_fields.VMMode.canonicalize(ostype)

            result.append((guestarch, obj_fields.HVType.XEN, ostype))
        except ValueError:
            LOG.warning("Failed to extract instance support from %s",
                        capability)

    return result


def to_cpu_model(host_cpu_info):
    # The XenAPI driver returns data in the format
    #
    # {"physical_features": "0098e3fd-bfebfbff-00000001-28100800",
    #  "modelname": "Intel(R) Xeon(R) CPU           X3430  @ 2.40GHz",
    #  "vendor": "GenuineIntel",
    #  "features": "0098e3fd-bfebfbff-00000001-28100800",
    #  "family": 6,
    #  "maskable": "full",
    #  "cpu_count": 4,
    #  "socket_count": "1",
    #  "flags": "fpu de tsc msr pae mce cx8 apic sep mtrr mca cmov
    #            pat clflush acpi mmx fxsr sse sse2 ss ht nx
    #            constant_tsc nonstop_tsc aperfmperf pni vmx est
    #            ssse3 sse4_1 sse4_2 popcnt hypervisor ida
    #            tpr_shadow vnmi flexpriority ept vpid",
    #  "stepping": 5,
    #  "model": 30,
    #  "features_after_reboot": "0098e3fd-bfebfbff-00000001-28100800",
    #  "speed": "2394.086"}

    if host_cpu_info is None:
        return None

    cpu_info = dict()
    # TODO(berrange) the data we're putting in model is not
    # exactly comparable to what libvirt puts in model. The
    # libvirt model names are a well defined short string
    # which is really an aliass for a particular set of
    # feature flags. The Xen model names are raw printable
    # strings from the kernel with no specific semantics
    cpu_info["model"] = host_cpu_info["modelname"]
    cpu_info["vendor"] = host_cpu_info["vendor"]
    # TODO(berrange) perhaps we could fill in 'arch' field too
    # by looking at 'host_capabilities' for the Xen host ?

    topology = dict()
    topology["sockets"] = int(host_cpu_info["socket_count"])
    topology["cores"] = (int(host_cpu_info["cpu_count"]) /
                         int(host_cpu_info["socket_count"]))
    # TODO(berrange): if 'ht' is present in the 'flags' list
    # is it possible to infer that the 'cpu_count' is in fact
    # sockets * cores * threads ? Unclear if 'ht' would remain
    # visible when threads are disabled in BIOS ?
    topology["threads"] = 1

    cpu_info["topology"] = topology

    cpu_info["features"] = host_cpu_info["flags"].split(" ")

    return cpu_info


def call_xenhost(session, method, arg_dict):
    """There will be several methods that will need this general
    handling for interacting with the xenhost plugin, so this abstracts
    out that behavior.
    """
    # Create a task ID as something that won't match any instance ID
    try:
        result = session.call_plugin('xenhost.py', method, args=arg_dict)
        if not result:
            return ''
        return jsonutils.loads(result)
    except ValueError:
        LOG.exception(_("Unable to get updated status"))
        return None
    except session.XenAPI.Failure as e:
        LOG.error("The call to %(method)s returned "
                  "an error: %(e)s.", {'method': method, 'e': e})
        return e.details[1]


def _call_host_management(session, method, *args):
    """There will be several methods that will need this general
    handling for interacting with the dom0 plugin, so this abstracts
    out that behavior. the call_xenhost will be removed once we deprecated
    those functions which are not needed anymore
    """
    try:
        result = method(session, *args)
        if not result:
            return ''
        return jsonutils.loads(result)
    except ValueError:
        LOG.exception(_("Unable to get updated status"))
        return None
    except session.XenAPI.Failure as e:
        LOG.error("The call to %(method)s returned an error: %(e)s.",
                  {'method': method.__name__, 'e': e})
        return e.details[1]


def _uuid_find(context, host, name_label):
    """Return instance uuid by name_label."""
    for i in objects.InstanceList.get_by_host(context, host):
        if i.name == name_label:
            return i.uuid
    return None


def _host_find(context, session, src_aggregate, host_ref):
    """Return the host from the xenapi host reference.

    :param src_aggregate: the aggregate that the compute host being put in
                          maintenance (source of VMs) belongs to
    :param host_ref: the hypervisor host reference (destination of VMs)

    :return: the compute host that manages host_ref
    """
    # NOTE: this would be a lot simpler if nova-compute stored
    # CONF.host in the XenServer host's other-config map.
    # TODO(armando-migliaccio): improve according the note above
    uuid = session.host.get_uuid(host_ref)
    for compute_host, host_uuid in src_aggregate.metadetails.items():
        if host_uuid == uuid:
            return compute_host
    raise exception.NoValidHost(reason='Host %(host_uuid)s could not be found '
                                'from aggregate metadata: %(metadata)s.' %
                                {'host_uuid': uuid,
                                 'metadata': src_aggregate.metadetails})
