#    Copyright 2015 Red Hat, Inc.
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

import copy

from oslo_log import log
from oslo_serialization import jsonutils
from oslo_utils import versionutils

from nova import exception
from nova.objects import base as obj_base
from nova.objects import fields


LOG = log.getLogger(__name__)


@obj_base.NovaObjectRegistry.register
class VIFMigrateData(obj_base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    # The majority of the fields here represent a port binding on the
    # **destination** host during a live migration. The vif_type, among
    # other fields, could be different from the existing binding on the
    # source host, which is represented by the "source_vif" field.
    fields = {
        'port_id': fields.StringField(),
        'vnic_type': fields.StringField(),  # TODO(sean-k-mooney): make enum?
        'vif_type': fields.StringField(),
        # vif_details is a dict whose contents are dependent on the vif_type
        # and can be any number of types for the values, so we just store it
        # as a serialized dict
        'vif_details_json': fields.StringField(),
        # profile is in the same random dict of terrible boat as vif_details
        # so it's stored as a serialized json string
        'profile_json': fields.StringField(),
        'host': fields.StringField(),
        # The source_vif attribute is a copy of the VIF network model
        # representation of the port on the source host which can be used
        # for filling in blanks about the VIF (port) when building a
        # configuration reference for the destination host.
        # NOTE(mriedem): This might not be sufficient based on how the
        # destination host is configured for all vif types. See the note in
        # the libvirt driver here: https://review.opendev.org/#/c/551370/
        # 29/nova/virt/libvirt/driver.py@7036
        'source_vif': fields.Field(fields.NetworkVIFModel()),
    }

    @property
    def vif_details(self):
        return jsonutils.loads(self.vif_details_json)

    @vif_details.setter
    def vif_details(self, vif_details_dict):
        self.vif_details_json = jsonutils.dumps(vif_details_dict)

    @property
    def profile(self):
        return jsonutils.loads(self.profile_json)

    @profile.setter
    def profile(self, profile_dict):
        self.profile_json = jsonutils.dumps(profile_dict)

    def get_dest_vif(self):
        """Get a destination VIF representation of this object.

        This method takes the source_vif and updates it to include the
        destination host port binding information using the other fields
        on this object.

        :return: nova.network.model.VIF object
        """
        if 'source_vif' not in self:
            raise exception.ObjectActionError(
                action='get_dest_vif', reason='source_vif is not set')
        vif = copy.deepcopy(self.source_vif)
        vif['type'] = self.vif_type
        vif['vnic_type'] = self.vnic_type
        vif['profile'] = self.profile
        vif['details'] = self.vif_details
        return vif

    @classmethod
    def create_skeleton_migrate_vifs(cls, vifs):
        """Create migrate vifs for live migration.

        :param vifs: a list of VIFs.
        :return: list of VIFMigrateData object corresponding to the provided
                 VIFs.
        """
        vif_mig_data = []

        for vif in vifs:
            mig_vif = cls(port_id=vif['id'], source_vif=vif)
            vif_mig_data.append(mig_vif)
        return vif_mig_data


@obj_base.NovaObjectRegistry.register
class LibvirtLiveMigrateNUMAInfo(obj_base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        # NOTE(artom) We need a 1:many cardinality here, so DictOfIntegers with
        # its 1:1 cardinality cannot work here. cpu_pins can have a single
        # guest CPU pinned to multiple host CPUs.
        'cpu_pins': fields.DictOfSetOfIntegersField(),
        # NOTE(artom) Currently we never pin a guest cell to more than a single
        # host cell, so cell_pins could be a DictOfIntegers, but
        # DictOfSetOfIntegers is more future-proof.
        'cell_pins': fields.DictOfSetOfIntegersField(),
        'emulator_pins': fields.SetOfIntegersField(),
        'sched_vcpus': fields.SetOfIntegersField(),
        'sched_priority': fields.IntegerField(),
    }


@obj_base.NovaObjectRegistry.register_if(False)
class LiveMigrateData(obj_base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added old_vol_attachment_ids field.
    # Version 1.2: Added wait_for_vif_plugged
    # Version 1.3: Added vifs field.
    VERSION = '1.3'

    fields = {
        'is_volume_backed': fields.BooleanField(),
        'migration': fields.ObjectField('Migration'),
        # old_vol_attachment_ids is a dict used to store the old attachment_ids
        # for each volume so they can be restored on a migration rollback. The
        # key is the volume_id, and the value is the attachment_id.
        # TODO(mdbooth): This field was made redundant by change Ibe9215c0. We
        # should eventually remove it.
        'old_vol_attachment_ids': fields.DictOfStringsField(),
        # wait_for_vif_plugged is set in pre_live_migration on the destination
        # compute host based on the [compute]/live_migration_wait_for_vif_plug
        # config option value; a default value is not set here since the
        # default for the config option may change in the future
        'wait_for_vif_plugged': fields.BooleanField(),
        'vifs': fields.ListOfObjectsField('VIFMigrateData'),
    }


@obj_base.NovaObjectRegistry.register
class LibvirtLiveMigrateBDMInfo(obj_base.NovaObject):
    # VERSION 1.0 : Initial version
    # VERSION 1.1 : Added encryption_secret_uuid for tracking volume secret
    #               uuid created on dest during migration with encrypted vols.
    VERSION = '1.1'

    fields = {
        # FIXME(danms): some of these can be enums?
        'serial': fields.StringField(),
        'bus': fields.StringField(),
        'dev': fields.StringField(),
        'type': fields.StringField(),
        'format': fields.StringField(nullable=True),
        'boot_index': fields.IntegerField(nullable=True),
        'connection_info_json': fields.StringField(),
        'encryption_secret_uuid': fields.UUIDField(nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(LibvirtLiveMigrateBDMInfo, self).obj_make_compatible(
            primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'encryption_secret_uuid' in primitive:
            del primitive['encryption_secret_uuid']

    # NOTE(danms): We don't have a connection_info object right
    # now, and instead mostly store/pass it as JSON that we're
    # careful with. When we get a connection_info object in the
    # future, we should use it here, so make this easy to convert
    # for later.
    @property
    def connection_info(self):
        return jsonutils.loads(self.connection_info_json)

    @connection_info.setter
    def connection_info(self, info):
        self.connection_info_json = jsonutils.dumps(info)

    def as_disk_info(self):
        info_dict = {
            'dev': self.dev,
            'bus': self.bus,
            'type': self.type,
        }
        if self.obj_attr_is_set('format') and self.format:
            info_dict['format'] = self.format
        if self.obj_attr_is_set('boot_index') and self.boot_index is not None:
            info_dict['boot_index'] = str(self.boot_index)
        return info_dict


@obj_base.NovaObjectRegistry.register
class LibvirtLiveMigrateData(LiveMigrateData):
    # Version 1.0: Initial version
    # Version 1.1: Added target_connect_addr
    # Version 1.2: Added 'serial_listen_ports' to allow live migration with
    #              serial console.
    # Version 1.3: Added 'supported_perf_events'
    # Version 1.4: Added old_vol_attachment_ids
    # Version 1.5: Added src_supports_native_luks
    # Version 1.6: Added wait_for_vif_plugged
    # Version 1.7: Added dst_wants_file_backed_memory
    # Version 1.8: Added file_backed_memory_discard
    # Version 1.9: Inherited vifs from LiveMigrateData
    # Version 1.10: Added dst_numa_info, src_supports_numa_live_migration, and
    #               dst_supports_numa_live_migration fields
    VERSION = '1.10'

    fields = {
        'filename': fields.StringField(),
        # FIXME: image_type should be enum?
        'image_type': fields.StringField(),
        'block_migration': fields.BooleanField(),
        'disk_over_commit': fields.BooleanField(),
        'disk_available_mb': fields.IntegerField(nullable=True),
        'is_shared_instance_path': fields.BooleanField(),
        'is_shared_block_storage': fields.BooleanField(),
        'instance_relative_path': fields.StringField(),
        'graphics_listen_addr_vnc': fields.IPAddressField(nullable=True),
        'graphics_listen_addr_spice': fields.IPAddressField(nullable=True),
        'serial_listen_addr': fields.StringField(nullable=True),
        'serial_listen_ports': fields.ListOfIntegersField(),
        'bdms': fields.ListOfObjectsField('LibvirtLiveMigrateBDMInfo'),
        'target_connect_addr': fields.StringField(nullable=True),
        'supported_perf_events': fields.ListOfStringsField(),
        'src_supports_native_luks': fields.BooleanField(),
        'dst_wants_file_backed_memory': fields.BooleanField(),
        # file_backed_memory_discard is ignored unless
        # dst_wants_file_backed_memory is set
        'file_backed_memory_discard': fields.BooleanField(),
        # TODO(artom) (src|dst)_supports_numa_live_migration are only used as
        # flags to indicate that the compute host is new enough to perform a
        # NUMA-aware live migration. Remove in version 2.0.
        'src_supports_numa_live_migration': fields.BooleanField(),
        'dst_supports_numa_live_migration': fields.BooleanField(),
        'dst_numa_info': fields.ObjectField('LibvirtLiveMigrateNUMAInfo'),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(LibvirtLiveMigrateData, self).obj_make_compatible(
            primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if (target_version < (1, 10) and
                'src_supports_numa_live_migration' in primitive):
            del primitive['src_supports_numa_live_migration']
        if target_version < (1, 10) and 'dst_numa_info' in primitive:
            del primitive['dst_numa_info']
        if target_version < (1, 9) and 'vifs' in primitive:
            del primitive['vifs']
        if target_version < (1, 8):
            if 'file_backed_memory_discard' in primitive:
                del primitive['file_backed_memory_discard']
        if target_version < (1, 7):
            if 'dst_wants_file_backed_memory' in primitive:
                del primitive['dst_wants_file_backed_memory']
        if target_version < (1, 6) and 'wait_for_vif_plugged' in primitive:
            del primitive['wait_for_vif_plugged']
        if target_version < (1, 5):
            if 'src_supports_native_luks' in primitive:
                del primitive['src_supports_native_luks']
        if target_version < (1, 4):
            if 'old_vol_attachment_ids' in primitive:
                del primitive['old_vol_attachment_ids']
        if target_version < (1, 3):
            if 'supported_perf_events' in primitive:
                del primitive['supported_perf_events']
        if target_version < (1, 2):
            if 'serial_listen_ports' in primitive:
                del primitive['serial_listen_ports']
        if target_version < (1, 1) and 'target_connect_addr' in primitive:
            del primitive['target_connect_addr']

    def is_on_shared_storage(self):
        return self.is_shared_block_storage or self.is_shared_instance_path


@obj_base.NovaObjectRegistry.register
class XenapiLiveMigrateData(LiveMigrateData):
    # Version 1.0: Initial version
    # Version 1.1: Added vif_uuid_map
    # Version 1.2: Added old_vol_attachment_ids
    # Version 1.3: Added wait_for_vif_plugged
    # Version 1.4: Inherited vifs from LiveMigrateData
    VERSION = '1.4'

    fields = {
        'block_migration': fields.BooleanField(nullable=True),
        'destination_sr_ref': fields.StringField(nullable=True),
        'migrate_send_data': fields.DictOfStringsField(nullable=True),
        'sr_uuid_map': fields.DictOfStringsField(),
        'kernel_file': fields.StringField(),
        'ramdisk_file': fields.StringField(),
        'vif_uuid_map': fields.DictOfStringsField(),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(XenapiLiveMigrateData, self).obj_make_compatible(
            primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 4) and 'vifs' in primitive:
            del primitive['vifs']
        if target_version < (1, 3) and 'wait_for_vif_plugged' in primitive:
            del primitive['wait_for_vif_plugged']
        if target_version < (1, 2):
            if 'old_vol_attachment_ids' in primitive:
                del primitive['old_vol_attachment_ids']
        if target_version < (1, 1):
            if 'vif_uuid_map' in primitive:
                del primitive['vif_uuid_map']


@obj_base.NovaObjectRegistry.register
class HyperVLiveMigrateData(LiveMigrateData):
    # Version 1.0: Initial version
    # Version 1.1: Added is_shared_instance_path
    # Version 1.2: Added old_vol_attachment_ids
    # Version 1.3: Added wait_for_vif_plugged
    # Version 1.4: Inherited vifs from LiveMigrateData
    VERSION = '1.4'

    fields = {'is_shared_instance_path': fields.BooleanField()}

    def obj_make_compatible(self, primitive, target_version):
        super(HyperVLiveMigrateData, self).obj_make_compatible(
            primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 4) and 'vifs' in primitive:
            del primitive['vifs']
        if target_version < (1, 3) and 'wait_for_vif_plugged' in primitive:
            del primitive['wait_for_vif_plugged']
        if target_version < (1, 2):
            if 'old_vol_attachment_ids' in primitive:
                del primitive['old_vol_attachment_ids']
        if target_version < (1, 1):
            if 'is_shared_instance_path' in primitive:
                del primitive['is_shared_instance_path']


@obj_base.NovaObjectRegistry.register
class PowerVMLiveMigrateData(LiveMigrateData):
    # Version 1.0: Initial version
    # Version 1.1: Added the Virtual Ethernet Adapter VLAN mappings.
    # Version 1.2: Added old_vol_attachment_ids
    # Version 1.3: Added wait_for_vif_plugged
    # Version 1.4: Inherited vifs from LiveMigrateData
    VERSION = '1.4'

    fields = {
        'host_mig_data': fields.DictOfNullableStringsField(),
        'dest_ip': fields.StringField(),
        'dest_user_id': fields.StringField(),
        'dest_sys_name': fields.StringField(),
        'public_key': fields.StringField(),
        'dest_proc_compat': fields.StringField(),
        'vol_data': fields.DictOfNullableStringsField(),
        'vea_vlan_mappings': fields.DictOfNullableStringsField(),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(PowerVMLiveMigrateData, self).obj_make_compatible(
            primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 4) and 'vifs' in primitive:
            del primitive['vifs']
        if target_version < (1, 3) and 'wait_for_vif_plugged' in primitive:
            del primitive['wait_for_vif_plugged']
        if target_version < (1, 2):
            if 'old_vol_attachment_ids' in primitive:
                del primitive['old_vol_attachment_ids']
        if target_version < (1, 1):
            if 'vea_vlan_mappings' in primitive:
                del primitive['vea_vlan_mappings']


@obj_base.NovaObjectRegistry.register
class VMwareLiveMigrateData(LiveMigrateData):
    VERSION = '1.0'

    fields = {
        'cluster_name': fields.StringField(nullable=False),
        'datastore_regex': fields.StringField(nullable=False),
    }
