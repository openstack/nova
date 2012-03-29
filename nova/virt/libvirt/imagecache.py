#!/usr/bin/python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import compute
from nova import context as db_context
from nova import db
from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
from nova import utils
from nova.virt.libvirt import utils as virtutils


LOG = logging.getLogger(__name__)

imagecache_opts = [
    cfg.BoolOpt('remove_unused_base_images',
                default=False,
                help='Should unused base images be removed?'),
    cfg.IntOpt('remove_unused_resized_minimum_age_seconds',
               default=3600,
               help='Unused resized base images younger than this will not be '
                    'removed'),
    cfg.IntOpt('remove_unused_original_minimum_age_seconds',
               default=(24 * 3600),
               help='Unused unresized base images younger than this will not '
                    'be removed'),
    cfg.BoolOpt('checksum_base_images',
                default=False,
                help='Write a checksum for files in _base to disk'),
    ]

flags.DECLARE('instances_path', 'nova.compute.manager')
FLAGS = flags.FLAGS
FLAGS.register_opts(imagecache_opts)


def read_stored_checksum(base_file):
    """Read the checksum which was created at image fetch time.

    Returns the checksum (as hex) or None.
    """
    checksum_file = '%s.sha1' % base_file
    if not os.path.exists(checksum_file):
        return None

    f = open(checksum_file, 'r')
    stored_checksum = f.read().rstrip()
    f.close()
    return stored_checksum


def write_stored_checksum(target):
    """Write a checksum to disk for a file in _base."""

    checksum_filename = '%s.sha1' % target
    if os.path.exists(target) and not os.path.exists(checksum_filename):
        # NOTE(mikal): Create the checksum file first to exclude possible
        # overlap in checksum operations. An empty checksum file is ignored if
        # encountered during verification.
        sum_file = open(checksum_filename, 'w')
        img_file = open(target, 'r')
        checksum = utils.hash_file(img_file)
        img_file.close()

        sum_file.write(checksum)
        sum_file.close()


class ImageCacheManager(object):
    def __init__(self):
        self._reset_state()

    def _reset_state(self):
        """Reset state variables used for each pass."""

        self.used_images = {}
        self.image_popularity = {}
        self.instance_names = {}

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

    def _list_base_images(self, base_dir):
        """Return a list of the images present in _base.

        Determine what images we have on disk. There will be other files in
        this directory (for example kernels) so we only grab the ones which
        are the right length to be disk images.

        Note that this does not return a value. It instead populates a class
        variable with a list of images that we need to try and explain.
        """
        digest_size = hashlib.sha1().digestsize * 2
        for ent in os.listdir(base_dir):
            if len(ent) == digest_size:
                self._store_image(base_dir, ent, original=True)

            elif (len(ent) > digest_size + 2 and
                  ent[digest_size] == '_' and
                  not ent.endswith('.sha1')):
                self._store_image(base_dir, ent, original=False)

    def _list_running_instances(self, context):
        """List running instances (on all compute nodes)."""
        self.used_images = {}
        self.image_popularity = {}
        self.instance_names = {}

        instances = db.instance_get_all(context)
        for instance in instances:
            self.instance_names[instance['name']] = instance['uuid']

            image_ref_str = str(instance['image_ref'])
            local, remote, insts = self.used_images.get(image_ref_str,
                                                        (0, 0, []))
            if instance['host'] == FLAGS.host:
                local += 1
            else:
                remote += 1
            insts.append(instance['name'])
            self.used_images[image_ref_str] = (local, remote, insts)

            self.image_popularity.setdefault(image_ref_str, 0)
            self.image_popularity[image_ref_str] += 1

    def _list_backing_images(self):
        """List the backing images currently in use."""
        inuse_images = []
        for ent in os.listdir(FLAGS.instances_path):
            if ent in self.instance_names:
                LOG.debug(_('%s is a valid instance name'), ent)
                disk_path = os.path.join(FLAGS.instances_path, ent, 'disk')
                if os.path.exists(disk_path):
                    LOG.debug(_('%s has a disk file'), ent)
                    backing_file = virtutils.get_disk_backing_file(disk_path)
                    LOG.debug(_('Instance %(instance)s is backed by '
                                '%(backing)s'),
                              {'instance': ent,
                               'backing': backing_file})

                    backing_path = os.path.join(FLAGS.instances_path,
                                                '_base', backing_file)
                    if not backing_path in inuse_images:
                        inuse_images.append(backing_path)

                    if backing_path in self.unexplained_images:
                        LOG.warning(_('Instance %(instance)s is using a '
                                      'backing file %(backing)s which does '
                                      'not appear in the image service'),
                                    {'instance': ent,
                                     'backing': backing_file})
                        self.unexplained_images.remove(backing_path)

        return inuse_images

    def _find_base_file(self, base_dir, fingerprint):
        """Find the base file matching this fingerprint.

        Yields the name of the base file, a boolean which is True if the image
        is "small", and a boolean which indicates if this is a resized image.
        Note that is is possible for more than one yield to result from this
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

    def _verify_checksum(self, img_id, base_file):
        """Compare the checksum stored on disk with the current file.

        Note that if the checksum fails to verify this is logged, but no actual
        action occurs. This is something sysadmins should monitor for and
        handle manually when it occurs.
        """

        stored_checksum = read_stored_checksum(base_file)
        if stored_checksum:
            f = open(base_file, 'r')
            current_checksum = utils.hash_file(f)
            f.close()

            if current_checksum != stored_checksum:
                LOG.error(_('%(id)s (%(base_file)s): image verification '
                            'failed'),
                          {'id': img_id,
                           'base_file': base_file})
                return False

            else:
                return True

        else:
            LOG.debug(_('%(id)s (%(base_file)s): image verification skipped, '
                        'no hash stored'),
                      {'id': img_id,
                       'base_file': base_file})

            # NOTE(mikal): If the checksum file is missing, then we should
            # create one. We don't create checksums when we download images
            # from glance because that would delay VM startup.
            if FLAGS.checksum_base_images:
                write_stored_checksum(base_file)

            return None

    def _remove_base_file(self, base_file):
        """Remove a single base file if it is old enough.

        Returns nothing.
        """
        if not os.path.exists(base_file):
            LOG.debug(_('Cannot remove %(base_file)s, it does not exist'),
                      base_file)
            return

        mtime = os.path.getmtime(base_file)
        age = time.time() - mtime

        maxage = FLAGS.remove_unused_resized_minimum_age_seconds
        if base_file in self.originals:
            maxage = FLAGS.remove_unused_original_minimum_age_seconds

        if age < maxage:
            LOG.info(_('Base file too young to remove: %s'),
                     base_file)
        else:
            LOG.info(_('Removing base file: %s'), base_file)
            try:
                os.remove(base_file)
                signature = base_file + '.sha1'
                if os.path.exists(signature):
                    os.remove(signature)
            except OSError, e:
                LOG.error(_('Failed to remove %(base_file)s, '
                            'error was %(error)s'),
                          {'base_file': base_file,
                           'error': e})

    def _handle_base_image(self, img_id, base_file):
        """Handle the checks for a single base image."""

        image_bad = False
        image_in_use = False

        LOG.info(_('%(id)s (%(base_file)s): checking'),
                 {'id': img_id,
                  'base_file': base_file})

        if base_file in self.unexplained_images:
            self.unexplained_images.remove(base_file)

        if (base_file and os.path.exists(base_file)
            and os.path.isfile(base_file)):
            # _verify_checksum returns True if the checksum is ok, and None if
            # there is no checksum file
            checksum_result = self._verify_checksum(img_id, base_file)
            if not checksum_result is None:
                image_bad = not checksum_result

        instances = []
        if img_id in self.used_images:
            local, remote, instances = self.used_images[img_id]
            if local > 0:
                LOG.debug(_('%(id)s (%(base_file)s): '
                            'in use: on this node %(local)d local, '
                            '%(remote)d on other nodes'),
                          {'id': img_id,
                           'base_file': base_file,
                           'local': local,
                           'remote': remote})

                image_in_use = True
                self.active_base_files.append(base_file)

                if not base_file:
                    LOG.warning(_('%(id)s (%(base_file)s): warning -- an '
                                  'absent base file is in use! instances: '
                                  '%(instance_list)s'),
                                {'id': img_id,
                                 'base_file': base_file,
                                 'instance_list': ' '.join(instances)})

            else:
                LOG.debug(_('%(id)s (%(base_file)s): in use on (%(remote)d on '
                            'other nodes)'),
                          {'id': img_id,
                           'base_file': base_file,
                           'remote': remote})
        if image_bad:
            self.corrupt_base_files.append(base_file)

        if base_file:
            if not image_in_use:
                LOG.debug(_('%(id)s (%(base_file)s): image is not in use'),
                          {'id': img_id,
                           'base_file': base_file})
                self.removable_base_files.append(base_file)

            else:
                LOG.debug(_('%(id)s (%(base_file)s): image is in use'),
                          {'id': img_id,
                           'base_file': base_file})
                if os.path.exists(base_file):
                    os.utime(base_file, None)

    def verify_base_images(self, context):
        """Verify that base images are in a reasonable state."""

        # NOTE(mikal): The new scheme for base images is as follows -- an
        # image is streamed from the image service to _base (filename is the
        # sha1 hash of the image id). If CoW is enabled, that file is then
        # resized to be the correct size for the instance (filename is the
        # same as the original, but with an underscore and the resized size
        # in bytes). This second file is then CoW'd to the instance disk. If
        # CoW is disabled, the resize occurs as part of the copy from the
        # cache to the instance directory. Files ending in _sm are no longer
        # created, but may remain from previous versions.
        self._reset_state()

        base_dir = os.path.join(FLAGS.instances_path, '_base')
        if not os.path.exists(base_dir):
            LOG.debug(_('Skipping verification, no base directory at %s'),
                      base_dir)
            return

        LOG.debug(_('Verify base images'))
        self._list_base_images(base_dir)
        self._list_running_instances(context)

        # Determine what images are on disk because they're in use
        for img in self.used_images:
            fingerprint = hashlib.sha1(img).hexdigest()
            LOG.debug(_('Image id %(id)s yields fingerprint %(fingerprint)s'),
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
            if not backing_path in self.active_base_files:
                self.active_base_files.append(backing_path)

        # Anything left is an unknown base image
        for img in self.unexplained_images:
            LOG.warning(_('Unknown base file: %s'), img)
            self.removable_base_files.append(img)

        # Dump these lists
        if self.active_base_files:
            LOG.info(_('Active base files: %s'),
                     ' '.join(self.active_base_files))
        if self.corrupt_base_files:
            LOG.info(_('Corrupt base files: %s'),
                     ' '.join(self.corrupt_base_files))

        if self.removable_base_files:
            LOG.info(_('Removable base files: %s'),
                     ' '.join(self.removable_base_files))

            if FLAGS.remove_unused_base_images:
                for base_file in self.removable_base_files:
                    self._remove_base_file(base_file)

        # That's it
        LOG.debug(_('Verification complete'))
