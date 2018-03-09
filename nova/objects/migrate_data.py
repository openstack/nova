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

from oslo_log import log
from oslo_serialization import jsonutils
from oslo_utils import versionutils

from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields


LOG = log.getLogger(__name__)


@obj_base.NovaObjectRegistry.register_if(False)
class LiveMigrateData(obj_base.NovaObject):
    fields = {
        'is_volume_backed': fields.BooleanField(),
        'migration': fields.ObjectField('Migration'),
        # old_vol_attachment_ids is a dict used to store the old attachment_ids
        # for each volume so they can be restored on a migration rollback. The
        # key is the volume_id, and the value is the attachment_id.
        # TODO(mdbooth): This field was made redundant by change I0390c9ff. We
        # should eventually remove it.
        'old_vol_attachment_ids': fields.DictOfStringsField(),
    }

    def to_legacy_dict(self, pre_migration_result=False):
        legacy = {}
        if self.obj_attr_is_set('is_volume_backed'):
            legacy['is_volume_backed'] = self.is_volume_backed
        if self.obj_attr_is_set('migration'):
            legacy['migration'] = self.migration
        if pre_migration_result:
            legacy['pre_live_migration_result'] = {}

        return legacy

    def from_legacy_dict(self, legacy):
        if 'is_volume_backed' in legacy:
            self.is_volume_backed = legacy['is_volume_backed']
        if 'migration' in legacy:
            self.migration = legacy['migration']

    @classmethod
    def detect_implementation(cls, legacy_dict):
        if 'instance_relative_path' in legacy_dict:
            obj = LibvirtLiveMigrateData()
        elif 'image_type' in legacy_dict:
            obj = LibvirtLiveMigrateData()
        elif 'migrate_data' in legacy_dict:
            obj = XenapiLiveMigrateData()
        else:
            obj = LiveMigrateData()
        obj.from_legacy_dict(legacy_dict)
        return obj


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
    VERSION = '1.5'

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
    }

    def obj_make_compatible(self, primitive, target_version):
        super(LibvirtLiveMigrateData, self).obj_make_compatible(
            primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
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

    def _bdms_to_legacy(self, legacy):
        if not self.obj_attr_is_set('bdms'):
            return
        legacy['volume'] = {}
        for bdmi in self.bdms:
            legacy['volume'][bdmi.serial] = {
                'disk_info': bdmi.as_disk_info(),
                'connection_info': bdmi.connection_info}

    def _bdms_from_legacy(self, legacy_pre_result):
        self.bdms = []
        volume = legacy_pre_result.get('volume', {})
        for serial in volume:
            vol = volume[serial]
            bdmi = objects.LibvirtLiveMigrateBDMInfo(serial=serial)
            bdmi.connection_info = vol['connection_info']
            bdmi.bus = vol['disk_info']['bus']
            bdmi.dev = vol['disk_info']['dev']
            bdmi.type = vol['disk_info']['type']
            if 'format' in vol:
                bdmi.format = vol['disk_info']['format']
            if 'boot_index' in vol:
                bdmi.boot_index = int(vol['disk_info']['boot_index'])
            self.bdms.append(bdmi)

    def to_legacy_dict(self, pre_migration_result=False):
        LOG.debug('Converting to legacy: %s', self)
        legacy = super(LibvirtLiveMigrateData, self).to_legacy_dict()
        keys = (set(self.fields.keys()) -
                set(LiveMigrateData.fields.keys()) - {'bdms'})
        legacy.update({k: getattr(self, k) for k in keys
                       if self.obj_attr_is_set(k)})

        graphics_vnc = legacy.pop('graphics_listen_addr_vnc', None)
        graphics_spice = legacy.pop('graphics_listen_addr_spice', None)
        transport_target = legacy.pop('target_connect_addr', None)
        live_result = {
            'graphics_listen_addrs': {
                'vnc': graphics_vnc and str(graphics_vnc),
                'spice': graphics_spice and str(graphics_spice),
                },
            'serial_listen_addr': legacy.pop('serial_listen_addr', None),
            'target_connect_addr': transport_target,
        }

        if pre_migration_result:
            legacy['pre_live_migration_result'] = live_result
            self._bdms_to_legacy(live_result)

        LOG.debug('Legacy result: %s', legacy)
        return legacy

    def from_legacy_dict(self, legacy):
        LOG.debug('Converting legacy dict to obj: %s', legacy)
        super(LibvirtLiveMigrateData, self).from_legacy_dict(legacy)
        keys = set(self.fields.keys()) - set(LiveMigrateData.fields.keys())
        for k in keys - {'bdms'}:
            if k in legacy:
                setattr(self, k, legacy[k])
        if 'pre_live_migration_result' in legacy:
            pre_result = legacy['pre_live_migration_result']
            self.graphics_listen_addr_vnc = \
                pre_result['graphics_listen_addrs'].get('vnc')
            self.graphics_listen_addr_spice = \
                pre_result['graphics_listen_addrs'].get('spice')
            self.target_connect_addr = pre_result.get('target_connect_addr')
            if 'serial_listen_addr' in pre_result:
                self.serial_listen_addr = pre_result['serial_listen_addr']
            self._bdms_from_legacy(pre_result)
        LOG.debug('Converted object: %s', self)

    def is_on_shared_storage(self):
        return self.is_shared_block_storage or self.is_shared_instance_path


@obj_base.NovaObjectRegistry.register
class XenapiLiveMigrateData(LiveMigrateData):
    # Version 1.0: Initial version
    # Version 1.1: Added vif_uuid_map
    # Version 1.2: Added old_vol_attachment_ids
    VERSION = '1.2'

    fields = {
        'block_migration': fields.BooleanField(nullable=True),
        'destination_sr_ref': fields.StringField(nullable=True),
        'migrate_send_data': fields.DictOfStringsField(nullable=True),
        'sr_uuid_map': fields.DictOfStringsField(),
        'kernel_file': fields.StringField(),
        'ramdisk_file': fields.StringField(),
        'vif_uuid_map': fields.DictOfStringsField(),
    }

    def to_legacy_dict(self, pre_migration_result=False):
        legacy = super(XenapiLiveMigrateData, self).to_legacy_dict()
        if self.obj_attr_is_set('block_migration'):
            legacy['block_migration'] = self.block_migration
        if self.obj_attr_is_set('migrate_send_data'):
            legacy['migrate_data'] = {
                'migrate_send_data': self.migrate_send_data,
                'destination_sr_ref': self.destination_sr_ref,
            }
        live_result = {
            'sr_uuid_map': ('sr_uuid_map' in self and self.sr_uuid_map
                            or {}),
            'vif_uuid_map': ('vif_uuid_map' in self and self.vif_uuid_map
                             or {}),
        }
        if pre_migration_result:
            legacy['pre_live_migration_result'] = live_result
        return legacy

    def from_legacy_dict(self, legacy):
        super(XenapiLiveMigrateData, self).from_legacy_dict(legacy)
        if 'block_migration' in legacy:
            self.block_migration = legacy['block_migration']
        else:
            self.block_migration = False
        if 'migrate_data' in legacy:
            self.migrate_send_data = \
                legacy['migrate_data']['migrate_send_data']
            self.destination_sr_ref = \
                legacy['migrate_data']['destination_sr_ref']
        if 'pre_live_migration_result' in legacy:
            self.sr_uuid_map = \
                legacy['pre_live_migration_result']['sr_uuid_map']
            self.vif_uuid_map = \
                legacy['pre_live_migration_result'].get('vif_uuid_map', {})

    def obj_make_compatible(self, primitive, target_version):
        super(XenapiLiveMigrateData, self).obj_make_compatible(
            primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
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
    VERSION = '1.2'

    fields = {'is_shared_instance_path': fields.BooleanField()}

    def obj_make_compatible(self, primitive, target_version):
        super(HyperVLiveMigrateData, self).obj_make_compatible(
            primitive, target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 2):
            if 'old_vol_attachment_ids' in primitive:
                del primitive['old_vol_attachment_ids']
        if target_version < (1, 1):
            if 'is_shared_instance_path' in primitive:
                del primitive['is_shared_instance_path']

    def to_legacy_dict(self, pre_migration_result=False):
        legacy = super(HyperVLiveMigrateData, self).to_legacy_dict()
        if self.obj_attr_is_set('is_shared_instance_path'):
            legacy['is_shared_instance_path'] = self.is_shared_instance_path

        return legacy

    def from_legacy_dict(self, legacy):
        super(HyperVLiveMigrateData, self).from_legacy_dict(legacy)
        if 'is_shared_instance_path' in legacy:
            self.is_shared_instance_path = legacy['is_shared_instance_path']


@obj_base.NovaObjectRegistry.register
class PowerVMLiveMigrateData(LiveMigrateData):
    # Version 1.0: Initial version
    # Version 1.1: Added the Virtual Ethernet Adapter VLAN mappings.
    # Version 1.2: Added old_vol_attachment_ids
    VERSION = '1.2'

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
        if target_version < (1, 2):
            if 'old_vol_attachment_ids' in primitive:
                del primitive['old_vol_attachment_ids']
        if target_version < (1, 1):
            if 'vea_vlan_mappings' in primitive:
                del primitive['vea_vlan_mappings']

    def to_legacy_dict(self, pre_migration_result=False):
        legacy = super(PowerVMLiveMigrateData, self).to_legacy_dict()
        for field in self.fields:
            if self.obj_attr_is_set(field):
                legacy[field] = getattr(self, field)
        return legacy

    def from_legacy_dict(self, legacy):
        super(PowerVMLiveMigrateData, self).from_legacy_dict(legacy)
        for field in self.fields:
            if field in legacy:
                setattr(self, field, legacy[field])
