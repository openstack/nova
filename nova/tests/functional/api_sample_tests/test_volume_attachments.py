# Copyright 2012 Nebula, Inc.
# Copyright 2014 IBM Corp.
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

from nova.tests import fixtures
from nova.tests.functional.api_sample_tests import test_servers


class VolumeAttachmentsSample(test_servers.ServersSampleBase):
    sample_dir = "os-volume_attachments"

    # The 'os_compute_api:os-volumes-attachments:swap' policy is admin-only
    ADMIN_API = True

    OLD_VOLUME_ID = fixtures.CinderFixture.SWAP_OLD_VOL
    NEW_VOLUME_ID = fixtures.CinderFixture.SWAP_NEW_VOL

    def setUp(self):
        super().setUp()
        self.cinder = self.useFixture(fixtures.CinderFixture(self))
        self.server_id = self._post_server()

    def _get_vol_attachment_subs(self, subs):
        """Allows subclasses to override/supplement request/response subs"""
        return subs

    def test_attach_volume_to_server(self):
        subs = {
            'volume_id': self.OLD_VOLUME_ID,
            'device': '/dev/sdb'
        }
        subs = self._get_vol_attachment_subs(subs)
        response = self._do_post(
            'servers/%s/os-volume_attachments' % self.server_id,
            'attach-volume-to-server-req', subs)
        self._verify_response(
            'attach-volume-to-server-resp', subs, response, 200)
        return subs

    def test_list_volume_attachments(self):
        subs = self.test_attach_volume_to_server()
        # Attach another volume to the server so the response has multiple
        # which is more interesting since it's a list of dicts.
        body = {
            'volumeAttachment': {
                'volumeId': self.NEW_VOLUME_ID
            }
        }
        self.api.post_server_volume(self.server_id, body)
        response = self._do_get(
            'servers/%s/os-volume_attachments' % self.server_id)
        subs['volume_id2'] = self.NEW_VOLUME_ID
        self._verify_response(
            'list-volume-attachments-resp', subs, response, 200)

    def test_volume_attachment_detail(self):
        subs = self.test_attach_volume_to_server()
        response = self._do_get(
            'servers/%s/os-volume_attachments/%s' % (
                self.server_id, subs['volume_id']))
        self._verify_response(
            'volume-attachment-detail-resp', subs, response, 200)

    def test_volume_attachment_delete(self):
        subs = self.test_attach_volume_to_server()
        response = self._do_delete(
            'servers/%s/os-volume_attachments/%s' % (
                self.server_id, subs['volume_id']))
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)

    def test_volume_attachment_update(self):
        subs = self.test_attach_volume_to_server()
        subs['new_volume_id'] = self.NEW_VOLUME_ID
        response = self._do_put(
            'servers/%s/os-volume_attachments/%s' % (
                self.server_id, subs['volume_id']),
            'update-volume-req', subs)
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)


class VolumeAttachmentsSampleV249(VolumeAttachmentsSample):
    """Microversion 2.49 adds the "tag" parameter to the request body"""
    microversion = '2.49'
    scenarios = [('v2_49', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super().setUp()
        # Stub out ComputeManager._delete_disk_metadata since the fake virt
        # driver does not actually update the instance.device_metadata.devices
        # list with the tagged bdm disk device metadata.
        self.stub_out(
            'nova.compute.manager.ComputeManager._delete_disk_metadata',
            lambda *a, **kw: None)

    def _get_vol_attachment_subs(self, subs):
        return dict(subs, tag='foo')


class VolumeAttachmentsSampleV270(VolumeAttachmentsSampleV249):
    """Microversion 2.70 adds the "tag" parameter to the response body"""
    microversion = '2.70'
    scenarios = [('v2_70', {'api_major_version': 'v2.1'})]


class VolumeAttachmentsSampleV279(VolumeAttachmentsSampleV270):
    """Microversion 2.79 adds the "delete_on_termination" parameter to the
    request and response body.
    """
    microversion = '2.79'
    scenarios = [('v2_79', {'api_major_version': 'v2.1'})]


class VolumeAttachmentsSampleV285(VolumeAttachmentsSampleV279):
    """Microversion 2.85 adds the ``PUT
    /servers/{server_id}/os-volume_attachments/{volume_id}``
    support for specifying ``delete_on_termination`` field in the request
    body to re-config the attached volume whether to delete when the instance
    is deleted.
    """
    microversion = '2.85'
    scenarios = [('v2_85', {'api_major_version': 'v2.1'})]

    def test_volume_attachment_update(self):
        subs = self.test_attach_volume_to_server()
        attached_volume_id = subs['volume_id']
        subs['server_id'] = self.server_id
        response = self._do_put(
            'servers/%s/os-volume_attachments/%s' % (
                self.server_id, attached_volume_id),
            'update-volume-attachment-delete-flag-req', subs)
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)

        # Make sure the attached volume was changed
        attachments = self.api.api_get(
            '/servers/%s/os-volume_attachments' % self.server_id
        ).body['volumeAttachments']
        self.assertEqual(1, len(attachments))
        self.assertEqual(self.server_id, attachments[0]['serverId'])
        self.assertTrue(attachments[0]['delete_on_termination'])


class VolumeAttachmentsSampleV289(VolumeAttachmentsSampleV285):
    """Microversion 2.89 adds the "attachment_id" parameter to the
    response body of show and list.
    """
    microversion = '2.89'
    scenarios = [('v2_89', {'api_major_version': 'v2.1'})]
