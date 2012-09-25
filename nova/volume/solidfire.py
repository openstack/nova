# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
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
"""
Drivers for san-stored volumes.

The unique thing about a SAN is that we don't expect that we can run the volume
controller on the SAN hardware.  We expect to access it over SSH or some API.
"""

import base64
import httplib
import json
import random
import socket
import string
import uuid

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.volume.san import SanISCSIDriver


LOG = logging.getLogger(__name__)

sf_opts = [
    cfg.BoolOpt('sf_emulate_512',
                default=True,
                help='Set 512 byte emulation on volume creation; '),

    cfg.StrOpt('sf_mvip',
               default='',
               help='IP address of SolidFire MVIP'),

    cfg.StrOpt('sf_login',
               default='admin',
               help='Username for SF Cluster Admin'),

    cfg.StrOpt('sf_password',
               default='',
               help='Password for SF Cluster Admin'),

    cfg.BoolOpt('sf_allow_tenant_qos',
                default=True,
                help='Allow tenants to specify QOS on create'), ]

FLAGS = flags.FLAGS
FLAGS.register_opts(sf_opts)


class SolidFire(SanISCSIDriver):

    sf_qos_dict = {'slow': {'minIOPS': 100,
                            'maxIOPS': 200,
                            'burstIOPS': 200},
                   'medium': {'minIOPS': 200,
                              'maxIOPS': 400,
                              'burstIOPS': 400},
                   'fast': {'minIOPS': 500,
                            'maxIOPS': 1000,
                            'burstIOPS': 1000},
                   'performant': {'minIOPS': 2000,
                                  'maxIOPS': 4000,
                                  'burstIOPS': 4000},
                   'off': None}

    def __init__(self, *args, **kwargs):
            super(SolidFire, self).__init__(*args, **kwargs)

    def _issue_api_request(self, method_name, params):
        """All API requests to SolidFire device go through this method

        Simple json-rpc web based API calls.
        each call takes a set of paramaters (dict)
        and returns results in a dict as well.
        """

        host = FLAGS.san_ip
        # For now 443 is the only port our server accepts requests on
        port = 443

        # NOTE(john-griffith): Probably don't need this, but the idea is
        # we provide a request_id so we can correlate
        # responses with requests
        request_id = int(uuid.uuid4())  # just generate a random number

        cluster_admin = FLAGS.san_login
        cluster_password = FLAGS.san_password

        command = {'method': method_name,
                   'id': request_id}

        if params is not None:
            command['params'] = params

        payload = json.dumps(command, ensure_ascii=False)
        payload.encode('utf-8')
        # we use json-rpc, webserver needs to see json-rpc in header
        header = {'Content-Type': 'application/json-rpc; charset=utf-8'}

        if cluster_password is not None:
            # base64.encodestring includes a newline character
            # in the result, make sure we strip it off
            auth_key = base64.encodestring('%s:%s' % (cluster_admin,
                                           cluster_password))[:-1]
            header['Authorization'] = 'Basic %s' % auth_key

        LOG.debug(_("Payload for SolidFire API call: %s"), payload)
        connection = httplib.HTTPSConnection(host, port)
        connection.request('POST', '/json-rpc/1.0', payload, header)
        response = connection.getresponse()
        data = {}

        if response.status != 200:
            connection.close()
            raise exception.SolidFireAPIException(status=response.status)

        else:
            data = response.read()
            try:
                data = json.loads(data)

            except (TypeError, ValueError), exc:
                connection.close()
                msg = _("Call to json.loads() raised an exception: %s") % exc
                raise exception.SfJsonEncodeFailure(msg)

            connection.close()

        LOG.debug(_("Results of SolidFire API call: %s"), data)
        return data

    def _get_volumes_by_sfaccount(self, account_id):
        params = {'accountID': account_id}
        data = self._issue_api_request('ListVolumesForAccount', params)
        if 'result' in data:
            return data['result']['volumes']

    def _get_sfaccount_by_name(self, sf_account_name):
        sfaccount = None
        params = {'username': sf_account_name}
        data = self._issue_api_request('GetAccountByName', params)
        if 'result' in data and 'account' in data['result']:
            LOG.debug(_('Found solidfire account: %s'), sf_account_name)
            sfaccount = data['result']['account']
        return sfaccount

    def _create_sfaccount(self, nova_project_id):
        """Create account on SolidFire device if it doesn't already exist.

        We're first going to check if the account already exits, if it does
        just return it.  If not, then create it.
        """

        sf_account_name = socket.getfqdn() + '-' + nova_project_id
        sfaccount = self._get_sfaccount_by_name(sf_account_name)
        if sfaccount is None:
            LOG.debug(_('solidfire account: %s does not exist, create it...'),
                      sf_account_name)
            chap_secret = self._generate_random_string(12)
            params = {'username': sf_account_name,
                      'initiatorSecret': chap_secret,
                      'targetSecret': chap_secret,
                      'attributes': {}}
            data = self._issue_api_request('AddAccount', params)
            if 'result' in data:
                sfaccount = self._get_sfaccount_by_name(sf_account_name)

        return sfaccount

    def _get_cluster_info(self):
        params = {}
        data = self._issue_api_request('GetClusterInfo', params)
        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

        return data['result']

    def _do_export(self, volume):
        """Gets the associated account, retrieves CHAP info and updates."""

        sfaccount_name = '%s-%s' % (socket.getfqdn(), volume['project_id'])
        sfaccount = self._get_sfaccount_by_name(sfaccount_name)

        model_update = {}
        model_update['provider_auth'] = ('CHAP %s %s'
                                         % (sfaccount['username'],
                                            sfaccount['targetSecret']))

        return model_update

    def _generate_random_string(self, length):
        """Generates random_string to use for CHAP password."""

        char_set = string.ascii_uppercase + string.digits
        return ''.join(random.sample(char_set, length))

    def _do_volume_create(self, project_id, params):
        cluster_info = self._get_cluster_info()
        iscsi_portal = cluster_info['clusterInfo']['svip'] + ':3260'
        sfaccount = self._create_sfaccount(project_id)
        chap_secret = sfaccount['targetSecret']

        params['accountID'] = sfaccount['accountID']
        data = self._issue_api_request('CreateVolume', params)

        if 'result' not in data or 'volumeID' not in data['result']:
            raise exception.SolidFireAPIDataException(data=data)

        volume_id = data['result']['volumeID']

        volume_list = self._get_volumes_by_sfaccount(sfaccount['accountID'])

        iqn = None
        for v in volume_list:
            if v['volumeID'] == volume_id:
                iqn = v['iqn']
                break

        model_update = {}

        # NOTE(john-griffith): SF volumes are always at lun 0
        model_update['provider_location'] = ('%s %s %s'
                                             % (iscsi_portal, iqn, 0))
        model_update['provider_auth'] = ('CHAP %s %s'
                                         % (sfaccount['username'],
                                         chap_secret))

        return model_update

    def create_volume(self, volume):
        """Create volume on SolidFire device.

        The account is where CHAP settings are derived from, volume is
        created and exported.  Note that the new volume is immediately ready
        for use.

        One caveat here is that an existing user account must be specified
        in the API call to create a new volume.  We use a set algorithm to
        determine account info based on passed in nova volume object.  First
        we check to see if the account already exists (and use it), or if it
        does not already exist, we'll go ahead and create it.

        For now, we're just using very basic settings, QOS is
        turned off, 512 byte emulation is off etc.  Will be
        looking at extensions for these things later, or
        this module can be hacked to suit needs.
        """
        GB = 1048576 * 1024
        slice_count = 1
        attributes = {}
        qos = {}
        qos_keys = ['minIOPS', 'maxIOPS', 'burstIOPS']
        valid_presets = self.sf_qos_dict.keys()

        if FLAGS.sf_allow_tenant_qos and \
                volume.get('volume_metadata')is not None:

            #First look to see if they included a preset
            presets = [i.value for i in volume.get('volume_metadata')
                       if i.key == 'sf-qos' and i.value in valid_presets]
            if len(presets) > 0:
                if len(presets) > 1:
                    LOG.warning(_('More than one valid preset was '
                                  'detected, using %s') % presets[0])
                qos = self.sf_qos_dict[presets[0]]
            else:
                #if there was no preset, look for explicit settings
                for i in volume.get('volume_metadata'):
                    if i.key in qos_keys:
                        qos[i.key] = int(i.value)

        params = {'name': 'OS-VOLID-%s' % volume['id'],
                  'accountID': None,
                  'sliceCount': slice_count,
                  'totalSize': volume['size'] * GB,
                  'enable512e': FLAGS.sf_emulate_512,
                  'attributes': attributes,
                  'qos': qos}

        return self._do_volume_create(volume['project_id'], params)

    def delete_volume(self, volume, is_snapshot=False):
        """Delete SolidFire Volume from device.

        SolidFire allows multipe volumes with same name,
        volumeID is what's guaranteed unique.

        """

        LOG.debug(_("Enter SolidFire delete_volume..."))
        sf_account_name = socket.getfqdn() + '-' + volume['project_id']
        sfaccount = self._get_sfaccount_by_name(sf_account_name)
        if sfaccount is None:
            raise exception.SfAccountNotFound(account_name=sf_account_name)

        params = {'accountID': sfaccount['accountID']}
        data = self._issue_api_request('ListVolumesForAccount', params)
        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

        if is_snapshot:
            seek = 'OS-SNAPID-%s' % (volume['id'])
        else:
            seek = 'OS-VOLID-%s' % volume['id']
            #params = {'name': 'OS-VOLID-:%s' % volume['id'],

        found_count = 0
        volid = -1
        for v in data['result']['volumes']:
            if v['name'] == seek:
                found_count += 1
                volid = v['volumeID']

        if found_count == 0:
            raise exception.VolumeNotFound(volume_id=volume['id'])

        if found_count > 1:
            LOG.debug(_("Deleting volumeID: %s"), volid)
            raise exception.DuplicateSfVolumeNames(vol_name=volume['id'])

        params = {'volumeID': volid}
        data = self._issue_api_request('DeleteVolume', params)
        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

        LOG.debug(_("Leaving SolidFire delete_volume"))

    def ensure_export(self, context, volume):
        LOG.debug(_("Executing SolidFire ensure_export..."))
        return self._do_export(volume)

    def create_export(self, context, volume):
        LOG.debug(_("Executing SolidFire create_export..."))
        return self._do_export(volume)

    def _do_create_snapshot(self, snapshot, snapshot_name):
        """Creates a snapshot."""
        LOG.debug(_("Enter SolidFire create_snapshot..."))
        sf_account_name = socket.getfqdn() + '-' + snapshot['project_id']
        sfaccount = self._get_sfaccount_by_name(sf_account_name)
        if sfaccount is None:
            raise exception.SfAccountNotFound(account_name=sf_account_name)

        params = {'accountID': sfaccount['accountID']}
        data = self._issue_api_request('ListVolumesForAccount', params)
        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

        found_count = 0
        volid = -1
        for v in data['result']['volumes']:
            if v['name'] == 'OS-VOLID-%s' % snapshot['volume_id']:
                found_count += 1
                volid = v['volumeID']

        if found_count == 0:
            raise exception.VolumeNotFound(volume_id=snapshot['volume_id'])
        if found_count != 1:
            raise exception.DuplicateSfVolumeNames(
                vol_name='OS-VOLID-%s' % snapshot['volume_id'])

        params = {'volumeID': int(volid),
                  'name': snapshot_name,
                  'attributes': {'OriginatingVolume': volid}}

        data = self._issue_api_request('CloneVolume', params)
        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

        return (data, sfaccount)

    def delete_snapshot(self, snapshot):
        self.delete_volume(snapshot, True)

    def create_snapshot(self, snapshot):
        snapshot_name = 'OS-SNAPID-%s' % (
                        snapshot['id'])
        (data, sf_account) = self._do_create_snapshot(snapshot, snapshot_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        cluster_info = self._get_cluster_info()
        iscsi_portal = cluster_info['clusterInfo']['svip'] + ':3260'
        sfaccount = self._create_sfaccount(snapshot['project_id'])
        chap_secret = sfaccount['targetSecret']
        snapshot_name = 'OS-VOLID-%s' % volume['id']

        (data, sf_account) = self._do_create_snapshot(snapshot, snapshot_name)

        if 'result' not in data or 'volumeID' not in data['result']:
            raise exception.SolidFireAPIDataException(data=data)

        volume_id = data['result']['volumeID']
        volume_list = self._get_volumes_by_sfaccount(sf_account['accountID'])
        iqn = None
        for v in volume_list:
            if v['volumeID'] == volume_id:
                iqn = v['iqn']
                break

        model_update = {}

        # NOTE(john-griffith): SF volumes are always at lun 0
        model_update['provider_location'] = ('%s %s %s'
                                             % (iscsi_portal, iqn, 0))
        model_update['provider_auth'] = ('CHAP %s %s'
                                         % (sfaccount['username'],
                                            chap_secret))
        return model_update
