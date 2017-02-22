# Copyright 2015, 2017 IBM Corp.
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

import random

import oslo_log.log as logging
from pypowervm import const as pvm_const
from pypowervm import exceptions as pvm_exc
from pypowervm.tasks import cluster_ssp as tsk_cs
from pypowervm.tasks import partition as tsk_par
from pypowervm.tasks import scsi_mapper as tsk_map
from pypowervm.tasks import storage as tsk_stg
import pypowervm.util as pvm_u
import pypowervm.wrappers.cluster as pvm_clust
import pypowervm.wrappers.storage as pvm_stg

import nova.conf
from nova import exception
from nova import image
from nova.virt.powervm import vm


LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF

IMAGE_API = image.API()


class DiskType(object):
    BOOT = 'boot'
    IMAGE = 'image'


class IterableToFileAdapter(object):
    """A degenerate file-like so that an iterable can be read like a file.

    The Glance client returns an iterable, but PowerVM requires a file.  This
    is the adapter between the two.

    Taken from xenapi/image/apis.py
    """

    def __init__(self, iterable):
        self.iterator = iterable.__iter__()
        self.remaining_data = ''

    def read(self, size):
        chunk = self.remaining_data
        try:
            while not chunk:
                chunk = next(self.iterator)
        except StopIteration:
            return ''
        return_value = chunk[0:size]
        self.remaining_data = chunk[size:]
        return return_value


class SSPDiskAdapter(object):
    """Provides a disk adapter for Shared Storage Pools.

    Shared Storage Pools are a clustered file system technology that can link
    together Virtual I/O Servers.

    This adapter provides the connection for nova ephemeral storage (not
    Cinder) to connect to virtual machines.
    """

    capabilities = {
        'shared_storage': True,
    }

    def __init__(self, adapter, host_uuid):
        """Initialize the SSPDiskAdapter.

        :param adapter: pypowervm.adapter.Adapter for the PowerVM REST API.
        :param host_uuid: PowerVM UUID of the managed system.
        """
        self._adapter = adapter
        self._host_uuid = host_uuid
        try:
            self._clust = pvm_clust.Cluster.get(self._adapter)[0]
            self._ssp = pvm_stg.SSP.get_by_href(
                self._adapter, self._clust.ssp_uri)
            self._tier = tsk_stg.default_tier_for_ssp(self._ssp)
        except pvm_exc.Error:
            LOG.exception("A unique PowerVM Cluster and Shared Storage Pool "
                          "is required in the default Tier.")
            raise exception.NotFound()

        LOG.info(
            "SSP Storage driver initialized. Cluster '%(clust_name)s'; "
            "SSP '%(ssp_name)s'; Tier '%(tier_name)s'",
            {'clust_name': self._clust.name, 'ssp_name': self._ssp.name,
             'tier_name': self._tier.name})

    @property
    def capacity(self):
        """Capacity of the storage in gigabytes."""
        # Retrieving the Tier is faster (because don't have to refresh LUs.)
        return float(self._tier.refresh().capacity)

    @property
    def capacity_used(self):
        """Capacity of the storage in gigabytes that is used."""
        self._ssp = self._ssp.refresh()
        return float(self._ssp.capacity) - float(self._ssp.free_space)

    def detach_disk(self, instance):
        """Detaches the storage adapters from the disk.

        :param instance: instance from which to detach the image.
        :return: A list of all the backing storage elements that were detached
                 from the I/O Server and VM.
        """
        stg_ftsk = tsk_par.build_active_vio_feed_task(
            self._adapter, name='ssp', xag=[pvm_const.XAG.VIO_SMAP])

        lpar_uuid = vm.get_pvm_uuid(instance)
        match_func = tsk_map.gen_match_func(pvm_stg.LU)

        def rm_func(vwrap):
            LOG.info("Removing SSP disk connection to VIOS %s.",
                     vwrap.name, instance=instance)
            return tsk_map.remove_maps(vwrap, lpar_uuid,
                                       match_func=match_func)

        # Remove the mapping from *each* VIOS on the LPAR's host.
        # The LPAR's host has to be self.host_uuid, else the PowerVM API will
        # fail.
        #
        # Note - this may not be all the VIOSes on the system...just the ones
        # in the SSP cluster.
        #
        # The mappings will normally be the same on all VIOSes, unless a VIOS
        # was down when a disk was added.  So for the return value, we need to
        # collect the union of all relevant mappings from all VIOSes.
        lu_set = set()
        for vios_uuid in self._vios_uuids:
            # Add the remove for the VIO
            stg_ftsk.wrapper_tasks[vios_uuid].add_functor_subtask(rm_func)

            # Find the active LUs so that a delete op knows what to remove.
            vios_w = stg_ftsk.wrapper_tasks[vios_uuid].wrapper
            mappings = tsk_map.find_maps(vios_w.scsi_mappings,
                                         client_lpar_id=lpar_uuid,
                                         match_func=match_func)
            if mappings:
                lu_set.update([x.backing_storage for x in mappings])

        stg_ftsk.execute()

        return list(lu_set)

    def delete_disks(self, storage_elems):
        """Removes the disks specified by the mappings.

        :param storage_elems: A list of the storage elements (LU
                              ElementWrappers) that are to be deleted.  Derived
                              from the return value from detach_disk.
        """
        tsk_stg.rm_tier_storage(storage_elems, tier=self._tier)

    def create_disk_from_image(self, context, instance, image_meta):
        """Creates a boot disk and links the specified image to it.

        If the specified image has not already been uploaded, an Image LU is
        created for it.  A Disk LU is then created for the instance and linked
        to the Image LU.

        :param context: nova context used to retrieve image from glance
        :param instance: instance to create the disk for.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        :return: The backing pypowervm LU storage object that was created.
        """
        LOG.info('SSP: Create boot disk from image %s.', image_meta.id,
                 instance=instance)

        image_lu = tsk_cs.get_or_upload_image_lu(
            self._tier, pvm_u.sanitize_file_name_for_api(
                image_meta.name, prefix=DiskType.IMAGE + '_',
                suffix='_' + image_meta.checksum),
            random.choice(self._vios_uuids), IterableToFileAdapter(
                IMAGE_API.download(context, image_meta.id)), image_meta.size,
            upload_type=tsk_stg.UploadType.IO_STREAM)

        boot_lu_name = pvm_u.sanitize_file_name_for_api(
            instance.name, prefix=DiskType.BOOT + '_')

        LOG.info('SSP: Disk name is %s', boot_lu_name, instance=instance)

        return tsk_stg.crt_lu(
            self._tier, boot_lu_name, instance.flavor.root_gb,
            typ=pvm_stg.LUType.DISK, clone=image_lu)[1]

    def attach_disk(self, instance, disk_info, stg_ftsk):
        """Connects the disk image to the Virtual Machine.

        :param instance: nova instance to which to attach the disk.
        :param disk_info: The pypowervm storage element returned from
                          create_disk_from_image.  Ex. VOptMedia, VDisk, LU,
                          or PV.
        :param stg_ftsk: FeedTask to defer storage connectivity operations.
        """
        # Create the LU structure
        lu = pvm_stg.LU.bld_ref(self._adapter, disk_info.name, disk_info.udid)
        lpar_uuid = vm.get_pvm_uuid(instance)

        # This is the delay apply mapping
        def add_func(vios_w):
            LOG.info("Attaching SSP disk from VIOS %s.",
                     vios_w.name, instance=instance)
            mapping = tsk_map.build_vscsi_mapping(
                self._host_uuid, vios_w, lpar_uuid, lu)
            return tsk_map.add_map(vios_w, mapping)

        # Add the mapping to *each* VIOS on the LPAR's host.
        # The LPAR's host has to be self.host_uuid, else the PowerVM API will
        # fail.
        #
        # Note: this may not be all the VIOSes on the system - just the ones
        # in the SSP cluster.
        for vios_uuid in self._vios_uuids:
            stg_ftsk.wrapper_tasks[vios_uuid].add_functor_subtask(add_func)

    @property
    def _vios_uuids(self):
        """List the UUIDs of our cluster's VIOSes on this host.

        (If a VIOS is not on this host, we can't interact with it, even if its
        URI and therefore its UUID happen to be available in the pypowervm
        wrapper.)

        :return: A list of VIOS UUID strings.
        """
        ret = []
        for n in self._clust.nodes:
            # Skip any nodes that we don't have the vios uuid or uri
            if not (n.vios_uuid and n.vios_uri):
                continue
            if self._host_uuid == pvm_u.get_req_path_uuid(
                    n.vios_uri, preserve_case=True, root=True):
                ret.append(n.vios_uuid)
        return ret
