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

import functools
import operator

from nova import block_device
from nova.objects import block_device as block_device_obj
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common.gettextutils import _LI
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.volume import encryptors

LOG = logging.getLogger(__name__)


class _NotTransformable(Exception):
    pass


class _InvalidType(_NotTransformable):
    pass


class _NoLegacy(Exception):
    pass


def update_db(method):
    @functools.wraps(method)
    def wrapped(obj, context, *args, **kwargs):
        ret_val = method(obj, context, *args, **kwargs)
        obj.save(context)
        return ret_val
    return wrapped


class DriverBlockDevice(dict):
    """A dict subclass that represents block devices used by the virt layer.

    Uses block device objects internally to do the database access.

    _fields and _legacy_fields class attributes present a set of fields that
    are expected on a certain DriverBlockDevice type. We may have more legacy
    versions in the future.

    If an attribute access is attempted for a name that is found in the
    _proxy_as_attr set, it will be proxied to the underlying object. This
    allows us to access stuff that is not part of the data model that all
    drivers understand.

    The save() method allows us to update the database using the underlying
    object. _update_on_save class attribute dictionary keeps the following
    mapping:

        {'object field name': 'driver dict field name (or None if same)'}

    These fields will be updated on the internal object, from the values in the
    dict, before the actual database update is done.
    """

    _fields = set()
    _legacy_fields = set()

    _proxy_as_attr = set()
    _update_on_save = {'disk_bus': None,
                       'device_name': None,
                       'device_type': None}

    def __init__(self, bdm):
        # TODO(ndipanov): Remove this check when we have all the rpc methods
        # use objects for block devices.
        if isinstance(bdm, block_device_obj.BlockDeviceMapping):
            self.__dict__['_bdm_obj'] = bdm
        else:
            self.__dict__['_bdm_obj'] = block_device_obj.BlockDeviceMapping()
            self._bdm_obj.update(block_device.BlockDeviceDict(bdm))
            self._bdm_obj.obj_reset_changes()

        if self._bdm_obj.no_device:
            raise _NotTransformable()

        self.update(dict((field, None)
                    for field in self._fields))
        self._transform()

    def __getattr__(self, name):
        if name in self._proxy_as_attr:
            return getattr(self._bdm_obj, name)
        else:
            raise AttributeError("Cannot access %s on DriverBlockDevice "
                                  "class" % name)

    def __setattr__(self, name, value):
        if name in self._proxy_as_attr:
            return setattr(self._bdm_obj, name, value)
        else:
            raise AttributeError("Cannot access %s on DriverBlockDevice "
                                  "class" % name)

    def _transform(self):
        """Transform bdm to the format that is passed to drivers."""
        raise NotImplementedError()

    def legacy(self):
        """Basic legacy transformation.

        Basic method will just drop the fields that are not in
        _legacy_fields set. Override this in subclass if needed.
        """
        return dict((key, self.get(key)) for key in self._legacy_fields)

    def attach(self, **kwargs):
        """Make the device available to be used by VMs.

        To be overriden in subclasses with the connecting logic for
        the type of device the subclass represents.
        """
        raise NotImplementedError()

    def save(self, context):
        for attr_name, key_name in self._update_on_save.iteritems():
            setattr(self._bdm_obj, attr_name, self[key_name or attr_name])
        self._bdm_obj.save(context)


class DriverSwapBlockDevice(DriverBlockDevice):
    _fields = set(['device_name', 'swap_size', 'disk_bus'])
    _legacy_fields = _fields - set(['disk_bus'])

    _update_on_save = {'disk_bus': None,
                       'device_name': None}

    def _transform(self):
        if not block_device.new_format_is_swap(self._bdm_obj):
            raise _InvalidType
        self.update({
            'device_name': self._bdm_obj.device_name,
            'swap_size': self._bdm_obj.volume_size or 0,
            'disk_bus': self._bdm_obj.disk_bus
        })


class DriverEphemeralBlockDevice(DriverBlockDevice):
    _new_only_fields = set(['disk_bus', 'device_type', 'guest_format'])
    _fields = set(['device_name', 'size']) | _new_only_fields
    _legacy_fields = (_fields - _new_only_fields |
                      set(['num', 'virtual_name']))

    def _transform(self):
        if not block_device.new_format_is_ephemeral(self._bdm_obj):
            raise _InvalidType
        self.update({
            'device_name': self._bdm_obj.device_name,
            'size': self._bdm_obj.volume_size or 0,
            'disk_bus': self._bdm_obj.disk_bus,
            'device_type': self._bdm_obj.device_type,
            'guest_format': self._bdm_obj.guest_format
        })

    def legacy(self, num=0):
        legacy_bdm = super(DriverEphemeralBlockDevice, self).legacy()
        legacy_bdm['num'] = num
        legacy_bdm['virtual_name'] = 'ephemeral' + str(num)
        return legacy_bdm


class DriverVolumeBlockDevice(DriverBlockDevice):
    _legacy_fields = set(['connection_info', 'mount_device',
                          'delete_on_termination'])
    _new_fields = set(['guest_format', 'device_type',
                       'disk_bus', 'boot_index'])
    _fields = _legacy_fields | _new_fields

    _valid_source = 'volume'
    _valid_destination = 'volume'

    _proxy_as_attr = set(['volume_size', 'volume_id'])
    _update_on_save = {'disk_bus': None,
                       'device_name': 'mount_device',
                       'device_type': None}

    def _transform(self):
        if (not self._bdm_obj.source_type == self._valid_source
                or not self._bdm_obj.destination_type ==
                self._valid_destination):
            raise _InvalidType

        self.update(
            dict((k, v) for k, v in self._bdm_obj.iteritems()
                 if k in self._new_fields | set(['delete_on_termination']))
        )
        self['mount_device'] = self._bdm_obj.device_name
        try:
            self['connection_info'] = jsonutils.loads(
                self._bdm_obj.connection_info)
        except TypeError:
            self['connection_info'] = None

    def _preserve_multipath_id(self, connection_info):
        if self['connection_info'] and 'data' in self['connection_info']:
            if 'multipath_id' in self['connection_info']['data']:
                connection_info['data']['multipath_id'] =\
                    self['connection_info']['data']['multipath_id']
                LOG.info(_LI('preserve multipath_id %s'),
                         connection_info['data']['multipath_id'])

    @update_db
    def attach(self, context, instance, volume_api, virt_driver,
               do_check_attach=True, do_driver_attach=False):
        volume = volume_api.get(context, self.volume_id)
        if do_check_attach:
            volume_api.check_attach(context, volume, instance=instance)

        volume_id = volume['id']
        context = context.elevated()

        connector = virt_driver.get_volume_connector(instance)
        connection_info = volume_api.initialize_connection(context,
                                                           volume_id,
                                                           connector)
        if 'serial' not in connection_info:
            connection_info['serial'] = self.volume_id
        self._preserve_multipath_id(connection_info)

        # If do_driver_attach is False, we will attach a volume to an instance
        # at boot time. So actual attach is done by instance creation code.
        if do_driver_attach:
            encryption = encryptors.get_encryption_metadata(
                context, volume_api, volume_id, connection_info)

            try:
                virt_driver.attach_volume(
                        context, connection_info, instance,
                        self['mount_device'], disk_bus=self['disk_bus'],
                        device_type=self['device_type'], encryption=encryption)
            except Exception:  # pylint: disable=W0702
                with excutils.save_and_reraise_exception():
                    LOG.exception(_("Driver failed to attach volume "
                                    "%(volume_id)s at %(mountpoint)s"),
                                  {'volume_id': volume_id,
                                   'mountpoint': self['mount_device']},
                                  context=context, instance=instance)
                    volume_api.terminate_connection(context, volume_id,
                                                    connector)
        self['connection_info'] = connection_info

        mode = 'rw'
        if 'data' in connection_info:
            mode = connection_info['data'].get('access_mode', 'rw')
        volume_api.attach(context, volume_id, instance['uuid'],
                          self['mount_device'], mode=mode)

    @update_db
    def refresh_connection_info(self, context, instance,
                                volume_api, virt_driver):
        # NOTE (ndipanov): A no-op if there is no connection info already
        if not self['connection_info']:
            return

        connector = virt_driver.get_volume_connector(instance)
        connection_info = volume_api.initialize_connection(context,
                                                           self.volume_id,
                                                           connector)
        if 'serial' not in connection_info:
            connection_info['serial'] = self.volume_id
        self._preserve_multipath_id(connection_info)
        self['connection_info'] = connection_info

    def save(self, context):
        # NOTE(ndipanov): we might want to generalize this by adding it to the
        # _update_on_save and adding a transformation function.
        try:
            self._bdm_obj.connection_info = jsonutils.dumps(
                    self.get('connection_info'))
        except TypeError:
            pass
        super(DriverVolumeBlockDevice, self).save(context)


class DriverSnapshotBlockDevice(DriverVolumeBlockDevice):

    _valid_source = 'snapshot'
    _proxy_as_attr = set(['volume_size', 'volume_id', 'snapshot_id'])

    def attach(self, context, instance, volume_api,
               virt_driver, wait_func=None):

        if not self.volume_id:
            snapshot = volume_api.get_snapshot(context,
                                               self.snapshot_id)
            vol = volume_api.create(context, self.volume_size,
                                    '', '', snapshot)
            if wait_func:
                wait_func(context, vol['id'])

            self.volume_id = vol['id']

        # Call the volume attach now
        super(DriverSnapshotBlockDevice, self).attach(context, instance,
                                                      volume_api, virt_driver)


class DriverImageBlockDevice(DriverVolumeBlockDevice):

    _valid_source = 'image'
    _proxy_as_attr = set(['volume_size', 'volume_id', 'image_id'])

    def attach(self, context, instance, volume_api,
               virt_driver, wait_func=None):
        if not self.volume_id:
            vol = volume_api.create(context, self.volume_size,
                                    '', '', image_id=self.image_id)
            if wait_func:
                wait_func(context, vol['id'])

            self.volume_id = vol['id']

        super(DriverImageBlockDevice, self).attach(context, instance,
                                                   volume_api, virt_driver)


def _convert_block_devices(device_type, block_device_mapping):
    def _is_transformable(bdm):
        try:
            device_type(bdm)
        except _NotTransformable:
            return False
        return True

    return [device_type(bdm)
            for bdm in block_device_mapping
            if _is_transformable(bdm)]


convert_swap = functools.partial(_convert_block_devices,
                                 DriverSwapBlockDevice)


convert_ephemerals = functools.partial(_convert_block_devices,
                                      DriverEphemeralBlockDevice)


convert_volumes = functools.partial(_convert_block_devices,
                                   DriverVolumeBlockDevice)


convert_snapshots = functools.partial(_convert_block_devices,
                                     DriverSnapshotBlockDevice)

convert_images = functools.partial(_convert_block_devices,
                                     DriverImageBlockDevice)


def attach_block_devices(block_device_mapping, *attach_args, **attach_kwargs):
    def _log_and_attach(bdm):
        context = attach_args[0]
        instance = attach_args[1]
        LOG.audit(_('Booting with volume %(volume_id)s at %(mountpoint)s'),
                  {'volume_id': bdm.volume_id,
                   'mountpoint': bdm['mount_device']},
                  context=context, instance=instance)
        bdm.attach(*attach_args, **attach_kwargs)

    map(_log_and_attach, block_device_mapping)
    return block_device_mapping


def refresh_conn_infos(block_device_mapping, *refresh_args, **refresh_kwargs):
    map(operator.methodcaller('refresh_connection_info',
                              *refresh_args, **refresh_kwargs),
        block_device_mapping)
    return block_device_mapping


def legacy_block_devices(block_device_mapping):
    def _has_legacy(bdm):
        try:
            bdm.legacy()
        except _NoLegacy:
            return False
        return True

    bdms = [bdm.legacy()
            for bdm in block_device_mapping
            if _has_legacy(bdm)]

    # Re-enumerate ephemeral devices
    if all(isinstance(bdm, DriverEphemeralBlockDevice)
           for bdm in block_device_mapping):
        for i, dev in enumerate(bdms):
            dev['virtual_name'] = dev['virtual_name'][:-1] + str(i)
            dev['num'] = i

    return bdms


def get_swap(transformed_list):
    """Get the swap device out of the list context.

    The block_device_info needs swap to be a single device,
    not a list - otherwise this is a no-op.
    """
    if not all(isinstance(device, DriverSwapBlockDevice) or
               'swap_size' in device
                for device in transformed_list):
        return transformed_list
    try:
        return transformed_list.pop()
    except IndexError:
        return None


_IMPLEMENTED_CLASSES = (DriverSwapBlockDevice, DriverEphemeralBlockDevice,
                        DriverVolumeBlockDevice, DriverSnapshotBlockDevice,
                        DriverImageBlockDevice)


def is_implemented(bdm):
    for cls in _IMPLEMENTED_CLASSES:
        try:
            cls(bdm)
            return True
        except _NotTransformable:
            pass
    return False
