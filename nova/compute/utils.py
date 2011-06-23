# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 VA Linux Systems Japan K.K
# Copyright (c) 2011 Isaku Yamahata
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

from nova import volume


def terminate_volumes(db, context, instance_id):
    """delete volumes of delete_on_termination=True in block device mapping"""
    volume_api = volume.API()
    for bdm in db.block_device_mapping_get_all_by_instance(context,
                                                           instance_id):
        #LOG.debug(_("terminating bdm %s") % bdm)
        if bdm['volume_id'] and bdm['delete_on_termination']:
            volume_api.delete(context, bdm['volume_id'])
        db.block_device_mapping_destroy(context, bdm['id'])
