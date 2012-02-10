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

import datetime
import hashlib
import os
import sys
import time

from nova import compute
from nova import context as db_context
from nova import db
from nova import flags
from nova import image
from nova import log as logging
from nova.openstack.common import cfg
from nova import utils
from nova.virt.libvirt import utils as virtutils


LOG = logging.getLogger('nova.compute.imagecache')

imagecache_opts = [
    cfg.BoolOpt('remove_unused_base_images',
                default=False,
                help='Should unused base images be removed?'),
    cfg.IntOpt('remove_unused_minimum_age_seconds',
               default=3600,
               help='Unused base images younger than this will not be '
                    'removed'),
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


class ImageCacheManager(object):
    def __init__(self):
        self.unexplained_images = []

    def _list_base_images(self, base_dir):
        """Return a list of the images present in _base.

        Note that this does not return a value. It instead populates a class
        variable with a list of images that we need to try and explain.
        """
        # Determine what images we have on disk. There will be other files in
        # this directory (for example kernels) so we only grab the ones which
        # are the right length to be disk images.
        self.unexplained_images = []
        digest_size = hashlib.sha1().digestsize * 2
        for ent in os.listdir(base_dir):
            if len(ent) == digest_size or len(ent) == digest_size + 3:
                entpath = os.path.join(base_dir, ent)
                if os.path.isfile(entpath):
                    self.unexplained_images.append(entpath)

    def _list_running_instances(self, context):
        """List running instances (on all compute nodes)."""
        self.used_images = {}
        self.image_popularity = {}

        instances = db.instance_get_all(context)
        for instance in instances:
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
            if ent.startswith('instance-'):
                disk_path = os.path.join(FLAGS.instances_path, ent, 'disk')
                if os.path.exists(disk_path):
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

        Yields the name of the base file, and a boolean which is True if
        the image is "small". Note that is is possible for more than one
        yield to result from this check.

        If no base file is found, then nothing is yielded.
        """
        base_file = os.path.join(base_dir, fingerprint)
        if os.path.exists(base_file):
            yield base_file, False

        base_file = os.path.join(base_dir, fingerprint + '_sm')
        if os.path.exists(base_file):
            yield base_file, True

    def _verify_checksum(self, img, base_file):
        """Compare the checksum stored on disk with the current file.

        Note that if the checksum fails to verify this is logged, but no actual
        action occurs. This is something sysadmins should monitor for and
        handle manually when it occurs.
        """
        f = open(base_file, 'r')
        current_checksum = utils.hash_file(f)
        f.close()

        stored_checksum = read_stored_checksum(base_file)

        if stored_checksum:
            if current_checksum != stored_checksum:
                LOG.error(_('%(container_format)s-%(id)s '
                            '(%(base_file)s): '
                            'image verification failed'),
                          {'container_format': img['container_format'],
                           'id': img['id'],
                           'base_file': base_file})
                return False

            else:
                return True

        else:
            LOG.debug(_('%(container_format)s-%(id)s (%(base_file)s): '
                        'image verification skipped, no hash stored'),
                      {'container_format': img['container_format'],
                       'id': img['id'],
                       'base_file': base_file})
            return None

    def _remove_base_file(self, base_file):
        """Remove a single base file if it is old enough.

        Returns nothing.
        """
        mtime = os.path.getmtime(base_file)
        age = time.time() - mtime

        if age < FLAGS.remove_unused_minimum_age_seconds:
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

    def _handle_base_image(self, img, base_file, image_small):
        """Handle the checks for a single base image."""

        # TODO(mikal): Write a unit test for this method
        image_bad = False
        image_in_use = False

        if base_file:
            LOG.debug(_('%(container_format)s-%(id)s (%(base_file)s): '
                        'checking'),
                      {'container_format': img['container_format'],
                       'id': img['id'],
                       'base_file': base_file})

            if base_file in self.unexplained_images:
                self.unexplained_images.remove(base_file)
            self._verify_checksum(img, base_file)

        else:
            LOG.debug(_('%(container_format)s-%(id)s (%(base_file)s): '
                        'base file absent'),
                      {'container_format': img['container_format'],
                       'id': img['id'],
                       'base_file': base_file})
            base_file = None

        instances = []
        if str(img['id']) in self.used_images:
            local, remote, instances = self.used_images[str(img['id'])]
            if local > 0:
                LOG.debug(_('%(container_format)s-%(id)s (%(base_file)s): '
                            'in use: on this node %(local)d local, '
                            '%(remote)d on other nodes'),
                          {'container_format': img['container_format'],
                           'id': img['id'],
                           'base_file': base_file,
                           'local': local,
                           'remote': remote})

                image_in_use = True
                self.active_base_files.append(base_file)

                if not base_file:
                    LOG.warning(_('%(container_format)s-%(id)s '
                                  '(%(base_file)s): warning -- an absent '
                                  'base file is in use! instances: '
                                  '%(instance_list)s'),
                                {'container_format':
                                     img['container_format'],
                                 'id': img['id'],
                                 'base_file': base_file,
                                 'instance_list': ' '.join(instances)})

            else:
                LOG.debug(_('%(container_format)s-%(id)s (%(base_file)s): '
                            'in: on other nodes (%(remote)d on other '
                            'nodes)'),
                          {'container_format': img['container_format'],
                           'id': img['id'],
                           'base_file': base_file,
                           'remote': remote})
        if image_bad:
            self.corrupt_base_files.append(base_file)

        if base_file:
            if not image_in_use:
                LOG.debug(_('%(container_format)s-%(id)s (%(base_file)s): '
                            'image is not in use'),
                          {'container_format': img['container_format'],
                           'id': img['id'],
                           'base_file': base_file})
                self.removable_base_files.append(base_file)

            else:
                LOG.debug(_('%(container_format)s-%(id)s (%(base_file)s): '
                            'image is in use'),
                          {'container_format': img['container_format'],
                           'id': img['id'],
                           'base_file': base_file})

    def verify_base_images(self, context):
        """Verify that base images are in a reasonable state."""
        # TODO(mikal): Write a unit test for this method

        base_dir = os.path.join(FLAGS.instances_path, '_base')
        if not os.path.exists(base_dir):
            LOG.debug(_('Skipping verification, no base directory at %s'),
                      base_dir)
            return

        LOG.debug(_('Verify base images'))
        self._list_base_images(base_dir)
        self._list_running_instances(context)

        # Determine what images are in glance
        image_service = image.get_default_image_service()

        self.active_base_files = []
        self.corrupt_base_files = []
        self.removable_base_files = []

        # GlanceImageService.detail uses _fetch_images which handles pagination
        # for us
        for img in image_service.detail(context):
            if img['container_format'] != 'ami':
                continue

            fingerprint = hashlib.sha1(str(img['id'])).hexdigest()
            for base_file, image_small in self._find_base_file(base_dir,
                                                               fingerprint):
                self._handle_base_image(img, base_file, image_small)

        # Elements remaining in unexplained_images are not currently in
        # glance. That doesn't mean that they're really not in use though
        # (consider images which have been removed from glance but are still
        # used by instances). So, we check the backing file for any running
        # instances as well.
        if self.unexplained_images:
            inuse_backing_images = self._list_backing_images()
            if inuse_backing_images:
                for backing_path in inuse_backing_images:
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
