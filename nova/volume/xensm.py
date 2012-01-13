# Copyright (c) 2011 Citrix Systems, Inc.
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

from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.volume.driver import VolumeDriver
from nova.virt.xenapi_conn import XenAPISession
from nova.virt.xenapi.volumeops import VolumeOps

LOG = logging.getLogger("nova.volume.xensm")
FLAGS = flags.FLAGS


class XenSMDriver(VolumeDriver):

    def _convert_config_params(self, conf_str):
        params = dict([item.split("=") for item in conf_str.split()])
        return params

    def _get_introduce_sr_keys(self, params):
        if 'name_label' in params:
            del params['name_label']
        keys = params.keys()
        keys.append('sr_type')
        return keys

    def _create_storage_repo(self, context, backend_ref):
        """Either creates or introduces SR on host
        depending on whether it exists in xapi db."""
        params = self._convert_config_params(backend_ref['config_params'])
        if 'name_label' in params:
            label = params['name_label']
            del params['name_label']
        else:
            label = 'SR-' + str(backend_ref['id'])

        params['sr_type'] = backend_ref['sr_type']

        if backend_ref['sr_uuid'] is None:
            # run the sr create command
            try:
                LOG.debug(_('SR name = %s') % label)
                LOG.debug(_('Params: %s') % str(params))
                sr_uuid = self._volumeops.create_sr(label, params)
            # update sr_uuid and created in db
            except Exception as ex:
                LOG.debug(_("Failed to create sr %s...continuing") \
                          % str(backend_ref['id']))
                raise exception.Error(_('Create failed'))

            LOG.debug(_('SR UUID of new SR is: %s') % sr_uuid)
            try:
                self.db.sm_backend_conf_update(context,
                                               backend_ref['id'],
                                               dict(sr_uuid=sr_uuid))
            except Exception as ex:
                LOG.exception(ex)
                raise exception.Error(_("Failed to update db"))

        else:
            # sr introduce, if not already done
            try:
                self._volumeops.introduce_sr(backend_ref['sr_uuid'], label,
                                              params)
            except Exception as ex:
                LOG.exception(ex)
                LOG.debug(_("Failed to introduce sr %s...continuing") \
                          % str(backend_ref['id']))

    def _create_storage_repos(self, context):
        """Create/Introduce storage repositories at start."""
        backends = self.db.sm_backend_conf_get_all(context)
        for backend in backends:
            try:
                self._create_storage_repo(context, backend)
            except Exception as ex:
                LOG.exception(ex)
                raise exception.Error(_('Failed to reach backend %d') \
                                      % backend['id'])

    def __init__(self, *args, **kwargs):
        """Connect to the hypervisor."""

        # This driver leverages Xen storage manager, and hence requires
        # hypervisor to be Xen
        if FLAGS.connection_type != 'xenapi':
            raise exception.Error(_('XenSMDriver requires xenapi connection'))

        url = FLAGS.xenapi_connection_url
        username = FLAGS.xenapi_connection_username
        password = FLAGS.xenapi_connection_password
        try:
            session = XenAPISession(url, username, password)
            self._volumeops = VolumeOps(session)
        except Exception as ex:
            LOG.exception(ex)
            raise exception.Error(_("Failed to initiate session"))

        super(XenSMDriver, self).__init__(execute=utils.execute,
                                          sync_exec=utils.execute,
                                          *args, **kwargs)

    def do_setup(self, ctxt):
        """Setup includes creating or introducing storage repos
           existing in the database and destroying deleted ones."""

        # TODO purge storage repos
        self.ctxt = ctxt
        self._create_storage_repos(ctxt)

    def create_volume(self, volume):
        """Creates a logical volume. Can optionally return a Dictionary of
        changes to the volume object to be persisted."""

        # For now the scheduling logic will be to try to fit the volume in
        # the first available backend.
        # TODO better scheduling once APIs are in place
        sm_vol_rec = None
        backends = self.db.sm_backend_conf_get_all(self.ctxt)
        for backend in backends:
            # Ensure that storage repo exists, if not create.
            # This needs to be done because if nova compute and
            # volume are both running on this host, then, as a
            # part of detach_volume, compute could potentially forget SR
            self._create_storage_repo(self.ctxt, backend)
            sm_vol_rec = self._volumeops.\
                              create_volume_for_sm(volume,
                                                   backend['sr_uuid'])
            if sm_vol_rec:
                LOG.debug(_('Volume will be created in backend - %d') \
                          % backend['id'])
                break

        if sm_vol_rec:
            # Update db
            sm_vol_rec['id'] = volume['id']
            sm_vol_rec['backend_id'] = backend['id']
            try:
                self.db.sm_volume_create(self.ctxt, sm_vol_rec)
            except Exception as ex:
                LOG.exception(ex)
                raise exception.Error(_("Failed to update volume in db"))

        else:
            raise exception.Error(_('Unable to create volume'))

    def delete_volume(self, volume):

        vol_rec = self.db.sm_volume_get(self.ctxt, volume['id'])

        try:
            # If compute runs on this node, detach could have disconnected SR
            backend_ref = self.db.sm_backend_conf_get(self.ctxt,
                                                      vol_rec['backend_id'])
            self._create_storage_repo(self.ctxt, backend_ref)
            self._volumeops.delete_volume_for_sm(vol_rec['vdi_uuid'])
        except Exception as ex:
            LOG.exception(ex)
            raise exception.Error(_("Failed to delete vdi"))

        try:
            self.db.sm_volume_delete(self.ctxt, volume['id'])
        except Exception as ex:
            LOG.exception(ex)
            raise exception.Error(_("Failed to delete volume in db"))

    def local_path(self, volume):
        return str(volume['id'])

    def undiscover_volume(self, volume):
        """Undiscover volume on a remote host."""
        pass

    def discover_volume(self, context, volume):
        return str(volume['id'])

    def check_for_setup_error(self):
        pass

    def create_export(self, context, volume):
        """Exports the volume."""
        # !!! TODO
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def ensure_export(self, context, volume):
        """Safely, synchronously recreates an export for a logical volume."""
        pass

    def initialize_connection(self, volume, address):
        try:
            xensm_properties = dict(self.db.sm_volume_get(self.ctxt,
                                                          volume['id']))
        except Exception as ex:
            LOG.exception(ex)
            raise exception.Error(_("Failed to find volume in db"))

        # Keep the volume id key consistent with what ISCSI driver calls it
        xensm_properties['volume_id'] = xensm_properties['id']
        del xensm_properties['id']

        try:
            backend_conf = self.db.\
                           sm_backend_conf_get(self.ctxt,
                                               xensm_properties['backend_id'])
        except Exception as ex:
            LOG.exception(ex)
            raise exception.Error(_("Failed to find backend in db"))

        params = self._convert_config_params(backend_conf['config_params'])

        xensm_properties['flavor_id'] = backend_conf['flavor_id']
        xensm_properties['sr_uuid'] = backend_conf['sr_uuid']
        xensm_properties['sr_type'] = backend_conf['sr_type']
        xensm_properties.update(params)
        xensm_properties['introduce_sr_keys'] = self.\
                                                _get_introduce_sr_keys(params)
        return {
            'driver_volume_type': 'xensm',
            'data': xensm_properties
        }

    def terminate_connection(self, volume, address):
        pass
