# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import excutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.disk import api as disk
from nova.virt.libvirt import config
from nova.virt.libvirt import utils as libvirt_utils


__imagebackend_opts = [
    cfg.StrOpt('libvirt_images_type',
            default='default',
            help='VM Images format. Acceptable values are: raw, qcow2, lvm,'
                 ' default. If default is specified,'
                 ' then use_cow_images flag is used instead of this one.'),
    cfg.StrOpt('libvirt_images_volume_group',
            default=None,
            help='LVM Volume Group that is used for VM images, when you'
                 ' specify libvirt_images_type=lvm.'),
    cfg.BoolOpt('libvirt_sparse_logical_volumes',
            default=False,
            help='Create sparse logical volumes (with virtualsize)'
                 ' if this flag is set to True.'),
        ]

FLAGS = flags.FLAGS
FLAGS.register_opts(__imagebackend_opts)

LOG = logging.getLogger(__name__)


class Image(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, source_type, driver_format, is_block_dev=False):
        """Image initialization.

        :source_type: block or file
        :driver_format: raw or qcow2
        :is_block_dev:
        """
        self.source_type = source_type
        self.driver_format = driver_format
        self.is_block_dev = is_block_dev

        # NOTE(mikal): We need a lock directory which is shared along with
        # instance files, to cover the scenario where multiple compute nodes
        # are trying to create a base file at the same time
        self.lock_path = os.path.join(FLAGS.instances_path, 'locks')

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

    def libvirt_info(self, disk_bus, disk_dev, device_type, cache_mode):
        """Get `LibvirtConfigGuestDisk` filled for this image.

        :disk_dev: Disk bus device name
        :disk_bus: Disk bus type
        :device_type: Device type for this image.
        :cache_mode: Caching mode for this image
        """
        info = config.LibvirtConfigGuestDisk()
        info.source_type = self.source_type
        info.source_device = device_type
        info.target_bus = disk_bus
        info.target_dev = disk_dev
        info.driver_cache = cache_mode
        info.driver_format = self.driver_format
        driver_name = libvirt_utils.pick_disk_driver_name(self.is_block_dev)
        info.driver_name = driver_name
        info.source_path = self.path
        return info

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
        def call_if_not_exists(target, *args, **kwargs):
            if not os.path.exists(target):
                fetch_func(target=target, *args, **kwargs)

        if not os.path.exists(self.path):
            base_dir = os.path.join(FLAGS.instances_path, '_base')
            if not os.path.exists(base_dir):
                utils.ensure_tree(base_dir)
            base = os.path.join(base_dir, filename)

            self.create_image(call_if_not_exists, base, size,
                              *args, **kwargs)


class Raw(Image):
    def __init__(self, instance, name):
        super(Raw, self).__init__("file", "raw", is_block_dev=False)

        self.path = os.path.join(FLAGS.instances_path,
                                 instance, name)

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        @utils.synchronized(base, external=True, lock_path=self.lock_path)
        def copy_raw_image(base, target, size):
            libvirt_utils.copy_image(base, target)
            if size:
                disk.extend(target, size)

        generating = 'image_id' not in kwargs
        if generating:
            #Generating image in place
            prepare_template(target=self.path, *args, **kwargs)
        else:
            prepare_template(target=base, *args, **kwargs)
            with utils.remove_path_on_error(self.path):
                copy_raw_image(base, self.path, size)


class Qcow2(Image):
    def __init__(self, instance, name):
        super(Qcow2, self).__init__("file", "qcow2", is_block_dev=False)

        self.path = os.path.join(FLAGS.instances_path,
                                 instance, name)

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        @utils.synchronized(base, external=True, lock_path=self.lock_path)
        def copy_qcow2_image(base, target, size):
            qcow2_base = base
            if size:
                size_gb = size / (1024 * 1024 * 1024)
                qcow2_base += '_%d' % size_gb
                if not os.path.exists(qcow2_base):
                    with utils.remove_path_on_error(qcow2_base):
                        libvirt_utils.copy_image(base, qcow2_base)
                        disk.extend(qcow2_base, size)
            libvirt_utils.create_cow_image(qcow2_base, target)

        prepare_template(target=base, *args, **kwargs)
        # NOTE(cfb): Having a flavor that sets the root size to 0 and having
        #            nova effectively ignore that size and use the size of the
        #            image is considered a feature at this time, not a bug.
        if size and size < disk.get_disk_size(base):
            LOG.error('%s virtual size larger than flavor root disk size %s' %
                      (base, size))
            raise exception.ImageTooLarge()
        with utils.remove_path_on_error(self.path):
            copy_qcow2_image(base, self.path, size)


class Lvm(Image):
    @staticmethod
    def escape(filename):
        return filename.replace('_', '__')

    def __init__(self, instance, name):
        super(Lvm, self).__init__("block", "raw", is_block_dev=True)

        if not FLAGS.libvirt_images_volume_group:
            raise RuntimeError(_('You should specify'
                               ' libvirt_images_volume_group'
                               ' flag to use LVM images.'))
        self.vg = FLAGS.libvirt_images_volume_group
        self.lv = '%s_%s' % (self.escape(instance),
                             self.escape(name))
        self.path = os.path.join('/dev', self.vg, self.lv)
        self.sparse = FLAGS.libvirt_sparse_logical_volumes

    def create_image(self, prepare_template, base, size, *args, **kwargs):
        @utils.synchronized(base, external=True, lock_path=self.lock_path)
        def create_lvm_image(base, size):
            base_size = disk.get_disk_size(base)
            resize = size > base_size
            size = size if resize else base_size
            libvirt_utils.create_lvm_image(self.vg, self.lv,
                                           size, sparse=self.sparse)
            cmd = ('dd', 'if=%s' % base, 'of=%s' % self.path, 'bs=4M')
            utils.execute(*cmd, run_as_root=True)
            if resize:
                disk.resize2fs(self.path)

        generated = 'ephemeral_size' in kwargs

        #Generate images with specified size right on volume
        if generated and size:
            libvirt_utils.create_lvm_image(self.vg, self.lv,
                                           size, sparse=self.sparse)
            with self.remove_volume_on_error(self.path):
                prepare_template(target=self.path, *args, **kwargs)
        else:
            prepare_template(target=base, *args, **kwargs)
            with self.remove_volume_on_error(self.path):
                create_lvm_image(base, size)

    @contextlib.contextmanager
    def remove_volume_on_error(self, path):
        try:
            yield
        except Exception:
            with excutils.save_and_reraise_exception():
                libvirt_utils.remove_logical_volumes(path)


class Backend(object):
    def __init__(self, use_cow):
        self.BACKEND = {
            'raw': Raw,
            'qcow2': Qcow2,
            'lvm': Lvm,
            'default': Qcow2 if use_cow else Raw
        }

    def image(self, instance, name, image_type=None):
        """Constructs image for selected backend

        :instance: Instance name.
        :name: Image name.
        :image_type: Image type.
        Optional, is FLAGS.libvirt_images_type by default.
        """
        if not image_type:
            image_type = FLAGS.libvirt_images_type
        image = self.BACKEND.get(image_type)
        if not image:
            raise RuntimeError(_('Unknown image_type=%s') % image_type)
        return image(instance, name)
