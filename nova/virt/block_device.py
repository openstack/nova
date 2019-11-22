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
import itertools

from os_brick import encryptors
from os_brick.initiator import utils as brick_utils
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils


from nova import block_device
import nova.conf
from nova import exception

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class _NotTransformable(Exception):
    pass


class _InvalidType(_NotTransformable):
    pass


def update_db(method):
    @functools.wraps(method)
    def wrapped(obj, context, *args, **kwargs):
        try:
            ret_val = method(obj, context, *args, **kwargs)
        finally:
            obj.save()
        return ret_val
    return wrapped


def _get_volume_create_az_value(instance):
    """Determine az to use when creating a volume

    Uses the cinder.cross_az_attach config option to determine the availability
    zone value to use when creating a volume.

    :param nova.objects.Instance instance: The instance for which the volume
        will be created and attached.
    :returns: The availability_zone value to pass to volume_api.create
    """
    # If we're allowed to attach a volume in any AZ to an instance in any AZ,
    # then we don't care what AZ the volume is in so don't specify anything.
    if CONF.cinder.cross_az_attach:
        return None
    # Else the volume has to be in the same AZ as the instance otherwise we
    # fail. If the AZ is not in Cinder the volume create will fail. But on the
    # other hand if the volume AZ and instance AZ don't match and
    # cross_az_attach is False, then volume_api.check_attach will fail too, so
    # we can't really win. :)
    # TODO(mriedem): It would be better from a UX perspective if we could do
    # some validation in the API layer such that if we know we're going to
    # specify the AZ when creating the volume and that AZ is not in Cinder, we
    # could fail the boot from volume request early with a 400 rather than
    # fail to build the instance on the compute node which results in a
    # NoValidHost error.
    return instance.availability_zone


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

    _proxy_as_attr_inherited = set(['uuid', 'is_volume'])
    _update_on_save = {'disk_bus': None,
                       'device_name': None,
                       'device_type': None}

    # A hash containing the combined inherited members of _proxy_as_attr for
    # each subclass
    _proxy_as_attr_by_class = {}

    def __init__(self, bdm):
        self.__dict__['_bdm_obj'] = bdm

        if self._bdm_obj.no_device:
            raise _NotTransformable()

        self.update({field: None for field in self._fields})
        self._transform()

    @property
    def _proxy_as_attr(self):
        # Combine the members of all _proxy_as_attr sets for this class and its
        # ancestors
        if self.__class__ not in self._proxy_as_attr_by_class:
            attr_all = set()
            for cls in self.__class__.mro():
                attr_one = getattr(cls, '_proxy_as_attr_inherited', None)
                if attr_one is not None:
                    attr_all = attr_all | attr_one

            # We don't need to lock here because as long as insertion into a
            # dict is threadsafe, the only consequence of a race is calculating
            # the inherited set multiple times.
            self._proxy_as_attr_by_class[self.__class__] = attr_all

        return self._proxy_as_attr_by_class[self.__class__]

    def __getattr__(self, name):
        if name in self._proxy_as_attr:
            return getattr(self._bdm_obj, name)
        elif name in self._fields:
            return self[name]
        else:
            return super(DriverBlockDevice, self).__getattr__(name)

    def __setattr__(self, name, value):
        if name in self._proxy_as_attr:
            setattr(self._bdm_obj, name, value)
        elif name in self._fields:
            self[name] = value
        else:
            super(DriverBlockDevice, self).__setattr__(name, value)

    def __getitem__(self, name):
        if name in self._proxy_as_attr:
            return getattr(self._bdm_obj, name)
        return super(DriverBlockDevice, self).__getitem__(name)

    def __setitem__(self, name, value):
        if name in self._proxy_as_attr:
            setattr(self._bdm_obj, name, value)
        super(DriverBlockDevice, self).__setitem__(name, value)

    def _transform(self):
        """Transform bdm to the format that is passed to drivers."""
        raise NotImplementedError()

    def get(self, name, default=None):
        if name in self._proxy_as_attr:
            return getattr(self._bdm_obj, name)
        elif name in self._fields:
            return self[name]
        else:
            return super(DriverBlockDevice, self).get(name, default)

    def legacy(self):
        """Basic legacy transformation.

        Basic method will just drop the fields that are not in
        _legacy_fields set. Override this in subclass if needed.
        """
        return {key: self.get(key) for key in self._legacy_fields}

    def attach(self, **kwargs):
        """Make the device available to be used by VMs.

        To be overridden in subclasses with the connecting logic for
        the type of device the subclass represents.
        """
        raise NotImplementedError()

    def detach(self, **kwargs):
        """Detach the device from an instance and detach in Cinder.

        Note: driver_detach is called as part of this method.

        To be overridden in subclasses with the detaching logic for
        the type of device the subclass represents.
        """
        raise NotImplementedError()

    def driver_detach(self, **kwargs):
        """Detach the device from an instance (don't detach in Cinder).

        To be overridden in subclasses with the detaching logic for
        the type of device the subclass represents.
        """
        raise NotImplementedError()

    def save(self):
        for attr_name, key_name in self._update_on_save.items():
            lookup_name = key_name or attr_name
            if self[lookup_name] != getattr(self._bdm_obj, attr_name):
                setattr(self._bdm_obj, attr_name, self[lookup_name])
        self._bdm_obj.save()


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
                       'disk_bus', 'boot_index',
                       'attachment_id'])
    _fields = _legacy_fields | _new_fields

    _valid_source = 'volume'
    _valid_destination = 'volume'

    _proxy_as_attr_inherited = set(['volume_size', 'volume_id', 'volume_type'])
    _update_on_save = {'disk_bus': None,
                       'device_name': 'mount_device',
                       'device_type': None,
                       # needed for boot from volume for blank/image/snapshot
                       'attachment_id': None}

    def _transform(self):
        if (not self._bdm_obj.source_type == self._valid_source or
                not self._bdm_obj.destination_type == self._valid_destination):
            raise _InvalidType

        self.update(
            {k: v for k, v in self._bdm_obj.items()
             if k in self._new_fields | set(['delete_on_termination'])}
        )
        self['mount_device'] = self._bdm_obj.device_name
        # connection_info might not be set so default to an empty dict so that
        # it can be serialized to an empty JSON object.
        try:
            self['connection_info'] = jsonutils.loads(
                self._bdm_obj.connection_info)
        except TypeError:
            self['connection_info'] = {}
        # volume_type might not be set on the internal bdm object so default
        # to None if not set
        self['volume_type'] = (
            self.volume_type if 'volume_type' in self._bdm_obj else None)

    def _preserve_multipath_id(self, connection_info):
        if self['connection_info'] and 'data' in self['connection_info']:
            if 'multipath_id' in self['connection_info']['data']:
                connection_info['data']['multipath_id'] =\
                    self['connection_info']['data']['multipath_id']
                LOG.info('preserve multipath_id %s',
                         connection_info['data']['multipath_id'])

    def driver_detach(self, context, instance, volume_api, virt_driver):
        connection_info = self['connection_info']
        mp = self['mount_device']
        volume_id = self.volume_id

        LOG.info('Attempting to driver detach volume %(volume_id)s from '
                 'mountpoint %(mp)s', {'volume_id': volume_id, 'mp': mp},
                 instance=instance)
        try:
            if not virt_driver.instance_exists(instance):
                LOG.warning('Detaching volume from unknown instance',
                            instance=instance)

            encryption = encryptors.get_encryption_metadata(context,
                    volume_api, volume_id, connection_info)
            virt_driver.detach_volume(context, connection_info, instance, mp,
                                      encryption=encryption)
        except exception.DiskNotFound as err:
            LOG.warning('Ignoring DiskNotFound exception while '
                        'detaching volume %(volume_id)s from '
                        '%(mp)s : %(err)s',
                        {'volume_id': volume_id, 'mp': mp,
                         'err': err}, instance=instance)
        except exception.DeviceDetachFailed:
            with excutils.save_and_reraise_exception():
                LOG.warning('Guest refused to detach volume %(vol)s',
                            {'vol': volume_id}, instance=instance)
                volume_api.roll_detaching(context, volume_id)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Failed to detach volume '
                              '%(volume_id)s from %(mp)s',
                              {'volume_id': volume_id, 'mp': mp},
                              instance=instance)
                volume_api.roll_detaching(context, volume_id)

    @staticmethod
    def _get_volume(context, volume_api, volume_id):
        # First try to get the volume at microversion 3.48 so we can get the
        # shared_targets parameter exposed in that version. If that API version
        # is not available, we just fallback.
        try:
            return volume_api.get(context, volume_id, microversion='3.48')
        except exception.CinderAPIVersionNotAvailable:
            return volume_api.get(context, volume_id)

    def _create_volume(self, context, instance, volume_api, size,
                       wait_func=None, **create_kwargs):
        """Create a volume and attachment record.

        :param context: nova auth RequestContext
        :param instance: Instance object to which the created volume will be
            attached.
        :param volume_api: nova.volume.cinder.API instance
        :param size: The size of the volume to create in GiB.
        :param wait_func: Optional callback function to wait for the volume to
            reach some status before continuing with a signature of::

                wait_func(context, volume_id)
        :param create_kwargs: Additional optional parameters used to create the
            volume. See nova.volume.cinder.API.create for keys.
        :return: A two-item tuple of volume ID and attachment ID.
        """
        av_zone = _get_volume_create_az_value(instance)
        name = create_kwargs.pop('name', '')
        description = create_kwargs.pop('description', '')
        vol = volume_api.create(
            context, size, name, description, volume_type=self.volume_type,
            availability_zone=av_zone, **create_kwargs)

        if wait_func:
            self._call_wait_func(context, wait_func, volume_api, vol['id'])

        # Unconditionally create an attachment record for the volume so the
        # attach/detach flows use the "new style" introduced in Queens. Note
        # that nova required the Cinder Queens level APIs (3.44+) starting in
        # Train.
        attachment_id = (
            volume_api.attachment_create(
                context, vol['id'], instance.uuid)['id'])

        return vol['id'], attachment_id

    def _do_detach(self, context, instance, volume_api, virt_driver,
                   attachment_id=None, destroy_bdm=False):
        """Private method that actually does the detach.

        This is separate from the detach() method so the caller can optionally
        lock this call.
        """
        volume_id = self.volume_id

        # Only attempt to detach and disconnect from the volume if the instance
        # is currently associated with the local compute host.
        if CONF.host == instance.host:
            self.driver_detach(context, instance, volume_api, virt_driver)
        elif not destroy_bdm:
            LOG.debug("Skipping driver_detach during remote rebuild.",
                      instance=instance)
        elif destroy_bdm:
            LOG.error("Unable to call for a driver detach of volume "
                      "%(vol_id)s due to the instance being "
                      "registered to the remote host %(inst_host)s.",
                      {'vol_id': volume_id,
                       'inst_host': instance.host}, instance=instance)

        # NOTE(jdg): For now we need to actually inspect the bdm for an
        # attachment_id as opposed to relying on what may have been passed
        # in, we want to force usage of the old detach flow for now and only
        # use the new flow when we explicitly used it for the attach.
        if not self['attachment_id']:
            connector = virt_driver.get_volume_connector(instance)
            connection_info = self['connection_info']
            if connection_info and not destroy_bdm and (
               connector.get('host') != instance.host):
                # If the volume is attached to another host (evacuate) then
                # this connector is for the wrong host. Use the connector that
                # was stored in connection_info instead (if we have one, and it
                # is for the expected host).
                stashed_connector = connection_info.get('connector')
                if not stashed_connector:
                    # Volume was attached before we began stashing connectors
                    LOG.warning("Host mismatch detected, but stashed "
                                "volume connector not found. Instance host is "
                                "%(ihost)s, but volume connector host is "
                                "%(chost)s.",
                                {'ihost': instance.host,
                                 'chost': connector.get('host')})
                elif stashed_connector.get('host') != instance.host:
                    # Unexpected error. The stashed connector is also not
                    # matching the needed instance host.
                    LOG.error("Host mismatch detected in stashed volume "
                              "connector. Will use local volume connector. "
                              "Instance host is %(ihost)s. Local volume "
                              "connector host is %(chost)s. Stashed volume "
                              "connector host is %(schost)s.",
                              {'ihost': instance.host,
                               'chost': connector.get('host'),
                               'schost': stashed_connector.get('host')})
                else:
                    # Fix found. Use stashed connector.
                    LOG.debug("Host mismatch detected. Found usable stashed "
                              "volume connector. Instance host is %(ihost)s. "
                              "Local volume connector host was %(chost)s. "
                              "Stashed volume connector host is %(schost)s.",
                              {'ihost': instance.host,
                               'chost': connector.get('host'),
                               'schost': stashed_connector.get('host')})
                    connector = stashed_connector

            volume_api.terminate_connection(context, volume_id, connector)
            volume_api.detach(context.elevated(), volume_id, instance.uuid,
                              attachment_id)
        else:
            volume_api.attachment_delete(context, self['attachment_id'])

    def detach(self, context, instance, volume_api, virt_driver,
               attachment_id=None, destroy_bdm=False):
        volume = self._get_volume(context, volume_api, self.volume_id)
        # Let OS-Brick handle high level locking that covers the local os-brick
        # detach and the Cinder call to call unmap the volume.  Not all volume
        # backends or hosts require locking.
        with brick_utils.guard_connection(volume):
            self._do_detach(context, instance, volume_api, virt_driver,
                            attachment_id, destroy_bdm)

    def _legacy_volume_attach(self, context, volume, connector, instance,
                              volume_api, virt_driver,
                              do_driver_attach=False):
        volume_id = volume['id']

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
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception("Driver failed to attach volume "
                                  "%(volume_id)s at %(mountpoint)s",
                                  {'volume_id': volume_id,
                                   'mountpoint': self['mount_device']},
                                  instance=instance)
                    volume_api.terminate_connection(context, volume_id,
                                                    connector)
        self['connection_info'] = connection_info
        if self.volume_size is None:
            self.volume_size = volume.get('size')

        mode = 'rw'
        if 'data' in connection_info:
            mode = connection_info['data'].get('access_mode', 'rw')
        if volume['attach_status'] == "detached":
            # NOTE(mriedem): save our current state so connection_info is in
            # the database before the volume status goes to 'in-use' because
            # after that we can detach and connection_info is required for
            # detach.
            self.save()
            try:
                volume_api.attach(context, volume_id, instance.uuid,
                                  self['mount_device'], mode=mode)
            except Exception:
                with excutils.save_and_reraise_exception():
                    if do_driver_attach:
                        try:
                            virt_driver.detach_volume(context,
                                                      connection_info,
                                                      instance,
                                                      self['mount_device'],
                                                      encryption=encryption)
                        except Exception:
                            LOG.warning("Driver failed to detach volume "
                                        "%(volume_id)s at %(mount_point)s.",
                                        {'volume_id': volume_id,
                                         'mount_point': self['mount_device']},
                                        exc_info=True, instance=instance)
                    volume_api.terminate_connection(context, volume_id,
                                                    connector)

                    # Cinder-volume might have completed volume attach. So
                    # we should detach the volume. If the attach did not
                    # happen, the detach request will be ignored.
                    volume_api.detach(context, volume_id)

    def _volume_attach(self, context, volume, connector, instance,
                       volume_api, virt_driver, attachment_id,
                       do_driver_attach=False):
        # This is where we actually (finally) make a call down to the device
        # driver and actually create/establish the connection.  We'll go from
        # here to block driver-->os-brick and back up.

        volume_id = volume['id']
        if self.volume_size is None:
            self.volume_size = volume.get('size')

        vol_multiattach = volume.get('multiattach', False)
        virt_multiattach = virt_driver.capabilities.get(
            'supports_multiattach', False)

        if vol_multiattach and not virt_multiattach:
            raise exception.MultiattachNotSupportedByVirtDriver(
                      volume_id=volume_id)

        LOG.debug("Updating existing volume attachment record: %s",
                  attachment_id, instance=instance)
        connection_info = volume_api.attachment_update(
            context, attachment_id, connector,
            self['mount_device'])['connection_info']
        if 'serial' not in connection_info:
            connection_info['serial'] = self.volume_id
        self._preserve_multipath_id(connection_info)
        if vol_multiattach:
            # This will be used by the volume driver to determine the proper
            # disk configuration.
            # TODO(mriedem): Long-term we should stop stashing the multiattach
            # flag in the bdm.connection_info since that should be an untouched
            # set of values we can refresh from Cinder as needed. Putting the
            # multiattach flag on the bdm directly will require schema and
            # online data migrations, plus some refactoring to anything that
            # needs to get a block device disk config, like spawn/migrate/swap
            # and the LibvirtLiveMigrateBDMInfo would also need to store the
            # value.
            connection_info['multiattach'] = True

        if do_driver_attach:
            encryption = encryptors.get_encryption_metadata(
                context, volume_api, volume_id, connection_info)

            try:
                virt_driver.attach_volume(
                        context, connection_info, instance,
                        self['mount_device'], disk_bus=self['disk_bus'],
                        device_type=self['device_type'], encryption=encryption)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception("Driver failed to attach volume "
                                      "%(volume_id)s at %(mountpoint)s",
                                  {'volume_id': volume_id,
                                   'mountpoint': self['mount_device']},
                                  instance=instance)
                    volume_api.attachment_delete(context,
                                                 attachment_id)

        # NOTE(mriedem): save our current state so connection_info is in
        # the database before the volume status goes to 'in-use' because
        # after that we can detach and connection_info is required for
        # detach.
        # TODO(mriedem): Technically for the new flow, we shouldn't have to
        # rely on the BlockDeviceMapping.connection_info since it's stored
        # with the attachment in Cinder (see refresh_connection_info).
        # Therefore we should phase out code that relies on the
        # BDM.connection_info and get it from Cinder if it's needed.
        self['connection_info'] = connection_info
        self.save()

        try:
            # This marks the volume as "in-use".
            volume_api.attachment_complete(context, attachment_id)
        except Exception:
            with excutils.save_and_reraise_exception():
                if do_driver_attach:
                    # Disconnect the volume from the host.
                    try:
                        virt_driver.detach_volume(context,
                                                  connection_info,
                                                  instance,
                                                  self['mount_device'],
                                                  encryption=encryption)
                    except Exception:
                        LOG.warning("Driver failed to detach volume "
                                    "%(volume_id)s at %(mount_point)s.",
                                    {'volume_id': volume_id,
                                     'mount_point': self['mount_device']},
                                    exc_info=True, instance=instance)
                # Delete the attachment to mark the volume as "available".
                volume_api.attachment_delete(context, self['attachment_id'])

    def _do_attach(self, context, instance, volume, volume_api, virt_driver,
                   do_driver_attach):
        """Private method that actually does the attach.

        This is separate from the attach() method so the caller can optionally
        lock this call.
        """
        context = context.elevated()
        connector = virt_driver.get_volume_connector(instance)
        if not self['attachment_id']:
            self._legacy_volume_attach(context, volume, connector, instance,
                                       volume_api, virt_driver,
                                       do_driver_attach)
        else:
            self._volume_attach(context, volume, connector, instance,
                                volume_api, virt_driver,
                                self['attachment_id'],
                                do_driver_attach)

    @update_db
    def attach(self, context, instance, volume_api, virt_driver,
               do_driver_attach=False, **kwargs):
        volume = self._get_volume(context, volume_api, self.volume_id)
        volume_api.check_availability_zone(context, volume,
                                           instance=instance)
        # Let OS-Brick handle high level locking that covers the call to
        # Cinder that exports & maps the volume, and for the local os-brick
        # attach.  Not all volume backends or hosts require locking.
        with brick_utils.guard_connection(volume):
            self._do_attach(context, instance, volume, volume_api,
                            virt_driver, do_driver_attach)

    @update_db
    def refresh_connection_info(self, context, instance,
                                volume_api, virt_driver):
        # NOTE (ndipanov): A no-op if there is no connection info already
        if not self['connection_info']:
            return

        if not self['attachment_id']:
            connector = virt_driver.get_volume_connector(instance)
            connection_info = volume_api.initialize_connection(context,
                                                               self.volume_id,
                                                               connector)
        else:
            attachment_ref = volume_api.attachment_get(context,
                                                       self['attachment_id'])
            # The _volume_attach method stashes a 'multiattach' flag in the
            # BlockDeviceMapping.connection_info which is not persisted back
            # in cinder so before we overwrite the BDM.connection_info (via
            # the update_db decorator on this method), we need to make sure
            # and preserve the multiattach flag if it's set. Note that this
            # is safe to do across refreshes because the multiattach capability
            # of a volume cannot be changed while the volume is in-use.
            multiattach = self['connection_info'].get('multiattach', False)
            connection_info = attachment_ref['connection_info']
            if multiattach:
                connection_info['multiattach'] = True

        if 'serial' not in connection_info:
            connection_info['serial'] = self.volume_id
        self._preserve_multipath_id(connection_info)
        self['connection_info'] = connection_info

    def save(self):
        # NOTE(ndipanov): we might want to generalize this by adding it to the
        # _update_on_save and adding a transformation function.
        try:
            connection_info_string = jsonutils.dumps(
                self.get('connection_info'))
            if connection_info_string != self._bdm_obj.connection_info:
                self._bdm_obj.connection_info = connection_info_string
        except TypeError:
            pass
        super(DriverVolumeBlockDevice, self).save()

    def _call_wait_func(self, context, wait_func, volume_api, volume_id):
        try:
            wait_func(context, volume_id)
        except exception.VolumeNotCreated:
            with excutils.save_and_reraise_exception():
                if self['delete_on_termination']:
                    try:
                        volume_api.delete(context, volume_id)
                    except Exception as exc:
                        LOG.warning(
                            'Failed to delete volume: %(volume_id)s '
                            'due to %(exc)s',
                            {'volume_id': volume_id, 'exc': exc})


class DriverVolSnapshotBlockDevice(DriverVolumeBlockDevice):

    _valid_source = 'snapshot'
    _proxy_as_attr_inherited = set(['snapshot_id'])

    def attach(self, context, instance, volume_api,
               virt_driver, wait_func=None):

        if not self.volume_id:
            snapshot = volume_api.get_snapshot(context,
                                               self.snapshot_id)
            # NOTE(lyarwood): Try to use the original volume type if one isn't
            # set against the bdm but is on the original volume.
            if not self.volume_type and snapshot.get('volume_id'):
                snap_volume_id = snapshot.get('volume_id')
                orig_volume = volume_api.get(context, snap_volume_id)
                self.volume_type = orig_volume.get('volume_type_id')

            self.volume_id, self.attachment_id = self._create_volume(
                context, instance, volume_api, self.volume_size,
                wait_func=wait_func, snapshot=snapshot)

        # Call the volume attach now
        super(DriverVolSnapshotBlockDevice, self).attach(
            context, instance, volume_api, virt_driver)


class DriverVolImageBlockDevice(DriverVolumeBlockDevice):

    _valid_source = 'image'
    _proxy_as_attr_inherited = set(['image_id'])

    def attach(self, context, instance, volume_api,
               virt_driver, wait_func=None):
        if not self.volume_id:
            self.volume_id, self.attachment_id = self._create_volume(
                context, instance, volume_api, self.volume_size,
                wait_func=wait_func, image_id=self.image_id)

        super(DriverVolImageBlockDevice, self).attach(
            context, instance, volume_api, virt_driver)


class DriverVolBlankBlockDevice(DriverVolumeBlockDevice):

    _valid_source = 'blank'
    _proxy_as_attr_inherited = set(['image_id'])

    def attach(self, context, instance, volume_api,
               virt_driver, wait_func=None):
        if not self.volume_id:
            vol_name = instance.uuid + '-blank-vol'
            self.volume_id, self.attachment_id = self._create_volume(
                context, instance, volume_api, self.volume_size,
                wait_func=wait_func, name=vol_name)

        super(DriverVolBlankBlockDevice, self).attach(
            context, instance, volume_api, virt_driver)


def _convert_block_devices(device_type, block_device_mapping):
    devices = []
    for bdm in block_device_mapping:
        try:
            devices.append(device_type(bdm))
        except _NotTransformable:
            pass

    return devices


convert_swap = functools.partial(_convert_block_devices,
                                 DriverSwapBlockDevice)


convert_ephemerals = functools.partial(_convert_block_devices,
                                      DriverEphemeralBlockDevice)


convert_volumes = functools.partial(_convert_block_devices,
                                   DriverVolumeBlockDevice)


convert_snapshots = functools.partial(_convert_block_devices,
                                     DriverVolSnapshotBlockDevice)

convert_images = functools.partial(_convert_block_devices,
                                     DriverVolImageBlockDevice)

convert_blanks = functools.partial(_convert_block_devices,
                                   DriverVolBlankBlockDevice)


def convert_all_volumes(*volume_bdms):
    source_volume = convert_volumes(volume_bdms)
    source_snapshot = convert_snapshots(volume_bdms)
    source_image = convert_images(volume_bdms)
    source_blank = convert_blanks(volume_bdms)

    return [vol for vol in
            itertools.chain(source_volume, source_snapshot,
                            source_image, source_blank)]


def convert_volume(volume_bdm):
    try:
        return convert_all_volumes(volume_bdm)[0]
    except IndexError:
        pass


def attach_block_devices(block_device_mapping, *attach_args, **attach_kwargs):
    def _log_and_attach(bdm):
        instance = attach_args[1]
        if bdm.get('volume_id'):
            LOG.info('Booting with volume %(volume_id)s at '
                     '%(mountpoint)s',
                     {'volume_id': bdm.volume_id,
                      'mountpoint': bdm['mount_device']},
                     instance=instance)
        elif bdm.get('snapshot_id'):
            LOG.info('Booting with volume snapshot %(snapshot_id)s at '
                     '%(mountpoint)s',
                     {'snapshot_id': bdm.snapshot_id,
                      'mountpoint': bdm['mount_device']},
                     instance=instance)
        elif bdm.get('image_id'):
            LOG.info('Booting with volume-backed-image %(image_id)s at '
                     '%(mountpoint)s',
                     {'image_id': bdm.image_id,
                      'mountpoint': bdm['mount_device']},
                     instance=instance)
        else:
            LOG.info('Booting with blank volume at %(mountpoint)s',
                     {'mountpoint': bdm['mount_device']},
                     instance=instance)

        bdm.attach(*attach_args, **attach_kwargs)

    for device in block_device_mapping:
        _log_and_attach(device)
    return block_device_mapping


def refresh_conn_infos(block_device_mapping, *refresh_args, **refresh_kwargs):
    for device in block_device_mapping:
        # NOTE(lyarwood): At present only DriverVolumeBlockDevice derived
        # devices provide a refresh_connection_info method.
        if hasattr(device, 'refresh_connection_info'):
            device.refresh_connection_info(*refresh_args, **refresh_kwargs)
    return block_device_mapping


def legacy_block_devices(block_device_mapping):
    bdms = [bdm.legacy() for bdm in block_device_mapping]

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
        return None
    try:
        return transformed_list.pop()
    except IndexError:
        return None


_IMPLEMENTED_CLASSES = (DriverSwapBlockDevice, DriverEphemeralBlockDevice,
                        DriverVolumeBlockDevice, DriverVolSnapshotBlockDevice,
                        DriverVolImageBlockDevice, DriverVolBlankBlockDevice)


def is_implemented(bdm):
    for cls in _IMPLEMENTED_CLASSES:
        try:
            cls(bdm)
            return True
        except _NotTransformable:
            pass
    return False


def is_block_device_mapping(bdm):
    return (bdm.source_type in ('image', 'volume', 'snapshot', 'blank') and
            bdm.destination_type == 'volume' and
            is_implemented(bdm))


def get_volume_id(connection_info):
    if connection_info:
        # Check for volume_id in 'data' and if not there, fallback to
        # the 'serial' that the DriverVolumeBlockDevice adds during attach.
        volume_id = connection_info.get('data', {}).get('volume_id')
        if not volume_id:
            volume_id = connection_info.get('serial')
        return volume_id
