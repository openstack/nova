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
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import fileutils

import nova.conf
from nova.i18n import _LE
from nova.i18n import _LI
from nova.i18n import _LW
from nova import utils
from nova.virt import imagecache
from nova.virt.libvirt import utils as libvirt_utils

LOG = logging.getLogger(__name__)

imagecache_opts = [
    cfg.StrOpt('image_info_filename_pattern',
               default='$instances_path/$image_cache_subdirectory_name/'
                       '%(image)s.info',
               help='Allows image information files to be stored in '
                    'non-standard locations'),
    cfg.BoolOpt('remove_unused_kernels',
                default=True,
                deprecated_for_removal=True,
                help='DEPRECATED: Should unused kernel images be removed? '
                     'This is only safe to enable if all compute nodes have '
                     'been updated to support this option (running Grizzly or '
                     'newer level compute). This will be the default behavior '
                     'in the 13.0.0 release.'),
    cfg.IntOpt('remove_unused_resized_minimum_age_seconds',
               default=3600,
               help='Unused resized base images younger than this will not be '
                    'removed'),
    cfg.BoolOpt('checksum_base_images',
                default=False,
                help='Write a checksum for files in _base to disk'),
    cfg.IntOpt('checksum_interval_seconds',
               default=3600,
               help='How frequently to checksum base images'),
    ]

CONF = nova.conf.CONF
CONF.register_opts(imagecache_opts, 'libvirt')
CONF.import_opt('instances_path', 'nova.compute.manager')


def get_cache_fname(images, key):
    """Return a filename based on the SHA1 hash of a given image ID.

    Image files stored in the _base directory that match this pattern
    are considered for cleanup by the image cache manager. The cache
    manager considers the file to be in use if it matches an instance's
    image_ref, kernel_id or ramdisk_id property.

    However, in grizzly-3 and before, only the image_ref property was
    considered. This means that it's unsafe to store kernel and ramdisk
    images using this pattern until we're sure that all compute nodes
    are running a cache manager newer than grizzly-3. For now, we
    require admins to confirm that by setting the remove_unused_kernels
    boolean but, at some point in the future, we'll be safely able to
    assume this.
    """
    image_id = str(images[key])
    if ((not CONF.libvirt.remove_unused_kernels and
         key in ['kernel_id', 'ramdisk_id'])):
        return image_id
    else:
        return hashlib.sha1(image_id).hexdigest()


def get_info_filename(base_path):
    """Construct a filename for storing additional information about a base
    image.

    Returns a filename.
    """

    base_file = os.path.basename(base_path)
    return (CONF.libvirt.image_info_filename_pattern
            % {'image': base_file})


def is_valid_info_file(path):
    """Test if a given path matches the pattern for info files."""

    digest_size = hashlib.sha1().digestsize * 2
    regexp = (CONF.libvirt.image_info_filename_pattern
              % {'image': ('([0-9a-f]{%(digest_size)d}|'
                           '[0-9a-f]{%(digest_size)d}_sm|'
                           '[0-9a-f]{%(digest_size)d}_[0-9]+)'
                           % {'digest_size': digest_size})})
    m = re.match(regexp, path)
    if m:
        return True
    return False


def _read_possible_json(serialized, info_file):
    try:
        d = jsonutils.loads(serialized)

    except ValueError as e:
        LOG.error(_LE('Error reading image info file %(filename)s: '
                      '%(error)s'),
                  {'filename': info_file,
                   'error': e})
        d = {}

    return d


def read_stored_info(target, field=None, timestamped=False):
    """Read information about an image.

    Returns an empty dictionary if there is no info, just the field value if
    a field is requested, or the entire dictionary otherwise.
    """

    info_file = get_info_filename(target)
    if not os.path.exists(info_file):
        # NOTE(mikal): Special case to handle essex checksums being converted.
        # There is an assumption here that target is a base image filename.
        old_filename = target + '.sha1'
        if field == 'sha1' and os.path.exists(old_filename):
            with open(old_filename) as hash_file:
                hash_value = hash_file.read()

            write_stored_info(target, field=field, value=hash_value)
            os.remove(old_filename)
            d = {field: hash_value}

        else:
            d = {}

    else:
        lock_name = 'info-%s' % os.path.split(target)[-1]
        lock_path = os.path.join(CONF.instances_path, 'locks')

        @utils.synchronized(lock_name, external=True, lock_path=lock_path)
        def read_file(info_file):
            LOG.debug('Reading image info file: %s', info_file)
            with open(info_file, 'r') as f:
                return f.read().rstrip()

        serialized = read_file(info_file)
        d = _read_possible_json(serialized, info_file)

    if field:
        if timestamped:
            return (d.get(field, None), d.get('%s-timestamp' % field, None))
        else:
            return d.get(field, None)
    return d


def write_stored_info(target, field=None, value=None):
    """Write information about an image."""

    if not field:
        return

    info_file = get_info_filename(target)
    LOG.info(_LI('Writing stored info to %s'), info_file)
    fileutils.ensure_tree(os.path.dirname(info_file))

    lock_name = 'info-%s' % os.path.split(target)[-1]
    lock_path = os.path.join(CONF.instances_path, 'locks')

    @utils.synchronized(lock_name, external=True, lock_path=lock_path)
    def write_file(info_file, field, value):
        d = {}

        if os.path.exists(info_file):
            with open(info_file, 'r') as f:
                d = _read_possible_json(f.read(), info_file)

        d[field] = value
        d['%s-timestamp' % field] = time.time()

        with open(info_file, 'w') as f:
            f.write(jsonutils.dumps(d))

    write_file(info_file, field, value)


def _hash_file(filename):
    """Generate a hash for the contents of a file."""
    checksum = hashlib.sha1()
    with open(filename) as f:
        for chunk in iter(lambda: f.read(32768), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def read_stored_checksum(target, timestamped=True):
    """Read the checksum.

    Returns the checksum (as hex) or None.
    """
    return read_stored_info(target, field='sha1', timestamped=timestamped)


def write_stored_checksum(target):
    """Write a checksum to disk for a file in _base."""
    write_stored_info(target, field='sha1', value=_hash_file(target))


class ImageCacheManager(imagecache.ImageCacheManager):
    def __init__(self):
        super(ImageCacheManager, self).__init__()
        self.lock_path = os.path.join(CONF.instances_path, 'locks')
        self._reset_state()

    def _reset_state(self):
        """Reset state variables used for each pass."""

        self.used_images = {}
        self.image_popularity = {}
        self.instance_names = set()

        self.back_swap_images = set()
        self.used_swap_images = set()

        self.active_base_files = []
        self.corrupt_base_files = []
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

    def _list_base_images(self, base_dir):
        """Return a list of the images present in _base.

        Determine what images we have on disk. There will be other files in
        this directory so we only grab the ones which are the right length
        to be disk images.
        """

        digest_size = hashlib.sha1().digestsize * 2
        for ent in os.listdir(base_dir):
            if len(ent) == digest_size:
                self._store_image(base_dir, ent, original=True)

            elif (len(ent) > digest_size + 2 and
                  ent[digest_size] == '_' and
                  not is_valid_info_file(os.path.join(base_dir, ent))):
                self._store_image(base_dir, ent, original=False)
            else:
                self._store_swap_image(ent)

        return {'unexplained_images': self.unexplained_images,
                'originals': self.originals}

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
                            LOG.warning(_LW('Instance %(instance)s is using a '
                                         'backing file %(backing)s which '
                                         'does not appear in the image '
                                         'service'),
                                        {'instance': ent,
                                         'backing': backing_file})
                            self.unexplained_images.remove(backing_path)
        return inuse_images

    def _find_base_file(self, base_dir, fingerprint):
        """Find the base file matching this fingerprint.

        Yields the name of the base file, a boolean which is True if the image
        is "small", and a boolean which indicates if this is a resized image.
        Note that it is possible for more than one yield to result from this
        check.

        If no base file is found, then nothing is yielded.
        """
        # The original file from glance
        base_file = os.path.join(base_dir, fingerprint)
        if os.path.exists(base_file):
            yield base_file, False, False

        # An older naming style which can be removed sometime after Folsom
        base_file = os.path.join(base_dir, fingerprint + '_sm')
        if os.path.exists(base_file):
            yield base_file, True, False

        # Resized images
        resize_re = re.compile('.*/%s_[0-9]+$' % fingerprint)
        for img in self.unexplained_images:
            m = resize_re.match(img)
            if m:
                yield img, False, True

    def _verify_checksum(self, img_id, base_file, create_if_missing=True):
        """Compare the checksum stored on disk with the current file.

        Note that if the checksum fails to verify this is logged, but no actual
        action occurs. This is something sysadmins should monitor for and
        handle manually when it occurs.
        """

        if not CONF.libvirt.checksum_base_images:
            return None

        lock_name = 'hash-%s' % os.path.split(base_file)[-1]

        # Protect against other nova-computes performing checksums at the same
        # time if we are using shared storage
        @utils.synchronized(lock_name, external=True, lock_path=self.lock_path)
        def inner_verify_checksum():
            (stored_checksum, stored_timestamp) = read_stored_checksum(
                base_file, timestamped=True)
            if stored_checksum:
                # NOTE(mikal): Checksums are timestamped. If we have recently
                # checksummed (possibly on another compute node if we are using
                # shared storage), then we don't need to checksum again.
                if (stored_timestamp and
                    time.time() - stored_timestamp <
                        CONF.libvirt.checksum_interval_seconds):
                    return True

                # NOTE(mikal): If there is no timestamp, then the checksum was
                # performed by a previous version of the code.
                if not stored_timestamp:
                    write_stored_info(base_file, field='sha1',
                                      value=stored_checksum)

                current_checksum = _hash_file(base_file)

                if current_checksum != stored_checksum:
                    LOG.error(_LE('image %(id)s at (%(base_file)s): image '
                                  'verification failed'),
                              {'id': img_id,
                               'base_file': base_file})
                    return False

                else:
                    return True

            else:
                LOG.info(_LI('image %(id)s at (%(base_file)s): image '
                             'verification skipped, no hash stored'),
                         {'id': img_id,
                          'base_file': base_file})

                # NOTE(mikal): If the checksum file is missing, then we should
                # create one. We don't create checksums when we download images
                # from glance because that would delay VM startup.
                if CONF.libvirt.checksum_base_images and create_if_missing:
                    LOG.info(_LI('%(id)s (%(base_file)s): generating '
                                 'checksum'),
                             {'id': img_id,
                              'base_file': base_file})
                    write_stored_checksum(base_file)

                return None

        return inner_verify_checksum()

    @staticmethod
    def _get_age_of_file(base_file):
        if not os.path.exists(base_file):
            LOG.debug('Cannot remove %s, it does not exist', base_file)
            return (False, 0)

        mtime = os.path.getmtime(base_file)
        age = time.time() - mtime

        return (True, age)

    def _remove_old_enough_file(self, base_file, maxage, remove_sig=True,
                                remove_lock=True):
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

            LOG.info(_LI('Removing base or swap file: %s'), base_file)
            try:
                os.remove(base_file)
                if remove_sig:
                    signature = get_info_filename(base_file)
                    if os.path.exists(signature):
                        os.remove(signature)
            except OSError as e:
                LOG.error(_LE('Failed to remove %(base_file)s, '
                              'error was %(error)s'),
                          {'base_file': base_file,
                           'error': e})

        if age < maxage:
            LOG.info(_LI('Base or swap file too young to remove: %s'),
                         base_file)
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

        self._remove_old_enough_file(base_file, maxage, remove_sig=False,
                                     remove_lock=False)

    def _remove_base_file(self, base_file):
        """Remove a single base file if it is old enough."""
        maxage = CONF.libvirt.remove_unused_resized_minimum_age_seconds
        if base_file in self.originals:
            maxage = CONF.remove_unused_original_minimum_age_seconds

        self._remove_old_enough_file(base_file, maxage)

    def _handle_base_image(self, img_id, base_file):
        """Handle the checks for a single base image."""

        image_bad = False
        image_in_use = False

        LOG.info(_LI('image %(id)s at (%(base_file)s): checking'),
                 {'id': img_id,
                  'base_file': base_file})

        if base_file in self.unexplained_images:
            self.unexplained_images.remove(base_file)

        if (base_file and os.path.exists(base_file)
                and os.path.isfile(base_file)):
            # _verify_checksum returns True if the checksum is ok, and None if
            # there is no checksum file
            checksum_result = self._verify_checksum(img_id, base_file)
            if checksum_result is not None:
                image_bad = not checksum_result

            # Give other threads a chance to run
            time.sleep(0)

        if img_id in self.used_images:
            local, remote, instances = self.used_images[img_id]

            if local > 0 or remote > 0:
                image_in_use = True
                LOG.info(_LI('image %(id)s at (%(base_file)s): '
                             'in use: on this node %(local)d local, '
                             '%(remote)d on other nodes sharing this instance '
                             'storage'),
                         {'id': img_id,
                          'base_file': base_file,
                          'local': local,
                          'remote': remote})

                self.active_base_files.append(base_file)

                if not base_file:
                    LOG.warning(_LW('image %(id)s at (%(base_file)s): warning '
                                 '-- an absent base file is in use! '
                                 'instances: %(instance_list)s'),
                                {'id': img_id,
                                 'base_file': base_file,
                                 'instance_list': ' '.join(instances)})

        if image_bad:
            self.corrupt_base_files.append(base_file)

        if base_file:
            if not image_in_use:
                LOG.debug('image %(id)s at (%(base_file)s): image is not in '
                          'use',
                          {'id': img_id,
                           'base_file': base_file})
                self.removable_base_files.append(base_file)

            else:
                LOG.debug('image %(id)s at (%(base_file)s): image is in '
                          'use',
                          {'id': img_id,
                           'base_file': base_file})
                if os.path.exists(base_file):
                    libvirt_utils.update_mtime(base_file)

    def _age_and_verify_swap_images(self, context, base_dir):
        LOG.debug('Verify swap images')

        for ent in self.back_swap_images:
            base_file = os.path.join(base_dir, ent)
            if ent in self.used_swap_images and os.path.exists(base_file):
                libvirt_utils.update_mtime(base_file)
            elif self.remove_unused_base_images:
                self._remove_swap_file(base_file)

        error_images = self.used_swap_images - self.back_swap_images
        for error_image in error_images:
            LOG.warning(_LW('%s swap image was used by instance'
                         ' but no back files existing!'), error_image)

    def _age_and_verify_cached_images(self, context, all_instances, base_dir):
        LOG.debug('Verify base images')
        # Determine what images are on disk because they're in use
        for img in self.used_images:
            fingerprint = hashlib.sha1(img).hexdigest()
            LOG.debug('Image id %(id)s yields fingerprint %(fingerprint)s',
                      {'id': img,
                       'fingerprint': fingerprint})
            for result in self._find_base_file(base_dir, fingerprint):
                base_file, image_small, image_resized = result
                self._handle_base_image(img, base_file)

                if not image_small and not image_resized:
                    self.originals.append(base_file)

        # Elements remaining in unexplained_images might be in use
        inuse_backing_images = self._list_backing_images()
        for backing_path in inuse_backing_images:
            if backing_path not in self.active_base_files:
                self.active_base_files.append(backing_path)

        # Anything left is an unknown base image
        for img in self.unexplained_images:
            LOG.warning(_LW('Unknown base file: %s'), img)
            self.removable_base_files.append(img)

        # Dump these lists
        if self.active_base_files:
            LOG.info(_LI('Active base files: %s'),
                     ' '.join(self.active_base_files))
        if self.corrupt_base_files:
            LOG.info(_LI('Corrupt base files: %s'),
                     ' '.join(self.corrupt_base_files))

        if self.removable_base_files:
            LOG.info(_LI('Removable base files: %s'),
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
        self._list_base_images(base_dir)
        # read running instances data
        running = self._list_running_instances(context, all_instances)
        self.used_images = running['used_images']
        self.image_popularity = running['image_popularity']
        self.instance_names = running['instance_names']
        self.used_swap_images = running['used_swap_images']
        # perform the aging and image verification
        self._age_and_verify_cached_images(context, all_instances, base_dir)
        self._age_and_verify_swap_images(context, base_dir)
