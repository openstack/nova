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
import os

import six

from oslo.config import cfg

from nova import exception
from nova.openstack.common import excutils
from nova.openstack.common import fileutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import units
from nova import utils
from nova.virt.disk import api as disk
from nova.virt import images
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import utils as libvirt_utils


try:
    import rados
    import rbd
except ImportError:
    rados = None
    rbd = None


__imagebackend_opts = [
    cfg.StrOpt('images_type',
               default='default',
               help='VM Images format. Acceptable values are: raw, qcow2, lvm,'
                    ' rbd, default. If default is specified,'
                    ' then use_cow_images flag is used instead of this one.',
               deprecated_group='DEFAULT',
               deprecated_name='libvirt_images_type'),
    cfg.StrOpt('images_volume_group',
               help='LVM Volume Group that is used for VM images, when you'
                    ' specify images_type=lvm.',
               deprecated_group='DEFAULT',
               deprecated_name='libvirt_images_volume_group'),
    cfg.BoolOpt('sparse_logical_volumes',
                default=False,
                help='Create sparse logical volumes (with virtualsize)'
                     ' if this flag is set to True.',
                deprecated_group='DEFAULT',
                deprecated_name='libvirt_sparse_logical_volumes'),
    cfg.StrOpt('volume_clear',
               default='zero',
               help='Method used to wipe old volumes (valid options are: '
                    'none, zero, shred)'),
    cfg.IntOpt('volume_clear_size',
               default=0,
               help='Size in MiB to wipe at start of old volumes. 0 => all'),
    cfg.StrOpt('images_rbd_pool',
               default='rbd',
               help='The RADOS pool in which rbd volumes are stored',
               deprecated_group='DEFAULT',
               deprecated_name='libvirt_images_rbd_pool'),
    cfg.StrOpt('images_rbd_ceph_conf',
               default='',  # default determined by librados
               help='Path to the ceph configuration file to use',
               deprecated_group='DEFAULT',
               deprecated_name='libvirt_images_rbd_ceph_conf'),
        ]

CONF = cfg.CONF
CONF.register_opts(__imagebackend_opts, 'libvirt')
CONF.import_opt('image_cache_subdirectory_name', 'nova.virt.imagecache')
CONF.import_opt('preallocate_images', 'nova.virt.driver')

LOG = logging.getLogger(__name__)


@six.add_metaclass(abc.ABCMeta)
class Image(object):

    def __init__(self, source_type, driver_format, is_block_dev=False):
        """Image initialization.

        :source_type: block or file
        :driver_format: raw or qcow2
        :is_block_dev:
        """
        self.source_type = source_type
        self.driver_format = driver_format
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
        info.driver_format = self.driver_format
        driver_name = libvirt_utils.pick_disk_driver_name(hypervisor_version,
                                                          self.is_block_dev)
        info.driver_name = driver_name
        info.source_path = self.path

        tune_items = ['disk_read_bytes_sec', 'disk_read_iops_sec',
            'disk_write_bytes_sec', 'disk_write_iops_sec',
            'disk_total_bytes_sec', 'disk_total_iops_sec']
        # Note(yaguang): Currently, the only tuning available is Block I/O
        # throttling for qemu.
        if self.source_type in ['file', 'block']:
            for key, value in extra_specs.iteritems():
                scope = key.split(':')
                if len(scope) > 1 and scope[0] == 'quota':
                    if scope[1] in tune_items:
                        setattr(info, scope[1], value)
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
                LOG.error(_('Unable to preallocate_images=%(imgs)s at path: '
                            '%(path)s'), {'imgs': CONF.preallocate_images,
                                           'path': self.path})
        return can_fallocate

    @staticmethod
    def verify_base_size(base, size, base_size=0):
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
            base_size = disk.get_disk_size(base)

        if size < base_size:
            msg = _('%(base)s virtual size %(base_size)s '
                    'larger than flavor root disk size %(size)s')
            LOG.error(msg % {'base': base,
                              'base_size': base_size,
                              'size': size})
            raise exception.FlavorDiskTooSmall()

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
                        {'line': line, 'error': unicode(e)})
                raise exception.InvalidDiskInfo(reason=msg)

        @utils.synchronized(self.disk_info_path, external=False,
                            lock_path=self.lock_path)
        def write_to_disk_info_file():
            # Use os.open to create it without group or world write permission.
            fd = os.open(self.disk_info_path, os.O_RDWR | os.O_CREAT, 0o644)
            with os.fdopen(fd, "r+") as disk_info_file:
                line = disk_info_file.read().rstrip()
                dct = _dict_from_line(line)
                if self.path in dct:
                    msg = _("Attempted overwrite of an existing value.")
                    raise exception.InvalidDiskInfo(reason=msg)
                dct.update({self.path: driver_format})
                disk_info_file.seek(0)
                disk_info_file.truncate()
                disk_info_file.write('%s\n' % jsonutils.dumps(dct))
            # Ensure the file is always owned by the nova user so qemu can't
            # write it.
            utils.chown(self.disk_info_path, owner_uid=os.getuid())

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
            raise exception.DiskInfoReadWriteFail(reason=unicode(e))
        return driver_format

    @staticmethod
    def is_shared_block_storage():
        """True if the backend puts images on a shared block storage."""
        return False


class Raw(Image):
    def __init__(self, instance=None, disk_name=None, path=None):
        super(Raw, self).__init__("file", "raw", is_block_dev=False)

        self.path = (path or
                     os.path.join(libvirt_utils.get_instance_path(instance),
                                  disk_name))
        self.preallocate = CONF.preallocate_images != 'none'
        self.disk_info_path = os.path.join(os.path.dirname(self.path),
                                           'disk.info')
        self.correct_format()

    def _get_driver_format(self):
        data = images.qemu_img_info(self.path)
        return data.file_format or 'raw'

    def correct_format(self):
        if os.path.exists(self.path):
            self.driver_format = self.resolve_driver_format()

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        filename = os.path.split(base)[-1]

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
                #Generating image in place
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
        filename = os.path.split(base)[-1]

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


class Lvm(Image):
    @staticmethod
    def escape(filename):
        return filename.replace('_', '__')

    def __init__(self, instance=None, disk_name=None, path=None):
        super(Lvm, self).__init__("block", "raw", is_block_dev=True)

        if path:
            info = libvirt_utils.logical_volume_info(path)
            self.vg = info['VG']
            self.lv = info['LV']
            self.path = path
        else:
            if not CONF.libvirt.images_volume_group:
                raise RuntimeError(_('You should specify'
                                     ' images_volume_group'
                                     ' flag to use LVM images.'))
            self.vg = CONF.libvirt.images_volume_group
            self.lv = '%s_%s' % (instance['uuid'],
                                 self.escape(disk_name))
            self.path = os.path.join('/dev', self.vg, self.lv)

        # TODO(pbrady): possibly deprecate libvirt.sparse_logical_volumes
        # for the more general preallocate_images
        self.sparse = CONF.libvirt.sparse_logical_volumes
        self.preallocate = not self.sparse

    def _can_fallocate(self):
        return False

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        filename = os.path.split(base)[-1]

        @utils.synchronized(filename, external=True, lock_path=self.lock_path)
        def create_lvm_image(base, size):
            base_size = disk.get_disk_size(base)
            self.verify_base_size(base, size, base_size=base_size)
            resize = size > base_size
            size = size if resize else base_size
            libvirt_utils.create_lvm_image(self.vg, self.lv,
                                           size, sparse=self.sparse)
            images.convert_image(base, self.path, 'raw', run_as_root=True)
            if resize:
                disk.resize2fs(self.path, run_as_root=True)

        generated = 'ephemeral_size' in kwargs

        #Generate images with specified size right on volume
        if generated and size:
            libvirt_utils.create_lvm_image(self.vg, self.lv,
                                           size, sparse=self.sparse)
            with self.remove_volume_on_error(self.path):
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
                libvirt_utils.remove_logical_volumes(path)

    def snapshot_extract(self, target, out_format):
        images.convert_image(self.path, target, out_format,
                             run_as_root=True)


class RBDVolumeProxy(object):
    """Context manager for dealing with an existing rbd volume.

    This handles connecting to rados and opening an ioctx automatically, and
    otherwise acts like a librbd Image object.

    The underlying librados client and ioctx can be accessed as the attributes
    'client' and 'ioctx'.
    """
    def __init__(self, driver, name, pool=None):
        client, ioctx = driver._connect_to_rados(pool)
        try:
            self.volume = driver.rbd.Image(ioctx, str(name), snapshot=None)
        except driver.rbd.Error:
            LOG.exception(_("error opening rbd image %s"), name)
            driver._disconnect_from_rados(client, ioctx)
            raise
        self.driver = driver
        self.client = client
        self.ioctx = ioctx

    def __enter__(self):
        return self

    def __exit__(self, type_, value, traceback):
        try:
            self.volume.close()
        finally:
            self.driver._disconnect_from_rados(self.client, self.ioctx)

    def __getattr__(self, attrib):
        return getattr(self.volume, attrib)


def ascii_str(s):
    """Convert a string to ascii, or return None if the input is None.

    This is useful when a parameter is None by default, or a string. LibRBD
    only accepts ascii, hence the need for conversion.
    """
    if s is None:
        return s
    return str(s)


class Rbd(Image):
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
        self.ceph_conf = ascii_str(CONF.libvirt.images_rbd_ceph_conf)
        self.rbd_user = ascii_str(CONF.libvirt.rbd_user)
        self.rbd = kwargs.get('rbd', rbd)
        self.rados = kwargs.get('rados', rados)

        self.path = 'rbd:%s/%s' % (self.pool, self.rbd_name)
        if self.rbd_user:
            self.path += ':id=' + self.rbd_user
        if self.ceph_conf:
            self.path += ':conf=' + self.ceph_conf

    def _connect_to_rados(self, pool=None):
        client = self.rados.Rados(rados_id=self.rbd_user,
                                  conffile=self.ceph_conf)
        try:
            client.connect()
            pool_to_open = str(pool or self.pool)
            ioctx = client.open_ioctx(pool_to_open)
            return client, ioctx
        except self.rados.Error:
            # shutdown cannot raise an exception
            client.shutdown()
            raise

    def _disconnect_from_rados(self, client, ioctx):
        # closing an ioctx cannot raise an exception
        ioctx.close()
        client.shutdown()

    def _supports_layering(self):
        return hasattr(self.rbd, 'RBD_FEATURE_LAYERING')

    def _ceph_args(self):
        args = []
        if self.rbd_user:
            args.extend(['--id', self.rbd_user])
        if self.ceph_conf:
            args.extend(['--conf', self.ceph_conf])
        return args

    def _get_mon_addrs(self):
        args = ['ceph', 'mon', 'dump', '--format=json'] + self._ceph_args()
        out, _ = utils.execute(*args)
        lines = out.split('\n')
        if lines[0].startswith('dumped monmap epoch'):
            lines = lines[1:]
        monmap = jsonutils.loads('\n'.join(lines))
        addrs = [mon['addr'] for mon in monmap['mons']]
        hosts = []
        ports = []
        for addr in addrs:
            host_port = addr[:addr.rindex('/')]
            host, port = host_port.rsplit(':', 1)
            hosts.append(host.strip('[]'))
            ports.append(port)
        return hosts, ports

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

        hosts, ports = self._get_mon_addrs()
        info.device_type = device_type
        info.driver_format = 'raw'
        info.driver_cache = cache_mode
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
        rbd_volumes = libvirt_utils.list_rbd_volumes(self.pool)
        for vol in rbd_volumes:
            if vol.startswith(self.rbd_name):
                return True

        return False

    def _resize(self, volume_name, size):
        with RBDVolumeProxy(self, volume_name) as vol:
            vol.resize(int(size))

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        if self.rbd is None:
            raise RuntimeError(_('rbd python libraries not found'))

        if not os.path.exists(base):
            prepare_template(target=base, max_size=size, *args, **kwargs)
        else:
            self.verify_base_size(base, size)

        # keep using the command line import instead of librbd since it
        # detects zeroes to preserve sparseness in the image
        args = ['--pool', self.pool, base, self.rbd_name]
        if self._supports_layering():
            args += ['--new-format']
        args += self._ceph_args()
        libvirt_utils.import_rbd_image(*args)

        base_size = disk.get_disk_size(base)

        if size and size > base_size:
            self._resize(self.rbd_name, size)

    def snapshot_extract(self, target, out_format):
        images.convert_image(self.path, target, out_format)

    @staticmethod
    def is_shared_block_storage():
        return True


class Backend(object):
    def __init__(self, use_cow):
        self.BACKEND = {
            'raw': Raw,
            'qcow2': Qcow2,
            'lvm': Lvm,
            'rbd': Rbd,
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

    def snapshot(self, disk_path, image_type=None):
        """Returns snapshot for given image

        :path: path to image
        :image_type: type of image
        """
        backend = self.backend(image_type)
        return backend(path=disk_path)
