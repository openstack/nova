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

from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields


LOG = log.getLogger(__name__)


@obj_base.NovaObjectRegistry.register_if(False)
class LiveMigrateData(obj_base.NovaObject):
    fields = {
        'is_volume_backed': fields.BooleanField(),
        'migration': fields.ObjectField('Migration'),
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


@obj_base.NovaObjectRegistry.register
class LibvirtLiveMigrateBDMInfo(obj_base.NovaObject):
    VERSION = '1.0'

    fields = {
        # FIXME(danms): some of these can be enums?
        'serial': fields.StringField(),
        'bus': fields.StringField(),
        'dev': fields.StringField(),
        'type': fields.StringField(),
        'format': fields.StringField(nullable=True),
        'boot_index': fields.IntegerField(nullable=True),
        'connection_info_json': fields.StringField(),
    }

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
    VERSION = '1.0'

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
        'serial_listen_addr': fields.StringField(),
        'bdms': fields.ListOfObjectsField('LibvirtLiveMigrateBDMInfo'),
    }

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
        LOG.debug('Converting to legacy: %s' % self)
        legacy = super(LibvirtLiveMigrateData, self).to_legacy_dict()
        keys = (set(self.fields.keys()) -
                set(LiveMigrateData.fields.keys()) - {'bdms'})
        legacy.update({k: getattr(self, k) for k in keys
                       if self.obj_attr_is_set(k)})

        graphics_vnc = legacy.pop('graphics_listen_addr_vnc', None)
        graphics_spice = legacy.pop('graphics_listen_addr_spice', None)
        live_result = {
            'graphics_listen_addrs': {
                'vnc': graphics_vnc and str(graphics_vnc),
                'spice': graphics_spice and str(graphics_spice),
                },
            'serial_listen_addr': legacy.pop('serial_listen_addr', None),
        }

        if pre_migration_result:
            legacy['pre_live_migration_result'] = live_result
            self._bdms_to_legacy(live_result)

        LOG.debug('Legacy result: %s' % legacy)
        return legacy

    def from_legacy_dict(self, legacy):
        LOG.debug('Converting legacy dict to obj: %s' % legacy)
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
            if 'serial_listen_addr' in pre_result:
                self.serial_listen_addr = pre_result['serial_listen_addr']
            self._bdms_from_legacy(pre_result)
        LOG.debug('Converted object: %s' % self)
