# Copyright (c) 2014 VMware, Inc.
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

"""
Image cache class

Images that are stored in the cache folder will be stored in a folder whose
name is the image ID. In the event that an image is discovered to be no longer
used then a timestamp will be added to the image folder.
The timestamp will be a folder - this is due to the fact that we can use the
VMware API's for creating and deleting of folders (it really simplifies
things). The timestamp will contain the time, on the compute node, when the
image was first seen to be unused.
At each aging iteration we check if the image can be aged.
This is done by comparing the current nova compute time to the time embedded
in the timestamp. If the time exceeds the configured aging time then
the parent folder, that is the image ID folder, will be deleted.
That effectively ages the cached image.
If an image is used then the timestamps will be deleted.

When accessing a timestamp we make use of locking. This ensure that aging
will not delete an image during the spawn operation. When spawning
the timestamp folder will be locked  and the timestamps will be purged.
This will ensure that an image is not deleted during the spawn.
"""

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_vmware import exceptions as vexc
from oslo_vmware import vim_util as vutil

from nova.virt import imagecache
from nova.virt.vmwareapi import ds_util

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

TIMESTAMP_PREFIX = 'ts-'
TIMESTAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'


class ImageCacheManager(imagecache.ImageCacheManager):
    def __init__(self, session, base_folder):
        super(ImageCacheManager, self).__init__()
        self._session = session
        self._base_folder = base_folder
        self._ds_browser = {}

    def _folder_delete(self, ds_path, dc_ref):
        try:
            ds_util.file_delete(self._session, ds_path, dc_ref)
        except (vexc.CannotDeleteFileException,
                vexc.FileFaultException,
                vexc.FileLockedException) as e:
            # There may be more than one process or thread that tries
            # to delete the file.
            LOG.warning("Unable to delete %(file)s. Exception: %(ex)s",
                        {'file': ds_path, 'ex': e})
        except vexc.FileNotFoundException:
            LOG.debug("File not found: %s", ds_path)

    def enlist_image(self, image_id, datastore, dc_ref):
        ds_browser = self._get_ds_browser(datastore.ref)
        cache_root_folder = datastore.build_path(self._base_folder)

        # Check if the timestamp file exists - if so then delete it. This
        # will ensure that the aging will not delete a cache image if it
        # is going to be used now.
        path = self.timestamp_folder_get(cache_root_folder, image_id)

        # Lock to ensure that the spawn will not try and access an image
        # that is currently being deleted on the datastore.
        with lockutils.lock(str(path), lock_file_prefix='nova-vmware-ts',
                            external=True):
            self.timestamp_cleanup(dc_ref, ds_browser, path)

    def timestamp_folder_get(self, ds_path, image_id):
        """Returns the timestamp folder."""
        return ds_path.join(image_id)

    def timestamp_cleanup(self, dc_ref, ds_browser, ds_path):
        ts = self._get_timestamp(ds_browser, ds_path)
        if ts:
            ts_path = ds_path.join(ts)
            LOG.debug("Timestamp path %s exists. Deleting!", ts_path)
            # Image is used - no longer need timestamp folder
            self._folder_delete(ts_path, dc_ref)

    def _get_timestamp(self, ds_browser, ds_path):
        files = ds_util.get_sub_folders(self._session, ds_browser, ds_path)
        if files:
            for file in files:
                if file.startswith(TIMESTAMP_PREFIX):
                    return file

    def _get_timestamp_filename(self):
        return '%s%s' % (TIMESTAMP_PREFIX,
                         timeutils.utcnow().strftime(TIMESTAMP_FORMAT))

    def _get_datetime_from_filename(self, timestamp_filename):
        ts = timestamp_filename.lstrip(TIMESTAMP_PREFIX)
        return timeutils.parse_strtime(ts, fmt=TIMESTAMP_FORMAT)

    def _get_ds_browser(self, ds_ref):
        ds_browser = self._ds_browser.get(ds_ref.value)
        if not ds_browser:
            ds_browser = vutil.get_object_property(self._session.vim,
                                                   ds_ref,
                                                   "browser")
            self._ds_browser[ds_ref.value] = ds_browser
        return ds_browser

    def _list_datastore_images(self, ds_path, datastore):
        """Return a list of the images present in _base.

        This method returns a dictionary with the following keys:
            - unexplained_images
            - originals
        """
        ds_browser = self._get_ds_browser(datastore.ref)
        originals = ds_util.get_sub_folders(self._session, ds_browser,
                                            ds_path)
        return {'unexplained_images': [],
                'originals': originals}

    def _age_cached_images(self, context, datastore, dc_info,
                           ds_path):
        """Ages cached images."""
        age_seconds = (
            CONF.image_cache.remove_unused_original_minimum_age_seconds)
        unused_images = self.originals - self.used_images
        ds_browser = self._get_ds_browser(datastore.ref)
        for image in unused_images:
            path = self.timestamp_folder_get(ds_path, image)
            # Lock to ensure that the spawn will not try and access an image
            # that is currently being deleted on the datastore.
            with lockutils.lock(str(path), lock_file_prefix='nova-vmware-ts',
                                external=True):
                ts = self._get_timestamp(ds_browser, path)
                if not ts:
                    ts_path = path.join(self._get_timestamp_filename())
                    try:
                        ds_util.mkdir(self._session, ts_path, dc_info.ref)
                    except vexc.FileAlreadyExistsException:
                        LOG.debug("Timestamp already exists.")
                    LOG.info("Image %s is no longer used by this node. "
                             "Pending deletion!", image)
                else:
                    dt = self._get_datetime_from_filename(str(ts))
                    if timeutils.is_older_than(dt, age_seconds):
                        LOG.info("Image %s is no longer used. Deleting!", path)
                        # Image has aged - delete the image ID folder
                        self._folder_delete(path, dc_info.ref)

        # If the image is used and the timestamp file exists then we delete
        # the timestamp.
        for image in self.used_images:
            path = self.timestamp_folder_get(ds_path, image)
            with lockutils.lock(str(path), lock_file_prefix='nova-vmware-ts',
                                external=True):
                self.timestamp_cleanup(dc_info.ref, ds_browser,
                                       path)

    def update(self, context, instances, datastores_info):
        """The cache manager entry point.

        This will invoke the cache manager. This will update the cache
        according to the defined cache management scheme. The information
        populated in the cached stats will be used for the cache management.
        """
        # read running instances data
        running = self._list_running_instances(context, instances)
        self.used_images = set(running['used_images'].keys())
        # perform the aging and image verification per datastore
        for (datastore, dc_info) in datastores_info:
            ds_path = datastore.build_path(self._base_folder)
            images = self._list_datastore_images(ds_path, datastore)
            self.originals = images['originals']
            self._age_cached_images(context, datastore, dc_info, ds_path)

    def get_image_cache_folder(self, datastore, image_id):
        """Returns datastore path of folder containing the image."""
        return datastore.build_path(self._base_folder, image_id)
