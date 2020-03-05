# Copyright 2012 Grid Dynamics
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

import abc
import base64
import contextlib
import errno
import functools
import os
import shutil

from castellan import key_manager
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import fileutils
from oslo_utils import strutils
from oslo_utils import units
import six

import nova.conf
from nova import exception
from nova.i18n import _
from nova import image
import nova.privsep.libvirt
import nova.privsep.path
from nova import utils
from nova.virt.disk import api as disk
from nova.virt.image import model as imgmodel
from nova.virt import images
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt.storage import dmcrypt
from nova.virt.libvirt.storage import lvm
from nova.virt.libvirt.storage import rbd_utils
from nova.virt.libvirt import utils as libvirt_utils

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)
IMAGE_API = image.API()


# NOTE(neiljerram): Don't worry if this fails. This sometimes happens, with
# EACCES (Permission Denied), when the base file is on an NFS client
# filesystem. I don't understand why, but wonder if it's a similar problem as
# the one that motivated using touch instead of utime in ec9d5e375e2.  In any
# case, IIUC, timing isn't the primary thing that the image cache manager uses
# to determine when the base file is in use. The primary mechanism for that is
# whether there is a matching disk file for a current instance. The timestamp
# on the base file is only used when deciding whether to delete a base file
# that is _not_ in use; so it is not a big deal if that deletion happens
# slightly earlier, for an unused base file, because of one of these preceding
# utime calls having failed.
# NOTE(mdbooth): Only use this method for updating the utime of an image cache
# entry during disk creation.
# TODO(mdbooth): Remove or rework this when we understand the problem.
def _update_utime_ignore_eacces(path):
    try:
        nova.privsep.path.utime(path)
    except OSError as e:
        with excutils.save_and_reraise_exception(logger=LOG) as ctxt:
            if e.errno == errno.EACCES:
                LOG.warning("Ignoring failure to update utime of %(path)s: "
                            "%(error)s", {'path': path, 'error': e})
                ctxt.reraise = False


@six.add_metaclass(abc.ABCMeta)
class Image(object):

    SUPPORTS_CLONE = False

    def __init__(self, path, source_type, driver_format, is_block_dev=False):
        """Image initialization.

        :param path: libvirt's representation of the path of this disk.
        :param source_type: block or file
        :param driver_format: raw or qcow2
        :param is_block_dev:
        """
        if (CONF.ephemeral_storage_encryption.enabled and
                not self._supports_encryption()):
            msg = _('Incompatible settings: ephemeral storage encryption is '
                    'supported only for LVM images.')
            raise exception.InternalError(msg)

        self.path = path

        self.source_type = source_type
        self.driver_format = driver_format
        self.driver_io = None
        self.discard_mode = CONF.libvirt.hw_disk_discard
        self.is_block_dev = is_block_dev
        self.preallocate = False

        # NOTE(dripton): We store lines of json (path, disk_format) in this
        # file, for some image types, to prevent attacks based on changing the
        # disk_format.
        self.disk_info_path = None

        # NOTE(mikal): We need a lock directory which is shared along with
        # instance files, to cover the scenario where multiple compute nodes
        # are trying to create a base file at the same time
        self.lock_path = os.path.join(CONF.instances_path, 'locks')

    def _supports_encryption(self):
        """Used to test that the backend supports encryption.
        Override in the subclass if backend supports encryption.
        """
        return False

    @abc.abstractmethod
    def create_image(self, prepare_template, base, size, *args, **kwargs):
        """Create image from template.

        Contains specific behavior for each image type.

        :prepare_template: function, that creates template.
                           Should accept `target` argument.
        :base: Template name
        :size: Size of created image in bytes

        """
        pass

    @abc.abstractmethod
    def resize_image(self, size):
        """Resize image to size (in bytes).

        :size: Desired size of image in bytes

        """
        pass

    def libvirt_info(self, disk_info, cache_mode,
                     extra_specs, hypervisor_version, boot_order=None,
                     disk_unit=None):
        """Get `LibvirtConfigGuestDisk` filled for this image.

        :disk_info: Metadata generated by libvirt.blockinfo.get_disk_mapping
        :cache_mode: Caching mode for this image
        :extra_specs: Instance type extra specs dict.
        :hypervisor_version: the hypervisor version
        :boot_order: Disk device boot order
        """
        disk_bus = disk_info['bus']
        info = vconfig.LibvirtConfigGuestDisk()
        info.source_type = self.source_type
        info.source_device = disk_info['type']
        info.target_bus = disk_bus
        info.target_dev = disk_info['dev']
        info.driver_cache = cache_mode
        info.driver_discard = self.discard_mode
        info.driver_io = self.driver_io
        info.driver_format = self.driver_format
        driver_name = libvirt_utils.pick_disk_driver_name(hypervisor_version,
                                                          self.is_block_dev)
        info.driver_name = driver_name
        info.source_path = self.path
        info.boot_order = boot_order

        if disk_bus == 'scsi':
            self.disk_scsi(info, disk_unit)

        self.disk_qos(info, extra_specs)

        return info

    def disk_scsi(self, info, disk_unit):
        # NOTE(melwitt): We set the device address unit number manually in the
        # case of the virtio-scsi controller, in order to allow attachment of
        # up to 256 devices. So, we should only be setting the address tag
        # if we intend to set the unit number. Otherwise, we will let libvirt
        # handle autogeneration of the address tag.
        # See https://bugs.launchpad.net/nova/+bug/1792077 for details.
        if disk_unit is not None:
            # The driver is responsible to create the SCSI controller
            # at index 0.
            info.device_addr = vconfig.LibvirtConfigGuestDeviceAddressDrive()
            info.device_addr.controller = 0
            # In order to allow up to 256 disks handled by one
            # virtio-scsi controller, the device addr should be
            # specified.
            info.device_addr.unit = disk_unit

    def disk_qos(self, info, extra_specs):
        tune_items = ['disk_read_bytes_sec', 'disk_read_iops_sec',
            'disk_write_bytes_sec', 'disk_write_iops_sec',
            'disk_total_bytes_sec', 'disk_total_iops_sec']
        for key, value in extra_specs.items():
            scope = key.split(':')
            if len(scope) > 1 and scope[0] == 'quota':
                if scope[1] in tune_items:
                    setattr(info, scope[1], value)

    def libvirt_fs_info(self, target, driver_type=None):
        """Get `LibvirtConfigGuestFilesys` filled for this image.

        :target: target directory inside a container.
        :driver_type: filesystem driver type, can be loop
                      nbd or ploop.
        """
        info = vconfig.LibvirtConfigGuestFilesys()
        info.target_dir = target

        if self.is_block_dev:
            info.source_type = "block"
            info.source_dev = self.path
        else:
            info.source_type = "file"
            info.source_file = self.path
            info.driver_format = self.driver_format
            if driver_type:
                info.driver_type = driver_type
            else:
                if self.driver_format == "raw":
                    info.driver_type = "loop"
                else:
                    info.driver_type = "nbd"

        return info

    def exists(self):
        return os.path.exists(self.path)

    def cache(self, fetch_func, filename, size=None, *args, **kwargs):
        """Creates image from template.

        Ensures that template and image not already exists.
        Ensures that base directory exists.
        Synchronizes on template fetching.

        :fetch_func: Function that creates the base image
                     Should accept `target` argument.
        :filename: Name of the file in the image directory
        :size: Size of created image in bytes (optional)
        """
        base_dir = os.path.join(CONF.instances_path,
                                CONF.image_cache_subdirectory_name)
        if not os.path.exists(base_dir):
            fileutils.ensure_tree(base_dir)
        base = os.path.join(base_dir, filename)

        @utils.synchronized(filename, external=True, lock_path=self.lock_path)
        def fetch_func_sync(target, *args, **kwargs):
            # NOTE(mdbooth): This method is called as a callback by the
            # create_image() method of a specific backend. It assumes that
            # target will be in the image cache, which is why it holds a
            # lock, and does not overwrite an existing file. However,
            # this is not true for all backends. Specifically Lvm writes
            # directly to the target rather than to the image cache,
            # and additionally it creates the target in advance.
            # This guard is only relevant in the context of the lock if the
            # target is in the image cache. If it isn't, we should
            # call fetch_func. The lock we're holding is also unnecessary in
            # that case, but it will not result in incorrect behaviour.
            if target != base or not os.path.exists(target):
                fetch_func(target=target, *args, **kwargs)

        if not self.exists() or not os.path.exists(base):
            self.create_image(fetch_func_sync, base, size,
                              *args, **kwargs)

        if size:
            # create_image() only creates the base image if needed, so
            # we cannot rely on it to exist here
            if os.path.exists(base) and size > self.get_disk_size(base):
                self.resize_image(size)

            if (self.preallocate and self._can_fallocate() and
                    os.access(self.path, os.W_OK)):
                processutils.execute('fallocate', '-n', '-l', size, self.path)

    def _can_fallocate(self):
        """Check once per class, whether fallocate(1) is available,
           and that the instances directory supports fallocate(2).
        """
        can_fallocate = getattr(self.__class__, 'can_fallocate', None)
        if can_fallocate is None:
            test_path = self.path + '.fallocate_test'
            _out, err = processutils.trycmd('fallocate', '-l', '1', test_path)
            fileutils.delete_if_exists(test_path)
            can_fallocate = not err
            self.__class__.can_fallocate = can_fallocate
            if not can_fallocate:
                LOG.warning('Unable to preallocate image at path: %(path)s',
                            {'path': self.path})
        return can_fallocate

    def verify_base_size(self, base, size, base_size=0):
        """Check that the base image is not larger than size.
           Since images can't be generally shrunk, enforce this
           constraint taking account of virtual image size.
        """

        # Note(pbrady): The size and min_disk parameters of a glance
        #  image are checked against the instance size before the image
        #  is even downloaded from glance, but currently min_disk is
        #  adjustable and doesn't currently account for virtual disk size,
        #  so we need this extra check here.
        # NOTE(cfb): Having a flavor that sets the root size to 0 and having
        #  nova effectively ignore that size and use the size of the
        #  image is considered a feature at this time, not a bug.

        if size is None:
            return

        if size and not base_size:
            base_size = self.get_disk_size(base)

        if size < base_size:
            LOG.error('%(base)s virtual size %(base_size)s '
                      'larger than flavor root disk size %(size)s',
                      {'base': base,
                       'base_size': base_size,
                       'size': size})
            raise exception.FlavorDiskSmallerThanImage(
                flavor_size=size, image_size=base_size)

    def get_disk_size(self, name):
        return disk.get_disk_size(name)

    @abc.abstractmethod
    def snapshot_extract(self, target, out_format):
        """Extract a snapshot of the image.

        This is used during cold (offline) snapshots. Live snapshots
        while the guest is still running are handled separately.

        :param target: The target path for the image snapshot.
        :param out_format: The image snapshot format.
        """
        raise NotImplementedError()

    def _get_driver_format(self):
        return self.driver_format

    def resolve_driver_format(self):
        """Return the driver format for self.path.

        First checks self.disk_info_path for an entry.
        If it's not there, calls self._get_driver_format(), and then
        stores the result in self.disk_info_path

        See https://bugs.launchpad.net/nova/+bug/1221190
        """
        def _dict_from_line(line):
            if not line:
                return {}
            try:
                return jsonutils.loads(line)
            except (TypeError, ValueError) as e:
                msg = (_("Could not load line %(line)s, got error "
                        "%(error)s") %
                        {'line': line, 'error': e})
                raise exception.InvalidDiskInfo(reason=msg)

        @utils.synchronized(self.disk_info_path, external=False,
                            lock_path=self.lock_path)
        def write_to_disk_info_file():
            # Use os.open to create it without group or world write permission.
            fd = os.open(self.disk_info_path, os.O_RDONLY | os.O_CREAT, 0o644)
            with os.fdopen(fd, "r") as disk_info_file:
                line = disk_info_file.read().rstrip()
                dct = _dict_from_line(line)

            if self.path in dct:
                msg = _("Attempted overwrite of an existing value.")
                raise exception.InvalidDiskInfo(reason=msg)
            dct.update({self.path: driver_format})

            tmp_path = self.disk_info_path + ".tmp"
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT, 0o644)
            with os.fdopen(fd, "w") as tmp_file:
                tmp_file.write('%s\n' % jsonutils.dumps(dct))
            os.rename(tmp_path, self.disk_info_path)

        try:
            if (self.disk_info_path is not None and
                        os.path.exists(self.disk_info_path)):
                with open(self.disk_info_path) as disk_info_file:
                    line = disk_info_file.read().rstrip()
                    dct = _dict_from_line(line)
                    for path, driver_format in dct.items():
                        if path == self.path:
                            return driver_format
            driver_format = self._get_driver_format()
            if self.disk_info_path is not None:
                fileutils.ensure_tree(os.path.dirname(self.disk_info_path))
                write_to_disk_info_file()
        except OSError as e:
            raise exception.DiskInfoReadWriteFail(reason=six.text_type(e))
        return driver_format

    @staticmethod
    def is_shared_block_storage():
        """True if the backend puts images on a shared block storage."""
        return False

    @staticmethod
    def is_file_in_instance_path():
        """True if the backend stores images in files under instance path."""
        return False

    def clone(self, context, image_id_or_uri):
        """Clone an image.

        Note that clone operation is backend-dependent. The backend may ask
        the image API for a list of image "locations" and select one or more
        of those locations to clone an image from.

        :param image_id_or_uri: The ID or URI of an image to clone.

        :raises: exception.ImageUnacceptable if it cannot be cloned
        """
        reason = _('clone() is not implemented')
        raise exception.ImageUnacceptable(image_id=image_id_or_uri,
                                          reason=reason)

    def flatten(self):
        """Flatten an image.

        The implementation of this method is optional and therefore is
        not an abstractmethod.
        """
        raise NotImplementedError('flatten() is not implemented')

    def direct_snapshot(self, context, snapshot_name, image_format, image_id,
                        base_image_id):
        """Prepare a snapshot for direct reference from glance.

        The implementation of this method is optional and therefore is
        not an abstractmethod.

        :raises: exception.ImageUnacceptable if it cannot be
                 referenced directly in the specified image format
        :returns: URL to be given to glance
        """
        raise NotImplementedError(_('direct_snapshot() is not implemented'))

    def cleanup_direct_snapshot(self, location, also_destroy_volume=False,
                                ignore_errors=False):
        """Performs any cleanup actions required after calling
        direct_snapshot(), for graceful exception handling and the like.

        This should be a no-op on any backend where it is not implemented.
        """
        pass

    def _get_lock_name(self, base):
        """Get an image's name of a base file."""
        return os.path.split(base)[-1]

    @abc.abstractmethod
    def get_model(self, connection):
        """Get the image information model

        :returns: an instance of nova.virt.image.model.Image
        """
        raise NotImplementedError()

    def import_file(self, instance, local_file, remote_name):
        """Import an image from local storage into this backend.

        Import a local file into the store used by this image type. Note that
        this is a noop for stores using local disk (the local file is
        considered "in the store").

        If the image already exists it will be overridden by the new file

        :param local_file: path to the file to import
        :param remote_name: the name for the file in the store
        """

        # NOTE(mikal): this is a noop for now for all stores except RBD, but
        # we should talk about if we want this functionality for everything.
        pass

    def create_snap(self, name):
        """Create a snapshot on the image.  A noop on backends that don't
        support snapshots.

        :param name: name of the snapshot
        """
        pass

    def remove_snap(self, name, ignore_errors=False):
        """Remove a snapshot on the image.  A noop on backends that don't
        support snapshots.

        :param name: name of the snapshot
        :param ignore_errors: don't log errors if the snapshot does not exist
        """
        pass

    def rollback_to_snap(self, name):
        """Rollback the image to the named snapshot. A noop on backends that
        don't support snapshots.

        :param name: name of the snapshot
        """
        pass


class Flat(Image):
    """The Flat backend uses either raw or qcow2 storage. It never uses
    a backing store, so when using qcow2 it copies an image rather than
    creating an overlay. By default it creates raw files, but will use qcow2
    when creating a disk from a qcow2 if force_raw_images is not set in config.
    """
    def __init__(self, instance=None, disk_name=None, path=None):
        self.disk_name = disk_name
        path = (path or os.path.join(libvirt_utils.get_instance_path(instance),
                                     disk_name))
        super(Flat, self).__init__(path, "file", "raw", is_block_dev=False)

        self.preallocate = (
            strutils.to_slug(CONF.preallocate_images) == 'space')
        if self.preallocate:
            self.driver_io = "native"
        self.disk_info_path = os.path.join(os.path.dirname(path), 'disk.info')
        self.correct_format()

    def _get_driver_format(self):
        try:
            data = images.qemu_img_info(self.path)
            return data.file_format
        except exception.InvalidDiskInfo as e:
            LOG.info('Failed to get image info from path %(path)s; '
                     'error: %(error)s',
                     {'path': self.path, 'error': e})
            return 'raw'

    def _supports_encryption(self):
        # NOTE(dgenin): Kernel, ramdisk and disk.config are fetched using
        # the Flat backend regardless of which backend is configured for
        # ephemeral storage. Encryption for the Flat backend is not yet
        # implemented so this loophole is necessary to allow other
        # backends already supporting encryption to function. This can
        # be removed once encryption for Flat is implemented.
        if self.disk_name not in ['kernel', 'ramdisk', 'disk.config']:
            return False
        else:
            return True

    def correct_format(self):
        if os.path.exists(self.path):
            self.driver_format = self.resolve_driver_format()

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        filename = self._get_lock_name(base)

        @utils.synchronized(filename, external=True, lock_path=self.lock_path)
        def copy_raw_image(base, target, size):
            libvirt_utils.copy_image(base, target)
            if size:
                image = imgmodel.LocalFileImage(target,
                                                self.driver_format)
                disk.extend(image, size)

        generating = 'image_id' not in kwargs
        if generating:
            if not self.exists():
                # Generating image in place
                prepare_template(target=self.path, *args, **kwargs)
        else:
            if not os.path.exists(base):
                prepare_template(target=base, *args, **kwargs)

            # NOTE(mikal): Update the mtime of the base file so the image
            # cache manager knows it is in use.
            _update_utime_ignore_eacces(base)
            self.verify_base_size(base, size)
            if not os.path.exists(self.path):
                with fileutils.remove_path_on_error(self.path):
                    copy_raw_image(base, self.path, size)

        self.correct_format()

    def resize_image(self, size):
        image = imgmodel.LocalFileImage(self.path, self.driver_format)
        disk.extend(image, size)

    def snapshot_extract(self, target, out_format):
        images.convert_image(self.path, target, self.driver_format, out_format)

    @staticmethod
    def is_file_in_instance_path():
        return True

    def get_model(self, connection):
        return imgmodel.LocalFileImage(self.path,
                                       imgmodel.FORMAT_RAW)


class Qcow2(Image):
    def __init__(self, instance=None, disk_name=None, path=None):
        path = (path or os.path.join(libvirt_utils.get_instance_path(instance),
                                     disk_name))
        super(Qcow2, self).__init__(path, "file", "qcow2", is_block_dev=False)

        self.preallocate = (
            strutils.to_slug(CONF.preallocate_images) == 'space')
        if self.preallocate:
            self.driver_io = "native"
        self.disk_info_path = os.path.join(os.path.dirname(path), 'disk.info')
        self.resolve_driver_format()

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        filename = self._get_lock_name(base)

        @utils.synchronized(filename, external=True, lock_path=self.lock_path)
        def copy_qcow2_image(base, target, size):
            # TODO(pbrady): Consider copying the cow image here
            # with preallocation=metadata set for performance reasons.
            # This would be keyed on a 'preallocate_images' setting.
            libvirt_utils.create_cow_image(base, target)
            if size:
                image = imgmodel.LocalFileImage(target, imgmodel.FORMAT_QCOW2)
                disk.extend(image, size)

        # Download the unmodified base image unless we already have a copy.
        if not os.path.exists(base):
            prepare_template(target=base, *args, **kwargs)

        # NOTE(ankit): Update the mtime of the base file so the image
        # cache manager knows it is in use.
        _update_utime_ignore_eacces(base)
        self.verify_base_size(base, size)

        legacy_backing_size = None
        legacy_base = base

        # Determine whether an existing qcow2 disk uses a legacy backing by
        # actually looking at the image itself and parsing the output of the
        # backing file it expects to be using.
        if os.path.exists(self.path):
            backing_path = libvirt_utils.get_disk_backing_file(self.path)
            if backing_path is not None:
                backing_file = os.path.basename(backing_path)
                backing_parts = backing_file.rpartition('_')
                if backing_file != backing_parts[-1] and \
                        backing_parts[-1].isdigit():
                    legacy_backing_size = int(backing_parts[-1])
                    legacy_base += '_%d' % legacy_backing_size
                    legacy_backing_size *= units.Gi

        # Create the legacy backing file if necessary.
        if legacy_backing_size:
            if not os.path.exists(legacy_base):
                with fileutils.remove_path_on_error(legacy_base):
                    libvirt_utils.copy_image(base, legacy_base)
                    image = imgmodel.LocalFileImage(legacy_base,
                                                    imgmodel.FORMAT_QCOW2)
                    disk.extend(image, legacy_backing_size)

        if not os.path.exists(self.path):
            with fileutils.remove_path_on_error(self.path):
                copy_qcow2_image(base, self.path, size)

    def resize_image(self, size):
        image = imgmodel.LocalFileImage(self.path, imgmodel.FORMAT_QCOW2)
        disk.extend(image, size)

    def snapshot_extract(self, target, out_format):
        libvirt_utils.extract_snapshot(self.path, 'qcow2',
                                       target,
                                       out_format)

    @staticmethod
    def is_file_in_instance_path():
        return True

    def get_model(self, connection):
        return imgmodel.LocalFileImage(self.path,
                                       imgmodel.FORMAT_QCOW2)


class Lvm(Image):
    @staticmethod
    def escape(filename):
        return filename.replace('_', '__')

    def __init__(self, instance=None, disk_name=None, path=None):
        self.ephemeral_key_uuid = instance.get('ephemeral_key_uuid')

        if self.ephemeral_key_uuid is not None:
            self.key_manager = key_manager.API(CONF)
        else:
            self.key_manager = None

        if path:
            if self.ephemeral_key_uuid is None:
                info = lvm.volume_info(path)
                self.vg = info['VG']
                self.lv = info['LV']
            else:
                self.vg = CONF.libvirt.images_volume_group
        else:
            if not CONF.libvirt.images_volume_group:
                raise RuntimeError(_('You should specify'
                                     ' images_volume_group'
                                     ' flag to use LVM images.'))
            self.vg = CONF.libvirt.images_volume_group
            self.lv = '%s_%s' % (instance.uuid,
                                 self.escape(disk_name))
            if self.ephemeral_key_uuid is None:
                path = os.path.join('/dev', self.vg, self.lv)
            else:
                self.lv_path = os.path.join('/dev', self.vg, self.lv)
                path = '/dev/mapper/' + dmcrypt.volume_name(self.lv)

        super(Lvm, self).__init__(path, "block", "raw", is_block_dev=True)

        # TODO(sbauza): Remove the config option usage and default the
        # LVM logical volume creation to preallocate the full size only.
        self.sparse = CONF.libvirt.sparse_logical_volumes
        self.preallocate = not self.sparse

        if not self.sparse:
            self.driver_io = "native"

    def _supports_encryption(self):
        return True

    def _can_fallocate(self):
        return False

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        def encrypt_lvm_image():
            dmcrypt.create_volume(self.path.rpartition('/')[2],
                                  self.lv_path,
                                  CONF.ephemeral_storage_encryption.cipher,
                                  CONF.ephemeral_storage_encryption.key_size,
                                  key)

        filename = self._get_lock_name(base)

        @utils.synchronized(filename, external=True, lock_path=self.lock_path)
        def create_lvm_image(base, size):
            base_size = disk.get_disk_size(base)
            self.verify_base_size(base, size, base_size=base_size)
            resize = size > base_size if size else False
            size = size if resize else base_size
            lvm.create_volume(self.vg, self.lv,
                                         size, sparse=self.sparse)
            if self.ephemeral_key_uuid is not None:
                encrypt_lvm_image()
            # NOTE: by calling convert_image_unsafe here we're
            # telling qemu-img convert to do format detection on the input,
            # because we don't know what the format is. For example,
            # we might have downloaded a qcow2 image, or created an
            # ephemeral filesystem locally, we just don't know here. Having
            # audited this, all current sources have been sanity checked,
            # either because they're locally generated, or because they have
            # come from images.fetch_to_raw. However, this is major code smell.
            images.convert_image_unsafe(base, self.path, self.driver_format,
                                        run_as_root=True)
            if resize:
                disk.resize2fs(self.path, run_as_root=True)

        generated = 'ephemeral_size' in kwargs
        if self.ephemeral_key_uuid is not None:
            if 'context' in kwargs:
                try:
                    # NOTE(dgenin): Key manager corresponding to the
                    # specific backend catches and reraises an
                    # an exception if key retrieval fails.
                    key = self.key_manager.get(kwargs['context'],
                            self.ephemeral_key_uuid).get_encoded()
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.error("Failed to retrieve ephemeral "
                                  "encryption key")
            else:
                raise exception.InternalError(
                    _("Instance disk to be encrypted but no context provided"))
        # Generate images with specified size right on volume
        if generated and size:
            lvm.create_volume(self.vg, self.lv,
                                         size, sparse=self.sparse)
            with self.remove_volume_on_error(self.path):
                if self.ephemeral_key_uuid is not None:
                    encrypt_lvm_image()
                prepare_template(target=self.path, *args, **kwargs)
        else:
            if not os.path.exists(base):
                prepare_template(target=base, *args, **kwargs)
            with self.remove_volume_on_error(self.path):
                create_lvm_image(base, size)

    # NOTE(nic): Resizing the image is already handled in create_image(),
    # and migrate/resize is not supported with LVM yet, so this is a no-op
    def resize_image(self, size):
        pass

    @contextlib.contextmanager
    def remove_volume_on_error(self, path):
        try:
            yield
        except Exception:
            with excutils.save_and_reraise_exception():
                if self.ephemeral_key_uuid is None:
                    lvm.remove_volumes([path])
                else:
                    dmcrypt.delete_volume(path.rpartition('/')[2])
                    lvm.remove_volumes([self.lv_path])

    def snapshot_extract(self, target, out_format):
        images.convert_image(self.path, target, self.driver_format,
                             out_format, run_as_root=True)

    def get_model(self, connection):
        return imgmodel.LocalBlockImage(self.path)


class Rbd(Image):

    SUPPORTS_CLONE = True

    def __init__(self, instance=None, disk_name=None, path=None):
        if not CONF.libvirt.images_rbd_pool:
            raise RuntimeError(_('You should specify'
                                 ' images_rbd_pool'
                                 ' flag to use rbd images.'))

        if path:
            try:
                self.rbd_name = path.split('/')[1]
            except IndexError:
                raise exception.InvalidDevicePath(path=path)
        else:
            self.rbd_name = '%s_%s' % (instance.uuid, disk_name)

        self.driver = rbd_utils.RBDDriver()

        path = 'rbd:%s/%s' % (self.driver.pool, self.rbd_name)
        if self.driver.rbd_user:
            path += ':id=' + self.driver.rbd_user
        if self.driver.ceph_conf:
            path += ':conf=' + self.driver.ceph_conf

        super(Rbd, self).__init__(path, "block", "rbd", is_block_dev=False)

        self.discard_mode = CONF.libvirt.hw_disk_discard

    def libvirt_info(self, disk_info, cache_mode,
                     extra_specs, hypervisor_version, boot_order=None,
                     disk_unit=None):
        """Get `LibvirtConfigGuestDisk` filled for this image.

        :disk_info: Metadata generated by libvirt.blockinfo.get_disk_mapping
        :cache_mode: Caching mode for this image
        :extra_specs: Instance type extra specs dict.
        :hypervisor_version: the hypervisor version
        :boot_order: Disk device boot order
        """
        info = vconfig.LibvirtConfigGuestDisk()
        disk_bus = disk_info['bus']

        hosts, ports = self.driver.get_mon_addrs()
        info.source_device = disk_info['type']
        info.driver_format = 'raw'
        info.driver_cache = cache_mode
        info.driver_discard = self.discard_mode
        info.target_bus = disk_bus
        info.target_dev = disk_info['dev']
        info.source_type = 'network'
        info.source_protocol = 'rbd'
        info.source_name = '%s/%s' % (self.driver.pool, self.rbd_name)
        info.source_hosts = hosts
        info.source_ports = ports
        info.boot_order = boot_order
        auth_enabled = (self.driver.rbd_user is not None)
        if CONF.libvirt.rbd_secret_uuid:
            info.auth_secret_uuid = CONF.libvirt.rbd_secret_uuid
            auth_enabled = True  # Force authentication locally
            if self.driver.rbd_user:
                info.auth_username = self.driver.rbd_user
        if auth_enabled:
            info.auth_secret_type = 'ceph'
            info.auth_secret_uuid = CONF.libvirt.rbd_secret_uuid

        if disk_bus == 'scsi':
            self.disk_scsi(info, disk_unit)

        self.disk_qos(info, extra_specs)

        return info

    def _can_fallocate(self):
        return False

    def exists(self):
        return self.driver.exists(self.rbd_name)

    def get_disk_size(self, name):
        """Returns the size of the virtual disk in bytes.

        The name argument is ignored since this backend already knows
        its name, and callers may pass a non-existent local file path.
        """
        return self.driver.size(self.rbd_name)

    @staticmethod
    def _remove_non_raw_cache_image(base):
        # NOTE(boxiang): If the cache image file exists, we will check
        # the format of it. Only raw format image is compatible for
        # RBD image backend. If format is not raw, we will remove it
        # at first. We limit force_raw_images to True this time. So
        # the format of new cache image must be raw.
        # We can remove this in 'U' version later.
        if not os.path.exists(base):
            return True
        image_format = images.qemu_img_info(base)
        if image_format.file_format != 'raw':
            try:
                os.remove(base)
            except OSError as e:
                LOG.warning("Ignoring failure to remove %(path)s: "
                            "%(error)s", {'path': base, 'error': e})

    def create_image(self, prepare_template, base, size, *args, **kwargs):

        if not self.exists():
            self._remove_non_raw_cache_image(base)
            prepare_template(target=base, *args, **kwargs)

        # prepare_template() may have cloned the image into a new rbd
        # image already instead of downloading it locally
        if not self.exists():
            self.driver.import_image(base, self.rbd_name)
        self.verify_base_size(base, size)

        if size and size > self.get_disk_size(self.rbd_name):
            self.driver.resize(self.rbd_name, size)

    def resize_image(self, size):
        self.driver.resize(self.rbd_name, size)

    def snapshot_extract(self, target, out_format):
        images.convert_image(self.path, target, 'raw', out_format)

    @staticmethod
    def is_shared_block_storage():
        return True

    def clone(self, context, image_id_or_uri):
        image_meta = IMAGE_API.get(context, image_id_or_uri,
                                   include_locations=True)
        locations = image_meta['locations']

        LOG.debug('Image locations are: %(locs)s', {'locs': locations})

        if image_meta.get('disk_format') not in ['raw', 'iso']:
            reason = _('Image is not raw format')
            raise exception.ImageUnacceptable(image_id=image_id_or_uri,
                                              reason=reason)

        for location in locations:
            if self.driver.is_cloneable(location, image_meta):
                LOG.debug('Selected location: %(loc)s', {'loc': location})
                return self.driver.clone(location, self.rbd_name)

        reason = _('No image locations are accessible')
        raise exception.ImageUnacceptable(image_id=image_id_or_uri,
                                          reason=reason)

    def flatten(self):
        # NOTE(vdrok): only flatten images if they are not already flattened,
        # meaning that parent info is present
        try:
            self.driver.parent_info(self.rbd_name, pool=self.driver.pool)
        except exception.ImageUnacceptable:
            LOG.debug(
                "Image %(img)s from pool %(pool)s has no parent info, "
                "consider it already flat", {
                    'img': self.rbd_name, 'pool': self.driver.pool})
        else:
            self.driver.flatten(self.rbd_name, pool=self.driver.pool)

    def get_model(self, connection):
        secret = None
        if CONF.libvirt.rbd_secret_uuid:
            secretobj = connection.secretLookupByUUIDString(
                CONF.libvirt.rbd_secret_uuid)
            secret = base64.b64encode(secretobj.value())

        hosts, ports = self.driver.get_mon_addrs()
        servers = [str(':'.join(k)) for k in zip(hosts, ports)]

        return imgmodel.RBDImage(self.rbd_name,
                                 self.driver.pool,
                                 self.driver.rbd_user,
                                 secret,
                                 servers)

    def import_file(self, instance, local_file, remote_name):
        name = '%s_%s' % (instance.uuid, remote_name)
        if self.exists():
            self.driver.remove_image(name)
        self.driver.import_image(local_file, name)

    def create_snap(self, name):
        return self.driver.create_snap(self.rbd_name, name)

    def remove_snap(self, name, ignore_errors=False):
        return self.driver.remove_snap(self.rbd_name, name, ignore_errors)

    def rollback_to_snap(self, name):
        return self.driver.rollback_to_snap(self.rbd_name, name)

    def _get_parent_pool(self, context, base_image_id, fsid):
        parent_pool = None
        try:
            # The easy way -- the image is an RBD clone, so use the parent
            # images' storage pool
            parent_pool, _im, _snap = self.driver.parent_info(self.rbd_name)
        except exception.ImageUnacceptable:
            # The hard way -- the image is itself a parent, so ask Glance
            # where it came from
            LOG.debug('No parent info for %s; asking the Image API where its '
                      'store is', base_image_id)
            try:
                image_meta = IMAGE_API.get(context, base_image_id,
                                           include_locations=True)
            except Exception as e:
                LOG.debug('Unable to get image %(image_id)s; error: %(error)s',
                          {'image_id': base_image_id, 'error': e})
                image_meta = {}

            # Find the first location that is in the same RBD cluster
            for location in image_meta.get('locations', []):
                try:
                    parent_fsid, parent_pool, _im, _snap = \
                        self.driver.parse_url(location['url'])
                    if parent_fsid == fsid:
                        break
                    else:
                        parent_pool = None
                except exception.ImageUnacceptable:
                    continue

        if not parent_pool:
            raise exception.ImageUnacceptable(
                    _('Cannot determine the parent storage pool for %s; '
                      'cannot determine where to store images') %
                    base_image_id)

        return parent_pool

    def direct_snapshot(self, context, snapshot_name, image_format,
                        image_id, base_image_id):
        """Creates an RBD snapshot directly.
        """
        fsid = self.driver.get_fsid()
        # NOTE(nic): Nova has zero comprehension of how Glance's image store
        # is configured, but we can infer what storage pool Glance is using
        # by looking at the parent image.  If using authx, write access should
        # be enabled on that pool for the Nova user
        parent_pool = self._get_parent_pool(context, base_image_id, fsid)

        # Snapshot the disk and clone it into Glance's storage pool.  librbd
        # requires that snapshots be set to "protected" in order to clone them
        self.driver.create_snap(self.rbd_name, snapshot_name, protect=True)
        location = {'url': 'rbd://%(fsid)s/%(pool)s/%(image)s/%(snap)s' %
                           dict(fsid=fsid,
                                pool=self.driver.pool,
                                image=self.rbd_name,
                                snap=snapshot_name)}
        try:
            self.driver.clone(location, image_id, dest_pool=parent_pool)
            # Flatten the image, which detaches it from the source snapshot
            self.driver.flatten(image_id, pool=parent_pool)
        finally:
            # all done with the source snapshot, clean it up
            self.cleanup_direct_snapshot(location)

        # Glance makes a protected snapshot called 'snap' on uploaded
        # images and hands it out, so we'll do that too.  The name of
        # the snapshot doesn't really matter, this just uses what the
        # glance-store rbd backend sets (which is not configurable).
        self.driver.create_snap(image_id, 'snap', pool=parent_pool,
                                protect=True)
        return ('rbd://%(fsid)s/%(pool)s/%(image)s/snap' %
                dict(fsid=fsid, pool=parent_pool, image=image_id))

    def cleanup_direct_snapshot(self, location, also_destroy_volume=False,
                                ignore_errors=False):
        """Unprotects and destroys the name snapshot.

        With also_destroy_volume=True, it will also cleanup/destroy the parent
        volume.  This is useful for cleaning up when the target volume fails
        to snapshot properly.
        """
        if location:
            _fsid, _pool, _im, _snap = self.driver.parse_url(location['url'])
            self.driver.remove_snap(_im, _snap, pool=_pool, force=True,
                                    ignore_errors=ignore_errors)
            if also_destroy_volume:
                self.driver.destroy_volume(_im, pool=_pool)


class Ploop(Image):
    def __init__(self, instance=None, disk_name=None, path=None):
        path = (path or os.path.join(libvirt_utils.get_instance_path(instance),
                                     disk_name))
        super(Ploop, self).__init__(path, "file", "ploop", is_block_dev=False)

        self.resolve_driver_format()

    # Create new ploop disk (in case of epehemeral) or
    # copy ploop disk from glance image
    def create_image(self, prepare_template, base, size, *args, **kwargs):
        filename = os.path.basename(base)

        # Copy main file of ploop disk, restore DiskDescriptor.xml for it
        # and resize if necessary
        @utils.synchronized(filename, external=True, lock_path=self.lock_path)
        def _copy_ploop_image(base, target, size):
            # Ploop disk is a directory with data file(root.hds) and
            # DiskDescriptor.xml, so create this dir
            fileutils.ensure_tree(target)
            image_path = os.path.join(target, "root.hds")
            libvirt_utils.copy_image(base, image_path)
            nova.privsep.libvirt.ploop_restore_descriptor(target,
                                                          image_path,
                                                          self.pcs_format)
            if size:
                self.resize_image(size)

        # Generating means that we create empty ploop disk
        generating = 'image_id' not in kwargs
        remove_func = functools.partial(fileutils.delete_if_exists,
                                        remove=shutil.rmtree)
        if generating:
            if os.path.exists(self.path):
                return
            with fileutils.remove_path_on_error(self.path, remove=remove_func):
                prepare_template(target=self.path, *args, **kwargs)
        else:
            # Create ploop disk from glance image
            if not os.path.exists(base):
                prepare_template(target=base, *args, **kwargs)
            else:
                # Disk already exists in cache, just update time
                _update_utime_ignore_eacces(base)
            self.verify_base_size(base, size)

            if os.path.exists(self.path):
                return

            # Get format for ploop disk
            if CONF.force_raw_images:
                self.pcs_format = "raw"
            else:
                image_meta = IMAGE_API.get(kwargs["context"],
                                           kwargs["image_id"])
                format = image_meta.get("disk_format")
                if format == "ploop":
                    self.pcs_format = "expanded"
                elif format == "raw":
                    self.pcs_format = "raw"
                else:
                    reason = _("Ploop image backend doesn't support images in"
                               " %s format. You should either set"
                               " force_raw_images=True in config or upload an"
                               " image in ploop or raw format.") % format
                    raise exception.ImageUnacceptable(
                                        image_id=kwargs["image_id"],
                                        reason=reason)

            with fileutils.remove_path_on_error(self.path, remove=remove_func):
                _copy_ploop_image(base, self.path, size)

    def resize_image(self, size):
        image = imgmodel.LocalFileImage(self.path, imgmodel.FORMAT_PLOOP)
        disk.extend(image, size)

    def snapshot_extract(self, target, out_format):
        img_path = os.path.join(self.path, "root.hds")
        libvirt_utils.extract_snapshot(img_path,
                                       'parallels',
                                       target,
                                       out_format)

    def get_model(self, connection):
        return imgmodel.LocalFileImage(self.path, imgmodel.FORMAT_PLOOP)


class Backend(object):
    def __init__(self, use_cow):
        self.BACKEND = {
            'raw': Flat,
            'flat': Flat,
            'qcow2': Qcow2,
            'lvm': Lvm,
            'rbd': Rbd,
            'ploop': Ploop,
            'default': Qcow2 if use_cow else Flat
        }

    def backend(self, image_type=None):
        if not image_type:
            image_type = CONF.libvirt.images_type
        image = self.BACKEND.get(image_type)
        if not image:
            raise RuntimeError(_('Unknown image_type=%s') % image_type)
        return image

    def by_name(self, instance, name, image_type=None):
        """Return an Image object for a disk with the given name.

        :param instance: the instance which owns this disk
        :param name: The name of the disk
        :param image_type: (Optional) Image type.
                           Default is CONF.libvirt.images_type.
        :return: An Image object for the disk with given name and instance.
        :rtype: Image
        """
        backend = self.backend(image_type)
        return backend(instance=instance, disk_name=name)

    def by_libvirt_path(self, instance, path, image_type=None):
        """Return an Image object for a disk with the given libvirt path.

        :param instance: The instance which owns this disk.
        :param path: The libvirt representation of the image's path.
        :param image_type: (Optional) Image type.
                           Default is CONF.libvirt.images_type.
        :return: An Image object for the given libvirt path.
        :rtype: Image
        """
        backend = self.backend(image_type)
        return backend(instance=instance, path=path)
