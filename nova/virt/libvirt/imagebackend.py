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
import contextlib
import functools
import os
import shutil

from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import units
import six

from nova import exception
from nova.i18n import _
from nova.i18n import _LE, _LI
from nova import image
from nova import keymgr
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.disk import api as disk
from nova.virt import images
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import dmcrypt
from nova.virt.libvirt import lvm
from nova.virt.libvirt import rbd_utils
from nova.virt.libvirt import utils as libvirt_utils

__imagebackend_opts = [
    cfg.StrOpt('images_type',
               default='default',
               help='VM Images format. Acceptable values are: raw, qcow2, lvm,'
                    ' rbd, default. If default is specified,'
                    ' then use_cow_images flag is used instead of this one.'),
    cfg.StrOpt('images_volume_group',
               help='LVM Volume Group that is used for VM images, when you'
                    ' specify images_type=lvm.'),
    cfg.BoolOpt('sparse_logical_volumes',
                default=False,
                help='Create sparse logical volumes (with virtualsize)'
                     ' if this flag is set to True.'),
    cfg.StrOpt('images_rbd_pool',
               default='rbd',
               help='The RADOS pool in which rbd volumes are stored'),
    cfg.StrOpt('images_rbd_ceph_conf',
               default='',  # default determined by librados
               help='Path to the ceph configuration file to use'),
    cfg.StrOpt('hw_disk_discard',
               help='Discard option for nova managed disks (valid options '
                    'are: ignore, unmap). Need Libvirt(1.0.6) Qemu1.5 '
                    '(raw format) Qemu1.6(qcow2 format)'),
        ]

CONF = cfg.CONF
CONF.register_opts(__imagebackend_opts, 'libvirt')
CONF.import_opt('image_cache_subdirectory_name', 'nova.virt.imagecache')
CONF.import_opt('preallocate_images', 'nova.virt.driver')
CONF.import_opt('enabled', 'nova.compute.api',
                group='ephemeral_storage_encryption')
CONF.import_opt('cipher', 'nova.compute.api',
                group='ephemeral_storage_encryption')
CONF.import_opt('key_size', 'nova.compute.api',
                group='ephemeral_storage_encryption')
CONF.import_opt('rbd_user', 'nova.virt.libvirt.volume', group='libvirt')
CONF.import_opt('rbd_secret_uuid', 'nova.virt.libvirt.volume', group='libvirt')

LOG = logging.getLogger(__name__)
IMAGE_API = image.API()


@six.add_metaclass(abc.ABCMeta)
class Image(object):

    SUPPORTS_CLONE = False

    def __init__(self, source_type, driver_format, is_block_dev=False):
        """Image initialization.

        :source_type: block or file
        :driver_format: raw or qcow2
        :is_block_dev:
        """
        if (CONF.ephemeral_storage_encryption.enabled and
                not self._supports_encryption()):
            raise exception.NovaException(_('Incompatible settings: '
                                  'ephemeral storage encryption is supported '
                                  'only for LVM images.'))

        self.source_type = source_type
        self.driver_format = driver_format
        self.discard_mode = get_hw_disk_discard(CONF.libvirt.hw_disk_discard)
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

    def libvirt_info(self, disk_bus, disk_dev, device_type, cache_mode,
            extra_specs, hypervisor_version):
        """Get `LibvirtConfigGuestDisk` filled for this image.

        :disk_dev: Disk bus device name
        :disk_bus: Disk bus type
        :device_type: Device type for this image.
        :cache_mode: Caching mode for this image
        :extra_specs: Instance type extra specs dict.
        """
        info = vconfig.LibvirtConfigGuestDisk()
        info.source_type = self.source_type
        info.source_device = device_type
        info.target_bus = disk_bus
        info.target_dev = disk_dev
        info.driver_cache = cache_mode
        info.driver_discard = self.discard_mode
        info.driver_format = self.driver_format
        driver_name = libvirt_utils.pick_disk_driver_name(hypervisor_version,
                                                          self.is_block_dev)
        info.driver_name = driver_name
        info.source_path = self.path

        tune_items = ['disk_read_bytes_sec', 'disk_read_iops_sec',
            'disk_write_bytes_sec', 'disk_write_iops_sec',
            'disk_total_bytes_sec', 'disk_total_iops_sec']
        for key, value in extra_specs.iteritems():
            scope = key.split(':')
            if len(scope) > 1 and scope[0] == 'quota':
                if scope[1] in tune_items:
                    setattr(info, scope[1], value)
        return info

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

    def check_image_exists(self):
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
        @utils.synchronized(filename, external=True, lock_path=self.lock_path)
        def fetch_func_sync(target, *args, **kwargs):
            # The image may have been fetched while a subsequent
            # call was waiting to obtain the lock.
            if not os.path.exists(target):
                fetch_func(target=target, *args, **kwargs)

        base_dir = os.path.join(CONF.instances_path,
                                CONF.image_cache_subdirectory_name)
        if not os.path.exists(base_dir):
            fileutils.ensure_tree(base_dir)
        base = os.path.join(base_dir, filename)

        if not self.check_image_exists() or not os.path.exists(base):
            self.create_image(fetch_func_sync, base, size,
                              *args, **kwargs)

        if (size and self.preallocate and self._can_fallocate() and
                os.access(self.path, os.W_OK)):
            utils.execute('fallocate', '-n', '-l', size, self.path)

    def _can_fallocate(self):
        """Check once per class, whether fallocate(1) is available,
           and that the instances directory supports fallocate(2).
        """
        can_fallocate = getattr(self.__class__, 'can_fallocate', None)
        if can_fallocate is None:
            _out, err = utils.trycmd('fallocate', '-n', '-l', '1',
                                     self.path + '.fallocate_test')
            fileutils.delete_if_exists(self.path + '.fallocate_test')
            can_fallocate = not err
            self.__class__.can_fallocate = can_fallocate
            if not can_fallocate:
                LOG.error(_LE('Unable to preallocate_images=%(imgs)s at path: '
                              '%(path)s'), {'imgs': CONF.preallocate_images,
                                            'path': self.path})
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
            msg = _LE('%(base)s virtual size %(base_size)s '
                      'larger than flavor root disk size %(size)s')
            LOG.error(msg % {'base': base,
                              'base_size': base_size,
                              'size': size})
            raise exception.FlavorDiskTooSmall()

    def get_disk_size(self, name):
        disk.get_disk_size(name)

    def snapshot_extract(self, target, out_format):
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
                    for path, driver_format in dct.iteritems():
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

    def _get_lock_name(self, base):
        """Get an image's name of a base file."""
        return os.path.split(base)[-1]


class Raw(Image):
    def __init__(self, instance=None, disk_name=None, path=None):
        self.disk_name = disk_name
        super(Raw, self).__init__("file", "raw", is_block_dev=False)

        self.path = (path or
                     os.path.join(libvirt_utils.get_instance_path(instance),
                                  disk_name))
        self.preallocate = CONF.preallocate_images != 'none'
        self.disk_info_path = os.path.join(os.path.dirname(self.path),
                                           'disk.info')
        self.correct_format()

    def _get_driver_format(self):
        try:
            data = images.qemu_img_info(self.path)
            return data.file_format
        except exception.InvalidDiskInfo as e:
            LOG.info(_LI('Failed to get image info from path %(path)s; '
                         'error: %(error)s'),
                      {'path': self.path,
                       'error': e})
            return 'raw'

    def _supports_encryption(self):
        # NOTE(dgenin): Kernel, ramdisk and disk.config are fetched using
        # the Raw backend regardless of which backend is configured for
        # ephemeral storage. Encryption for the Raw backend is not yet
        # implemented so this loophole is necessary to allow other
        # backends already supporting encryption to function. This can
        # be removed once encryption for Raw is implemented.
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
                # class Raw is misnamed, format may not be 'raw' in all cases
                use_cow = self.driver_format == 'qcow2'
                disk.extend(target, size, use_cow=use_cow)

        generating = 'image_id' not in kwargs
        if generating:
            if not self.check_image_exists():
                # Generating image in place
                prepare_template(target=self.path, *args, **kwargs)
        else:
            if not os.path.exists(base):
                prepare_template(target=base, max_size=size, *args, **kwargs)
            self.verify_base_size(base, size)
            if not os.path.exists(self.path):
                with fileutils.remove_path_on_error(self.path):
                    copy_raw_image(base, self.path, size)
        self.correct_format()

    def snapshot_extract(self, target, out_format):
        images.convert_image(self.path, target, out_format)

    @staticmethod
    def is_file_in_instance_path():
        return True


class Qcow2(Image):
    def __init__(self, instance=None, disk_name=None, path=None):
        super(Qcow2, self).__init__("file", "qcow2", is_block_dev=False)

        self.path = (path or
                     os.path.join(libvirt_utils.get_instance_path(instance),
                                  disk_name))
        self.preallocate = CONF.preallocate_images != 'none'
        self.disk_info_path = os.path.join(os.path.dirname(self.path),
                                           'disk.info')
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
                disk.extend(target, size, use_cow=True)

        # Download the unmodified base image unless we already have a copy.
        if not os.path.exists(base):
            prepare_template(target=base, max_size=size, *args, **kwargs)
        else:
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
                    disk.extend(legacy_base, legacy_backing_size, use_cow=True)

        if not os.path.exists(self.path):
            with fileutils.remove_path_on_error(self.path):
                copy_qcow2_image(base, self.path, size)

    def snapshot_extract(self, target, out_format):
        libvirt_utils.extract_snapshot(self.path, 'qcow2',
                                       target,
                                       out_format)

    @staticmethod
    def is_file_in_instance_path():
        return True


class Lvm(Image):
    @staticmethod
    def escape(filename):
        return filename.replace('_', '__')

    def __init__(self, instance=None, disk_name=None, path=None):
        super(Lvm, self).__init__("block", "raw", is_block_dev=True)

        self.ephemeral_key_uuid = instance.get('ephemeral_key_uuid')

        if self.ephemeral_key_uuid is not None:
            self.key_manager = keymgr.API()
        else:
            self.key_manager = None

        if path:
            self.path = path
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
            self.lv = '%s_%s' % (instance['uuid'],
                                 self.escape(disk_name))
            if self.ephemeral_key_uuid is None:
                self.path = os.path.join('/dev', self.vg, self.lv)
            else:
                self.lv_path = os.path.join('/dev', self.vg, self.lv)
                self.path = '/dev/mapper/' + dmcrypt.volume_name(self.lv)

        # TODO(pbrady): possibly deprecate libvirt.sparse_logical_volumes
        # for the more general preallocate_images
        self.sparse = CONF.libvirt.sparse_logical_volumes
        self.preallocate = not self.sparse

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
            resize = size > base_size
            size = size if resize else base_size
            lvm.create_volume(self.vg, self.lv,
                                         size, sparse=self.sparse)
            if self.ephemeral_key_uuid is not None:
                encrypt_lvm_image()
            images.convert_image(base, self.path, 'raw', run_as_root=True)
            if resize:
                disk.resize2fs(self.path, run_as_root=True)

        generated = 'ephemeral_size' in kwargs
        if self.ephemeral_key_uuid is not None:
            if 'context' in kwargs:
                try:
                    # NOTE(dgenin): Key manager corresponding to the
                    # specific backend catches and reraises an
                    # an exception if key retrieval fails.
                    key = self.key_manager.get_key(kwargs['context'],
                            self.ephemeral_key_uuid).get_encoded()
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_LE("Failed to retrieve ephemeral encryption"
                                      " key"))
            else:
                raise exception.NovaException(
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
                prepare_template(target=base, max_size=size, *args, **kwargs)
            with self.remove_volume_on_error(self.path):
                create_lvm_image(base, size)

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
        images.convert_image(self.path, target, out_format,
                             run_as_root=True)


class Rbd(Image):

    SUPPORTS_CLONE = True

    def __init__(self, instance=None, disk_name=None, path=None, **kwargs):
        super(Rbd, self).__init__("block", "rbd", is_block_dev=False)
        if path:
            try:
                self.rbd_name = path.split('/')[1]
            except IndexError:
                raise exception.InvalidDevicePath(path=path)
        else:
            self.rbd_name = '%s_%s' % (instance['uuid'], disk_name)

        if not CONF.libvirt.images_rbd_pool:
            raise RuntimeError(_('You should specify'
                                 ' images_rbd_pool'
                                 ' flag to use rbd images.'))
        self.pool = CONF.libvirt.images_rbd_pool
        self.discard_mode = get_hw_disk_discard(
                CONF.libvirt.hw_disk_discard)
        self.rbd_user = CONF.libvirt.rbd_user
        self.ceph_conf = CONF.libvirt.images_rbd_ceph_conf

        self.driver = rbd_utils.RBDDriver(
            pool=self.pool,
            ceph_conf=self.ceph_conf,
            rbd_user=self.rbd_user)

        self.path = 'rbd:%s/%s' % (self.pool, self.rbd_name)
        if self.rbd_user:
            self.path += ':id=' + self.rbd_user
        if self.ceph_conf:
            self.path += ':conf=' + self.ceph_conf

    def libvirt_info(self, disk_bus, disk_dev, device_type, cache_mode,
            extra_specs, hypervisor_version):
        """Get `LibvirtConfigGuestDisk` filled for this image.

        :disk_dev: Disk bus device name
        :disk_bus: Disk bus type
        :device_type: Device type for this image.
        :cache_mode: Caching mode for this image
        :extra_specs: Instance type extra specs dict.
        """
        info = vconfig.LibvirtConfigGuestDisk()

        hosts, ports = self.driver.get_mon_addrs()
        info.source_device = device_type
        info.driver_format = 'raw'
        info.driver_cache = cache_mode
        info.driver_discard = self.discard_mode
        info.target_bus = disk_bus
        info.target_dev = disk_dev
        info.source_type = 'network'
        info.source_protocol = 'rbd'
        info.source_name = '%s/%s' % (self.pool, self.rbd_name)
        info.source_hosts = hosts
        info.source_ports = ports
        auth_enabled = (CONF.libvirt.rbd_user is not None)
        if CONF.libvirt.rbd_secret_uuid:
            info.auth_secret_uuid = CONF.libvirt.rbd_secret_uuid
            auth_enabled = True  # Force authentication locally
            if CONF.libvirt.rbd_user:
                info.auth_username = CONF.libvirt.rbd_user
        if auth_enabled:
            info.auth_secret_type = 'ceph'
            info.auth_secret_uuid = CONF.libvirt.rbd_secret_uuid
        return info

    def _can_fallocate(self):
        return False

    def check_image_exists(self):
        return self.driver.exists(self.rbd_name)

    def get_disk_size(self, name):
        """Returns the size of the virtual disk in bytes.

        The name argument is ignored since this backend already knows
        its name, and callers may pass a non-existent local file path.
        """
        return self.driver.size(self.rbd_name)

    def create_image(self, prepare_template, base, size, *args, **kwargs):

        if not self.check_image_exists():
            prepare_template(target=base, max_size=size, *args, **kwargs)
        else:
            self.verify_base_size(base, size)

        # prepare_template() may have cloned the image into a new rbd
        # image already instead of downloading it locally
        if not self.check_image_exists():
            self.driver.import_image(base, self.rbd_name)

        if size and size > self.get_disk_size(self.rbd_name):
            self.driver.resize(self.rbd_name, size)

    def snapshot_extract(self, target, out_format):
        images.convert_image(self.path, target, out_format)

    @staticmethod
    def is_shared_block_storage():
        return True

    def clone(self, context, image_id_or_uri):
        if not self.driver.supports_layering():
            reason = _('installed version of librbd does not support cloning')
            raise exception.ImageUnacceptable(image_id=image_id_or_uri,
                                              reason=reason)

        image_meta = IMAGE_API.get(context, image_id_or_uri,
                                   include_locations=True)
        locations = image_meta['locations']

        LOG.debug('Image locations are: %(locs)s' % {'locs': locations})

        if image_meta.get('disk_format') not in ['raw', 'iso']:
            reason = _('Image is not raw format')
            raise exception.ImageUnacceptable(image_id=image_id_or_uri,
                                              reason=reason)

        for location in locations:
            if self.driver.is_cloneable(location, image_meta):
                return self.driver.clone(location, self.rbd_name)

        reason = _('No image locations are accessible')
        raise exception.ImageUnacceptable(image_id=image_id_or_uri,
                                          reason=reason)


class Ploop(Image):
    def __init__(self, instance=None, disk_name=None, path=None):
        super(Ploop, self).__init__("file", "ploop", is_block_dev=False)

        self.path = (path or
                     os.path.join(libvirt_utils.get_instance_path(instance),
                                  disk_name))
        self.resolve_driver_format()

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        filename = os.path.split(base)[-1]

        @utils.synchronized(filename, external=True, lock_path=self.lock_path)
        def create_ploop_image(base, target, size):
            image_path = os.path.join(target, "root.hds")
            libvirt_utils.copy_image(base, image_path)
            utils.execute('ploop', 'restore-descriptor', '-f', self.pcs_format,
                          target, image_path)
            if size:
                dd_path = os.path.join(self.path, "DiskDescriptor.xml")
                utils.execute('ploop', 'grow', '-s', '%dK' % (size >> 10),
                              dd_path, run_as_root=True)

        if not os.path.exists(self.path):
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
                    reason = _("PCS doesn't support images in %s format."
                                " You should either set force_raw_images=True"
                                " in config or upload an image in ploop"
                                " or raw format.") % format
                    raise exception.ImageUnacceptable(
                                        image_id=kwargs["image_id"],
                                        reason=reason)

        if not os.path.exists(base):
            prepare_template(target=base, max_size=size, *args, **kwargs)
        self.verify_base_size(base, size)

        if os.path.exists(self.path):
            return

        fileutils.ensure_tree(self.path)

        remove_func = functools.partial(fileutils.delete_if_exists,
                                        remove=shutil.rmtree)
        with fileutils.remove_path_on_error(self.path, remove=remove_func):
            create_ploop_image(base, self.path, size)


class Backend(object):
    def __init__(self, use_cow):
        self.BACKEND = {
            'raw': Raw,
            'qcow2': Qcow2,
            'lvm': Lvm,
            'rbd': Rbd,
            'ploop': Ploop,
            'default': Qcow2 if use_cow else Raw
        }

    def backend(self, image_type=None):
        if not image_type:
            image_type = CONF.libvirt.images_type
        image = self.BACKEND.get(image_type)
        if not image:
            raise RuntimeError(_('Unknown image_type=%s') % image_type)
        return image

    def image(self, instance, disk_name, image_type=None):
        """Constructs image for selected backend

        :instance: Instance name.
        :name: Image name.
        :image_type: Image type.
                     Optional, is CONF.libvirt.images_type by default.
        """
        backend = self.backend(image_type)
        return backend(instance=instance, disk_name=disk_name)

    def snapshot(self, instance, disk_path, image_type=None):
        """Returns snapshot for given image

        :path: path to image
        :image_type: type of image
        """
        backend = self.backend(image_type)
        return backend(instance=instance, path=disk_path)


def get_hw_disk_discard(hw_disk_discard):
    """Check valid and get hw_disk_discard value from Conf.
    """
    if hw_disk_discard and hw_disk_discard not in ('unmap', 'ignore'):
        raise RuntimeError(_('Unknown hw_disk_discard=%s') % hw_disk_discard)
    return hw_disk_discard
