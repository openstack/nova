# Copyright 2012 Michael Still and Canonical Inc
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

"""Image cache manager.

The cache manager implements the specification at
http://wiki.openstack.org/nova-image-cache-management.

"""

import hashlib
import os
import re
import time

from oslo_concurrency import lockutils
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import encodeutils
import six

import nova.conf
import nova.privsep.path
from nova import utils
from nova.virt import imagecache
from nova.virt.libvirt import utils as libvirt_utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


def get_cache_fname(image_id):
    """Return a filename based on the SHA1 hash of a given image ID.

    Image files stored in the _base directory that match this pattern
    are considered for cleanup by the image cache manager. The cache
    manager considers the file to be in use if it matches an instance's
    image_ref, kernel_id or ramdisk_id property.
    """
    return hashlib.sha1(image_id.encode('utf-8')).hexdigest()


class ImageCacheManager(imagecache.ImageCacheManager):
    def __init__(self):
        super(ImageCacheManager, self).__init__()
        self.lock_path = os.path.join(CONF.instances_path, 'locks')
        self._reset_state()

    def _reset_state(self):
        """Reset state variables used for each pass."""

        self.used_images = {}
        self.instance_names = set()

        self.back_swap_images = set()
        self.used_swap_images = set()

        self.active_base_files = []
        self.originals = []
        self.removable_base_files = []
        self.unexplained_images = []

    def _store_image(self, base_dir, ent, original=False):
        """Store a base image for later examination."""
        entpath = os.path.join(base_dir, ent)
        if os.path.isfile(entpath):
            self.unexplained_images.append(entpath)
            if original:
                self.originals.append(entpath)

    def _store_swap_image(self, ent):
        """Store base swap images for later examination."""
        names = ent.split('_')
        if len(names) == 2 and names[0] == 'swap':
            if len(names[1]) > 0 and names[1].isdigit():
                LOG.debug('Adding %s into backend swap images', ent)
                self.back_swap_images.add(ent)

    def _scan_base_images(self, base_dir):
        """Scan base images in base_dir and call _store_image or
        _store_swap_image on each as appropriate. These methods populate
        self.unexplained_images, self.originals, and self.back_swap_images.
        """

        if six.PY2:
            digest_size = hashlib.sha1().digestsize * 2
        else:
            digest_size = hashlib.sha1().digest_size * 2
        for ent in os.listdir(base_dir):
            if len(ent) == digest_size:
                self._store_image(base_dir, ent, original=True)

            elif len(ent) > digest_size + 2 and ent[digest_size] == '_':
                self._store_image(base_dir, ent, original=False)

            else:
                self._store_swap_image(ent)

    def _list_backing_images(self):
        """List the backing images currently in use."""
        inuse_images = []
        for ent in os.listdir(CONF.instances_path):
            if ent in self.instance_names:
                LOG.debug('%s is a valid instance name', ent)
                disk_path = os.path.join(CONF.instances_path, ent, 'disk')
                if os.path.exists(disk_path):
                    LOG.debug('%s has a disk file', ent)
                    try:
                        backing_file = libvirt_utils.get_disk_backing_file(
                            disk_path)
                    except processutils.ProcessExecutionError:
                        # (for bug 1261442)
                        if not os.path.exists(disk_path):
                            LOG.debug('Failed to get disk backing file: %s',
                                      disk_path)
                            continue
                        else:
                            raise
                    LOG.debug('Instance %(instance)s is backed by '
                              '%(backing)s',
                              {'instance': ent,
                               'backing': backing_file})

                    if backing_file:
                        backing_path = os.path.join(
                            CONF.instances_path,
                            CONF.image_cache_subdirectory_name,
                            backing_file)
                        if backing_path not in inuse_images:
                            inuse_images.append(backing_path)

                        if backing_path in self.unexplained_images:
                            LOG.warning('Instance %(instance)s is using a '
                                        'backing file %(backing)s which '
                                        'does not appear in the image service',
                                        {'instance': ent,
                                         'backing': backing_file})
                            self.unexplained_images.remove(backing_path)
        return inuse_images

    def _find_base_file(self, base_dir, fingerprint):
        """Find the base file matching this fingerprint.

        Yields the name of a base file which exists.
        Note that it is possible for more than one yield to result from this
        check.

        If no base file is found, then nothing is yielded.
        """
        # The original file from glance
        base_file = os.path.join(base_dir, fingerprint)
        if os.path.exists(base_file):
            yield base_file

        # An older naming style which can be removed sometime after Folsom
        base_file = os.path.join(base_dir, fingerprint + '_sm')
        if os.path.exists(base_file):
            yield base_file

        # Resized images (also legacy)
        resize_re = re.compile('.*/%s_[0-9]+$' % fingerprint)
        for img in self.unexplained_images:
            m = resize_re.match(img)
            if m:
                yield img

    @staticmethod
    def _get_age_of_file(base_file):
        if not os.path.exists(base_file):
            LOG.debug('Cannot remove %s, it does not exist', base_file)
            return (False, 0)

        mtime = os.path.getmtime(base_file)
        age = time.time() - mtime

        return (True, age)

    def _remove_old_enough_file(self, base_file, maxage, remove_lock=True):
        """Remove a single swap or base file if it is old enough."""
        exists, age = self._get_age_of_file(base_file)
        if not exists:
            return

        lock_file = os.path.split(base_file)[-1]

        @utils.synchronized(lock_file, external=True,
                            lock_path=self.lock_path)
        def _inner_remove_old_enough_file():
            # NOTE(mikal): recheck that the file is old enough, as a new
            # user of the file might have come along while we were waiting
            # for the lock
            exists, age = self._get_age_of_file(base_file)
            if not exists or age < maxage:
                return

            LOG.info('Removing base or swap file: %s', base_file)
            try:
                os.remove(base_file)
            except OSError as e:
                LOG.error('Failed to remove %(base_file)s, '
                          'error was %(error)s',
                          {'base_file': base_file,
                           'error': e})

        if age < maxage:
            LOG.info('Base or swap file too young to remove: %s', base_file)
        else:
            _inner_remove_old_enough_file()
            if remove_lock:
                try:
                    # NOTE(jichenjc) The lock file will be constructed first
                    # time the image file was accessed. the lock file looks
                    # like nova-9e881789030568a317fad9daae82c5b1c65e0d4a
                    # or nova-03d8e206-6500-4d91-b47d-ee74897f9b4e
                    # according to the original file name
                    lockutils.remove_external_lock_file(lock_file,
                        lock_file_prefix='nova-', lock_path=self.lock_path)
                except OSError as e:
                    LOG.debug('Failed to remove %(lock_file)s, '
                              'error was %(error)s',
                              {'lock_file': lock_file,
                               'error': e})

    def _remove_swap_file(self, base_file):
        """Remove a single swap base file if it is old enough."""
        maxage = CONF.remove_unused_original_minimum_age_seconds

        self._remove_old_enough_file(base_file, maxage, remove_lock=False)

    def _remove_base_file(self, base_file):
        """Remove a single base file if it is old enough."""
        maxage = CONF.libvirt.remove_unused_resized_minimum_age_seconds
        if base_file in self.originals:
            maxage = CONF.remove_unused_original_minimum_age_seconds

        self._remove_old_enough_file(base_file, maxage)

    def _mark_in_use(self, img_id, base_file):
        """Mark a single base image as in use."""

        LOG.info('image %(id)s at (%(base_file)s): checking',
                 {'id': img_id, 'base_file': base_file})

        if base_file in self.unexplained_images:
            self.unexplained_images.remove(base_file)

        self.active_base_files.append(base_file)

        LOG.debug('image %(id)s at (%(base_file)s): image is in use',
                  {'id': img_id, 'base_file': base_file})
        nova.privsep.path.utime(base_file)

    def _age_and_verify_swap_images(self, context, base_dir):
        LOG.debug('Verify swap images')

        for ent in self.back_swap_images:
            base_file = os.path.join(base_dir, ent)
            if ent in self.used_swap_images and os.path.exists(base_file):
                nova.privsep.path.utime(base_file)
            elif self.remove_unused_base_images:
                self._remove_swap_file(base_file)

        error_images = self.used_swap_images - self.back_swap_images
        for error_image in error_images:
            LOG.warning('%s swap image was used by instance'
                        ' but no back files existing!', error_image)

    def _age_and_verify_cached_images(self, context, all_instances, base_dir):
        LOG.debug('Verify base images')
        # Determine what images are on disk because they're in use
        for img in self.used_images:
            fingerprint = hashlib.sha1(
                    encodeutils.safe_encode(img)).hexdigest()
            LOG.debug('Image id %(id)s yields fingerprint %(fingerprint)s',
                      {'id': img,
                       'fingerprint': fingerprint})
            for base_file in self._find_base_file(base_dir, fingerprint):
                self._mark_in_use(img, base_file)

        # Elements remaining in unexplained_images might be in use
        inuse_backing_images = self._list_backing_images()
        for backing_path in inuse_backing_images:
            if backing_path not in self.active_base_files:
                self.active_base_files.append(backing_path)

        # Anything left is an unknown base image
        for img in self.unexplained_images:
            LOG.warning('Unknown base file: %s', img)
            self.removable_base_files.append(img)

        # Dump these lists
        if self.active_base_files:
            LOG.info('Active base files: %s',
                     ' '.join(self.active_base_files))

        if self.removable_base_files:
            LOG.info('Removable base files: %s',
                     ' '.join(self.removable_base_files))

            if self.remove_unused_base_images:
                for base_file in self.removable_base_files:
                    self._remove_base_file(base_file)

        # That's it
        LOG.debug('Verification complete')

    def _get_base(self):

        # NOTE(mikal): The new scheme for base images is as follows -- an
        # image is streamed from the image service to _base (filename is the
        # sha1 hash of the image id). If CoW is enabled, that file is then
        # resized to be the correct size for the instance (filename is the
        # same as the original, but with an underscore and the resized size
        # in bytes). This second file is then CoW'd to the instance disk. If
        # CoW is disabled, the resize occurs as part of the copy from the
        # cache to the instance directory. Files ending in _sm are no longer
        # created, but may remain from previous versions.

        base_dir = os.path.join(CONF.instances_path,
                                CONF.image_cache_subdirectory_name)
        if not os.path.exists(base_dir):
            LOG.debug('Skipping verification, no base directory at %s',
                      base_dir)
            return
        return base_dir

    def update(self, context, all_instances):
        base_dir = self._get_base()
        if not base_dir:
            return
        # reset the local statistics
        self._reset_state()
        # read the cached images
        self._scan_base_images(base_dir)
        # read running instances data
        running = self._list_running_instances(context, all_instances)
        self.used_images = running['used_images']
        self.instance_names = running['instance_names']
        self.used_swap_images = running['used_swap_images']
        # perform the aging and image verification
        self._age_and_verify_cached_images(context, all_instances, base_dir)
        self._age_and_verify_swap_images(context, base_dir)

    def get_disk_usage(self):
        try:
            # If the cache is on a different device than the instance dir then
            # it does not consume the same disk resource as instances.
            # NOTE(gibi): this does not work on Windows properly as st_dev is
            # always 0
            if (os.stat(CONF.instances_path).st_dev !=
                    os.stat(self.cache_dir).st_dev):
                return 0

            # NOTE(gibi): we need to use the disk size occupied from the file
            # system as images in the cache will not grow to their virtual
            # size.
            # NOTE(gibi): st.blocks is always measured in 512 byte blocks see
            # man fstat
            return sum(
                os.stat(os.path.join(self.cache_dir, f)).st_blocks * 512
                for f in os.listdir(self.cache_dir)
                if os.path.isfile(os.path.join(self.cache_dir, f)))
        except OSError:
            # NOTE(gibi): An error here can mean many things. E.g. the cache
            # dir does not exists yet, the cache dir is deleted between the
            # listdir() and the stat() calls, or a file is deleted between
            # the listdir() and the stat() calls.
            return 0

    @property
    def cache_dir(self):
        return os.path.join(
            CONF.instances_path, CONF.image_cache_subdirectory_name)
