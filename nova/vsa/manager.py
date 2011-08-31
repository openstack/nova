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
Handles all processes relating to Virtual Storage Arrays (VSA).

**Related Flags**

"""

from nova import compute
from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
from nova import volume
from nova import vsa
from nova import utils
from nova.compute import instance_types
from nova.vsa import utils as vsa_utils
from nova.vsa.api import VsaState

FLAGS = flags.FLAGS
flags.DEFINE_string('vsa_driver', 'nova.vsa.connection.get_connection',
                    'Driver to use for controlling VSAs')

LOG = logging.getLogger('nova.vsa.manager')


class VsaManager(manager.SchedulerDependentManager):
    """Manages Virtual Storage Arrays (VSAs)."""

    def __init__(self, vsa_driver=None, *args, **kwargs):
        if not vsa_driver:
            vsa_driver = FLAGS.vsa_driver
        self.driver = utils.import_object(vsa_driver)
        self.compute_manager = utils.import_object(FLAGS.compute_manager)

        self.compute_api = compute.API()
        self.volume_api = volume.API()
        self.vsa_api = vsa.API()

        if FLAGS.vsa_ec2_user_id is None or \
           FLAGS.vsa_ec2_access_key is None:
            raise exception.VSANovaAccessParamNotFound()

        super(VsaManager, self).__init__(*args, **kwargs)

    def init_host(self):
        self.driver.init_host(host=self.host)
        super(VsaManager, self).init_host()

    @exception.wrap_exception()
    def create_vsa(self, context, vsa_id):
        """Called by API if there were no BE volumes assigned"""
        LOG.debug(_("Create call received for VSA %s"), vsa_id)

        vsa_id = int(vsa_id)    # just in case

        try:
            vsa = self.vsa_api.get(context, vsa_id)
        except Exception as ex:
            msg = _("Failed to find VSA %(vsa_id)d") % locals()
            LOG.exception(msg)
            return

        return self._start_vcs(context, vsa)

    @exception.wrap_exception()
    def vsa_volume_created(self, context, vol_id, vsa_id, status):
        """Callback for volume creations"""
        LOG.debug(_("VSA ID %(vsa_id)s: Drive %(vol_id)s created. "\
                    "Status %(status)s"), locals())
        vsa_id = int(vsa_id)    # just in case

        # Get all volumes for this VSA
        # check if any of them still in creating phase
        drives = self.vsa_api.get_all_vsa_drives(context, vsa_id)
        for drive in drives:
            if drive['status'] == 'creating':
                vol_name = drive['name']
                vol_disp_name = drive['display_name']
                LOG.debug(_("Drive %(vol_name)s (%(vol_disp_name)s) still "\
                            "in creating phase - wait"), locals())
                return

        try:
            vsa = self.vsa_api.get(context, vsa_id)
        except Exception as ex:
            msg = _("Failed to find VSA %(vsa_id)d") % locals()
            LOG.exception(msg)
            return

        if len(drives) != vsa['vol_count']:
            cvol_real = len(drives)
            cvol_exp = vsa['vol_count']
            LOG.debug(_("VSA ID %(vsa_id)d: Not all volumes are created "\
                        "(%(cvol_real)d of %(cvol_exp)d)"), locals())
            return

        # all volumes created (successfully or not)
        return self._start_vcs(context, vsa, drives)

    def _start_vcs(self, context, vsa, drives=[]):
        """Start VCs for VSA """

        vsa_id = vsa['id']
        if vsa['status'] == VsaState.CREATING:
            self.vsa_api.update_vsa_status(context, vsa_id,
                                           VsaState.LAUNCHING)
        else:
            return

        # in _separate_ loop go over all volumes and mark as "attached"
        has_failed_volumes = False
        for drive in drives:
            vol_name = drive['name']
            vol_disp_name = drive['display_name']
            status = drive['status']
            LOG.info(_("VSA ID %(vsa_id)d: Drive %(vol_name)s "\
                        "(%(vol_disp_name)s) is in %(status)s state"),
                        locals())
            if status == 'available':
                try:
                    # self.volume_api.update(context, volume['id'],
                    #                   dict(attach_status="attached"))
                    pass
                except Exception as ex:
                    msg = _("Failed to update attach status for volume "
                            "%(vol_name)s. %(ex)s") % locals()
                    LOG.exception(msg)
            else:
                has_failed_volumes = True

        if has_failed_volumes:
            LOG.info(_("VSA ID %(vsa_id)d: Delete all BE volumes"), locals())
            self.vsa_api.delete_vsa_volumes(context, vsa_id, "BE", True)
            self.vsa_api.update_vsa_status(context, vsa_id,
                                           VsaState.FAILED)
            return

        # create user-data record for VC
        storage_data = vsa_utils.generate_user_data(vsa, drives)

        instance_type = instance_types.get_instance_type(
                                            vsa['instance_type_id'])

        # now start the VC instance

        vc_count = vsa['vc_count']
        LOG.info(_("VSA ID %(vsa_id)d: Start %(vc_count)d instances"),
                    locals())
        vc_instances = self.compute_api.create(context,
                instance_type,      # vsa['vsa_instance_type'],
                vsa['image_ref'],
                min_count=1,
                max_count=vc_count,
                display_name='vc-' + vsa['display_name'],
                display_description='VC for VSA ' + vsa['display_name'],
                availability_zone=vsa['availability_zone'],
                user_data=storage_data,
                metadata=dict(vsa_id=str(vsa_id)))

        self.vsa_api.update_vsa_status(context, vsa_id,
                                       VsaState.CREATED)
