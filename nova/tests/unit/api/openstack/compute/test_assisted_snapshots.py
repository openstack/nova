# Copyright 2013 Josh Durgin
# Copyright 2013 Red Hat, Inc.
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

from unittest import mock
import urllib

import fixtures
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
import webob

from nova.api.openstack.compute import assisted_volume_snapshots \
        as assisted_snaps_v21
from nova.compute import api as compute_api
from nova.compute import task_states
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


class AssistedSnapshotCreateTestCaseV21(test.NoDBTestCase):
    assisted_snaps = assisted_snaps_v21
    bad_request = exception.ValidationError

    def setUp(self):
        super(AssistedSnapshotCreateTestCaseV21, self).setUp()

        self.controller = \
            self.assisted_snaps.AssistedVolumeSnapshotsController()
        self.url = ('/v2/%s/os-assisted-volume-snapshots' %
                    fakes.FAKE_PROJECT_ID)

    @mock.patch.object(compute_api.API, 'volume_snapshot_create')
    def test_assisted_create(self, mock_volume_snapshot_create):
        mock_volume_snapshot_create.return_value = {
            'snapshot': {
                'id': uuids.snapshot_id,
                'volumeId': uuids.volume_id,
            },
        }
        req = fakes.HTTPRequest.blank(self.url)
        expected_create_info = {'type': 'qcow2',
                                'new_file': 'new_file',
                                'snapshot_id': 'snapshot_id'}
        body = {'snapshot': {'volume_id': uuids.volume_to_snapshot,
                             'create_info': expected_create_info}}
        req.method = 'POST'
        self.controller.create(req, body=body)

        mock_volume_snapshot_create.assert_called_once_with(
            req.environ['nova.context'], uuids.volume_to_snapshot,
            expected_create_info)

    def test_assisted_create_missing_create_info(self):
        req = fakes.HTTPRequest.blank(self.url)
        body = {'snapshot': {'volume_id': '1'}}
        req.method = 'POST'
        self.assertRaises(self.bad_request, self.controller.create,
                req, body=body)

    def test_assisted_create_with_unexpected_attr(self):
        req = fakes.HTTPRequest.blank(self.url)
        body = {
            'snapshot': {
                'volume_id': '1',
                'create_info': {
                    'type': 'qcow2',
                    'new_file': 'new_file',
                    'snapshot_id': 'snapshot_id'
                }
            },
            'unexpected': 0,
        }
        req.method = 'POST'
        self.assertRaises(self.bad_request, self.controller.create,
                req, body=body)

    @mock.patch('nova.objects.BlockDeviceMapping.get_by_volume',
                side_effect=exception.VolumeBDMIsMultiAttach(volume_id='1'))
    def test_assisted_create_multiattach_fails(self, bdm_get_by_volume):
        req = fakes.HTTPRequest.blank(self.url)
        body = {'snapshot':
                   {'volume_id': '1',
                    'create_info': {'type': 'qcow2',
                                    'new_file': 'new_file',
                                    'snapshot_id': 'snapshot_id'}}}
        req.method = 'POST'
        self.assertRaises(
            webob.exc.HTTPBadRequest, self.controller.create, req, body=body)

    def _test_assisted_create_instance_conflict(self, api_error):
        req = fakes.HTTPRequest.blank(self.url)
        body = {'snapshot':
                   {'volume_id': '1',
                    'create_info': {'type': 'qcow2',
                                    'new_file': 'new_file',
                                    'snapshot_id': 'snapshot_id'}}}
        req.method = 'POST'
        with mock.patch.object(compute_api.API, 'volume_snapshot_create',
                               side_effect=api_error):
            self.assertRaises(
                webob.exc.HTTPBadRequest, self.controller.create,
                req, body=body)

    def test_assisted_create_instance_invalid_state(self):
        api_error = exception.InstanceInvalidState(
            instance_uuid=FAKE_UUID, attr='task_state',
            state=task_states.SHELVING_OFFLOADING,
            method='volume_snapshot_create')
        self._test_assisted_create_instance_conflict(api_error)

    def test_assisted_create_instance_not_ready(self):
        api_error = exception.InstanceNotReady(instance_id=FAKE_UUID)
        self._test_assisted_create_instance_conflict(api_error)


class AssistedSnapshotDeleteTestCaseV21(test.NoDBTestCase):
    assisted_snaps = assisted_snaps_v21
    microversion = '2.1'

    def _check_status(self, expected_status, req, res, controller_method):
        self.assertEqual(expected_status, controller_method.wsgi_codes(req))

    def setUp(self):
        super(AssistedSnapshotDeleteTestCaseV21, self).setUp()

        self.controller = \
            self.assisted_snaps.AssistedVolumeSnapshotsController()
        self.mock_volume_snapshot_delete = self.useFixture(
            fixtures.MockPatchObject(compute_api.API,
                                     'volume_snapshot_delete')).mock
        self.url = ('/v2/%s/os-assisted-volume-snapshots' %
                    fakes.FAKE_PROJECT_ID)

    def test_assisted_delete(self):
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
        }
        req = fakes.HTTPRequest.blank(
                self.url + '?%s' %
                urllib.parse.urlencode(params),
                version=self.microversion)
        req.method = 'DELETE'
        result = self.controller.delete(req, '5')
        self._check_status(204, req, result, self.controller.delete)

    def test_assisted_delete_missing_delete_info(self):
        req = fakes.HTTPRequest.blank(self.url,
                                      version=self.microversion)
        req.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                req, '5')

    def _test_assisted_delete_instance_conflict(self, api_error):
        self.mock_volume_snapshot_delete.side_effect = api_error
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
        }
        req = fakes.HTTPRequest.blank(
                self.url + '?%s' %
                urllib.parse.urlencode(params),
                version=self.microversion)
        req.method = 'DELETE'

        self.assertRaises(
            webob.exc.HTTPBadRequest, self.controller.delete, req, '5')

    def test_assisted_delete_instance_invalid_state(self):
        api_error = exception.InstanceInvalidState(
            instance_uuid=FAKE_UUID, attr='task_state',
            state=task_states.UNSHELVING,
            method='volume_snapshot_delete')
        self._test_assisted_delete_instance_conflict(api_error)

    def test_assisted_delete_instance_not_ready(self):
        api_error = exception.InstanceNotReady(instance_id=FAKE_UUID)
        self._test_assisted_delete_instance_conflict(api_error)

    def test_delete_additional_query_parameters(self):
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
            'additional': 123
        }
        req = fakes.HTTPRequest.blank(
                self.url + '?%s' %
                urllib.parse.urlencode(params),
                version=self.microversion)
        req.method = 'DELETE'
        self.controller.delete(req, '5')

    def test_delete_duplicate_query_parameters_validation(self):
        params = [
            ('delete_info', jsonutils.dumps({'volume_id': '1'})),
            ('delete_info', jsonutils.dumps({'volume_id': '2'}))
        ]
        req = fakes.HTTPRequest.blank(
                self.url + '?%s' %
                urllib.parse.urlencode(params),
                version=self.microversion)
        req.method = 'DELETE'
        self.controller.delete(req, '5')

    def test_assisted_delete_missing_volume_id(self):
        params = {
            'delete_info': jsonutils.dumps({'something_else': '1'}),
        }
        req = fakes.HTTPRequest.blank(
                self.url + '?%s' %
                urllib.parse.urlencode(params),
                version=self.microversion)

        req.method = 'DELETE'
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.delete, req, '5')
        # This is the result of a KeyError but the only thing in the message
        # is the missing key.
        self.assertIn('volume_id', str(ex))


class AssistedSnapshotDeleteTestCaseV275(AssistedSnapshotDeleteTestCaseV21):
    assisted_snaps = assisted_snaps_v21
    microversion = '2.75'

    def test_delete_additional_query_parameters_old_version(self):
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
            'additional': 123
        }
        req = fakes.HTTPRequest.blank(
                self.url + '?%s' %
                urllib.parse.urlencode(params),
                version='2.74')
        self.controller.delete(req, 1)

    def test_delete_additional_query_parameters(self):
        req = fakes.HTTPRequest.blank(
                self.url + '?unknown=1',
                version=self.microversion)
        self.assertRaises(exception.ValidationError,
                          self.controller.delete, req, 1)
