# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
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
Handles all requests relating to Virtual Storage Arrays (VSAs).

Experimental code. Requires special VSA image.
For assistance and guidelines pls contact
    Zadara Storage Inc & Openstack community
"""

import sys

from nova import compute
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import rpc
from nova import volume
from nova.compute import instance_types
from nova.db import base
from nova.volume import volume_types


class VsaState:
    CREATING = 'creating'       # VSA creating (not ready yet)
    LAUNCHING = 'launching'     # Launching VCs (all BE volumes were created)
    CREATED = 'created'         # VSA fully created and ready for use
    PARTIAL = 'partial'         # Some BE drives were allocated
    FAILED = 'failed'           # Some BE storage allocations failed
    DELETING = 'deleting'       # VSA started the deletion procedure


FLAGS = flags.FLAGS
flags.DEFINE_string('vsa_ec2_access_key', None,
                    'EC2 access key used by VSA for accessing nova')
flags.DEFINE_string('vsa_ec2_user_id', None,
                    'User ID used by VSA for accessing nova')
flags.DEFINE_boolean('vsa_multi_vol_creation', True,
                  'Ask scheduler to create multiple volumes in one call')
flags.DEFINE_string('vsa_volume_type_name', 'VSA volume type',
                    'Name of volume type associated with FE VSA volumes')

LOG = logging.getLogger('nova.vsa')


class API(base.Base):
    """API for interacting with the VSA manager."""

    def __init__(self, compute_api=None, volume_api=None, **kwargs):
        self.compute_api = compute_api or compute.API()
        self.volume_api = volume_api or volume.API()
        super(API, self).__init__(**kwargs)

    def _check_volume_type_correctness(self, vol_type):
        if vol_type.get('extra_specs') == None or\
           vol_type['extra_specs'].get('type') != 'vsa_drive' or\
           vol_type['extra_specs'].get('drive_type') == None or\
           vol_type['extra_specs'].get('drive_size') == None:

            raise exception.ApiError(_("Invalid drive type %s")
                                        % vol_type['name'])

    def _get_default_vsa_instance_type(self):
        return instance_types.get_instance_type_by_name(
                                FLAGS.default_vsa_instance_type)

    def _check_storage_parameters(self, context, vsa_name, storage,
                                  shared, first_index=0):
        """
        Translates storage array of disks to the list of volumes
        :param storage: List of dictionaries with following keys:
                        disk_name, num_disks, size
        :param shared: Specifies if storage is dedicated or shared.
                       For shared storage disks split into partitions
        """
        volume_params = []
        for node in storage:

            name = node.get('drive_name', None)
            num_disks = node.get('num_drives', 1)

            if name is None:
                raise exception.ApiError(_("No drive_name param found in %s")
                                            % node)
            try:
                vol_type = volume_types.get_volume_type_by_name(context, name)
            except exception.NotFound:
                raise exception.ApiError(_("Invalid drive type name %s")
                                            % name)

            self._check_volume_type_correctness(vol_type)

            # if size field present - override disk size specified in DB
            size = int(node.get('size',
                                vol_type['extra_specs'].get('drive_size')))

            if shared:
                part_size = FLAGS.vsa_part_size_gb
                total_capacity = num_disks * size
                num_volumes = total_capacity / part_size
                size = part_size
            else:
                num_volumes = num_disks
                size = 0    # special handling for full drives

            for i in range(num_volumes):
                volume_name = "drive-%03d" % first_index
                first_index += 1
                volume_desc = 'BE volume for VSA %s type %s' % \
                              (vsa_name, name)
                volume = {
                    'size': size,
                    'name': volume_name,
                    'description': volume_desc,
                    'volume_type_id': vol_type['id'],
                    }
                volume_params.append(volume)

        return volume_params

    def create(self, context, display_name='', display_description='',
                vc_count=1, instance_type=None, image_name=None,
                availability_zone=None, storage=[], shared=None):
        """
        Provision VSA instance with corresponding compute instances
        and associated volumes
        :param storage: List of dictionaries with following keys:
                        disk_name, num_disks, size
        :param shared: Specifies if storage is dedicated or shared.
                       For shared storage disks split into partitions
        """

        LOG.info(_("*** Experimental VSA code ***"))

        if vc_count > FLAGS.max_vcs_in_vsa:
            LOG.warning(_("Requested number of VCs (%d) is too high."\
                          " Setting to default"), vc_count)
            vc_count = FLAGS.max_vcs_in_vsa

        if instance_type is None:
            instance_type = self._get_default_vsa_instance_type()

        if availability_zone is None:
            availability_zone = FLAGS.storage_availability_zone

        if storage is None:
            storage = []

        if shared is None or shared == 'False' or shared == False:
            shared = False
        else:
            shared = True

        # check if image is ready before starting any work
        if image_name is None:
            image_name = FLAGS.vc_image_name
        try:
            image_service = self.compute_api.image_service
            vc_image = image_service.show_by_name(context, image_name)
            vc_image_href = vc_image['id']
        except exception.ImageNotFound:
            raise exception.ApiError(_("Failed to find configured image %s")
                                        % image_name)

        options = {
            'display_name': display_name,
            'display_description': display_description,
            'project_id': context.project_id,
            'availability_zone': availability_zone,
            'instance_type_id': instance_type['id'],
            'image_ref': vc_image_href,
            'vc_count': vc_count,
            'status': VsaState.CREATING,
        }
        LOG.info(_("Creating VSA: %s") % options)

        # create DB entry for VSA instance
        try:
            vsa_ref = self.db.vsa_create(context, options)
        except exception.Error:
            raise exception.ApiError(_(sys.exc_info()[1]))
        vsa_id = vsa_ref['id']
        vsa_name = vsa_ref['name']

        # check storage parameters
        try:
            volume_params = self._check_storage_parameters(context, vsa_name,
                                                           storage, shared)
        except exception.ApiError:
            self.db.vsa_destroy(context, vsa_id)
            raise exception.ApiError(_("Error in storage parameters: %s")
                                        % storage)

        # after creating DB entry, re-check and set some defaults
        updates = {}
        if (not hasattr(vsa_ref, 'display_name') or
                vsa_ref.display_name is None or
                vsa_ref.display_name == ''):
            updates['display_name'] = display_name = vsa_name
        updates['vol_count'] = len(volume_params)
        vsa_ref = self.update(context, vsa_id, **updates)

        # create volumes
        if FLAGS.vsa_multi_vol_creation:
            if len(volume_params) > 0:
                request_spec = {
                    'num_volumes': len(volume_params),
                    'vsa_id': str(vsa_id),
                    'volumes': volume_params,
                }

                rpc.cast(context,
                         FLAGS.scheduler_topic,
                         {"method": "create_volumes",
                          "args": {"topic": FLAGS.volume_topic,
                                   "request_spec": request_spec,
                                   "availability_zone": availability_zone}})
        else:
            # create BE volumes one-by-one
            for vol in volume_params:
                try:
                    vol_name = vol['name']
                    vol_size = vol['size']
                    vol_type_id = vol['volume_type_id']
                    LOG.debug(_("VSA ID %(vsa_id)d %(vsa_name)s: Create "\
                                "volume %(vol_name)s, %(vol_size)d GB, "\
                                "type %(vol_type_id)s"), locals())

                    vol_type = volume_types.get_volume_type(context,
                                                vol['volume_type_id'])

                    vol_ref = self.volume_api.create(context,
                                    vol_size,
                                    None,
                                    vol_name,
                                    vol['description'],
                                    volume_type=vol_type,
                                    metadata=dict(to_vsa_id=str(vsa_id)),
                                    availability_zone=availability_zone)
                except:
                    self.update_vsa_status(context, vsa_id,
                                           status=VsaState.PARTIAL)
                    raise

        if len(volume_params) == 0:
            # No BE volumes - ask VSA manager to start VCs
            rpc.cast(context,
                     FLAGS.vsa_topic,
                     {"method": "create_vsa",
                      "args": {"vsa_id": str(vsa_id)}})

        return vsa_ref

    def update_vsa_status(self, context, vsa_id, status):
        updates = dict(status=status)
        LOG.info(_("VSA ID %(vsa_id)d: Update VSA status to %(status)s"),
                    locals())
        return self.update(context, vsa_id, **updates)

    def update(self, context, vsa_id, **kwargs):
        """Updates the VSA instance in the datastore.

        :param context: The security context
        :param vsa_id: ID of the VSA instance to update
        :param kwargs: All additional keyword args are treated
                       as data fields of the instance to be
                       updated

        :returns: None
        """
        LOG.info(_("VSA ID %(vsa_id)d: Update VSA call"), locals())

        updatable_fields = ['status', 'vc_count', 'vol_count',
                            'display_name', 'display_description']
        changes = {}
        for field in updatable_fields:
            if field in kwargs:
                changes[field] = kwargs[field]

        vc_count = kwargs.get('vc_count', None)
        if vc_count is not None:
            # VP-TODO: This request may want to update number of VCs
            # Get number of current VCs and add/delete VCs appropriately
            vsa = self.get(context, vsa_id)
            vc_count = int(vc_count)
            if vc_count > FLAGS.max_vcs_in_vsa:
                LOG.warning(_("Requested number of VCs (%d) is too high."\
                              " Setting to default"), vc_count)
                vc_count = FLAGS.max_vcs_in_vsa

            if vsa['vc_count'] != vc_count:
                self.update_num_vcs(context, vsa, vc_count)
                changes['vc_count'] = vc_count

        return self.db.vsa_update(context, vsa_id, changes)

    def update_num_vcs(self, context, vsa, vc_count):
        vsa_name = vsa['name']
        old_vc_count = int(vsa['vc_count'])
        if vc_count > old_vc_count:
            add_cnt = vc_count - old_vc_count
            LOG.debug(_("Adding %(add_cnt)s VCs to VSA %(vsa_name)s."),
                        locals())
            # VP-TODO: actual code for adding new VCs

        elif vc_count < old_vc_count:
            del_cnt = old_vc_count - vc_count
            LOG.debug(_("Deleting %(del_cnt)s VCs from VSA %(vsa_name)s."),
                        locals())
            # VP-TODO: actual code for deleting extra VCs

    def _force_volume_delete(self, ctxt, volume):
        """Delete a volume, bypassing the check that it must be available."""
        host = volume['host']
        if not host:
            # Deleting volume from database and skipping rpc.
            self.db.volume_destroy(ctxt, volume['id'])
            return

        rpc.cast(ctxt,
                 self.db.queue_get_for(ctxt, FLAGS.volume_topic, host),
                 {"method": "delete_volume",
                  "args": {"volume_id": volume['id']}})

    def delete_vsa_volumes(self, context, vsa_id, direction,
                           force_delete=True):
        if direction == "FE":
            volumes = self.get_all_vsa_volumes(context, vsa_id)
        else:
            volumes = self.get_all_vsa_drives(context, vsa_id)

        for volume in volumes:
            try:
                vol_name = volume['name']
                LOG.info(_("VSA ID %(vsa_id)s: Deleting %(direction)s "\
                           "volume %(vol_name)s"), locals())
                self.volume_api.delete(context, volume['id'])
            except exception.ApiError:
                LOG.info(_("Unable to delete volume %s"), volume['name'])
                if force_delete:
                    LOG.info(_("VSA ID %(vsa_id)s: Forced delete. "\
                               "%(direction)s volume %(vol_name)s"), locals())
                    self._force_volume_delete(context, volume)

    def delete(self, context, vsa_id):
        """Terminate a VSA instance."""
        LOG.info(_("Going to try to terminate VSA ID %s"), vsa_id)

        # Delete all FrontEnd and BackEnd volumes
        self.delete_vsa_volumes(context, vsa_id, "FE", force_delete=True)
        self.delete_vsa_volumes(context, vsa_id, "BE", force_delete=True)

        # Delete all VC instances
        instances = self.compute_api.get_all(context,
                search_opts={'metadata': dict(vsa_id=str(vsa_id))})
        for instance in instances:
            name = instance['name']
            LOG.debug(_("VSA ID %(vsa_id)s: Delete instance %(name)s"),
                        locals())
            self.compute_api.delete(context, instance['id'])

        # Delete VSA instance
        self.db.vsa_destroy(context, vsa_id)

    def get(self, context, vsa_id):
        rv = self.db.vsa_get(context, vsa_id)
        return rv

    def get_all(self, context):
        if context.is_admin:
            return self.db.vsa_get_all(context)
        return self.db.vsa_get_all_by_project(context, context.project_id)

    def get_vsa_volume_type(self, context):
        name = FLAGS.vsa_volume_type_name
        try:
            vol_type = volume_types.get_volume_type_by_name(context, name)
        except exception.NotFound:
            volume_types.create(context, name,
                                extra_specs=dict(type='vsa_volume'))
            vol_type = volume_types.get_volume_type_by_name(context, name)

        return vol_type

    def get_all_vsa_instances(self, context, vsa_id):
        return self.compute_api.get_all(context,
                search_opts={'metadata': dict(vsa_id=str(vsa_id))})

    def get_all_vsa_volumes(self, context, vsa_id):
        return self.volume_api.get_all(context,
                search_opts={'metadata': dict(from_vsa_id=str(vsa_id))})

    def get_all_vsa_drives(self, context, vsa_id):
        return self.volume_api.get_all(context,
                search_opts={'metadata': dict(to_vsa_id=str(vsa_id))})
