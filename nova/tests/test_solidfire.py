# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

from nova import exception
from nova.openstack.common import log as logging
from nova import test
from nova.volume.solidfire import SolidFire

LOG = logging.getLogger(__name__)


class SolidFireVolumeTestCase(test.TestCase):
    def setUp(self):
        super(SolidFireVolumeTestCase, self).setUp()

    def fake_issue_api_request(obj, method, params):
        if method is 'GetClusterInfo':
            LOG.info('Called Fake GetClusterInfo...')
            results = {'result': {'clusterInfo':
                                  {'name': 'fake-cluster',
                                   'mvip': '1.1.1.1',
                                   'svip': '1.1.1.1',
                                   'uniqueID': 'unqid',
                                   'repCount': 2,
                                   'attributes': {}}}}
            return results

        elif method is 'AddAccount':
            LOG.info('Called Fake AddAccount...')
            return {'result': {'accountID': 25}, 'id': 1}

        elif method is 'GetAccountByName':
            LOG.info('Called Fake GetAccountByName...')
            results = {'result': {'account':
                                  {'accountID': 25,
                                   'username': params['username'],
                                   'status': 'active',
                                   'initiatorSecret': '123456789012',
                                   'targetSecret': '123456789012',
                                   'attributes': {},
                                   'volumes': [6, 7, 20]}},
                       "id": 1}
            return results

        elif method is 'CreateVolume':
            LOG.info('Called Fake CreateVolume...')
            return {'result': {'volumeID': 5}, 'id': 1}

        elif method is 'DeleteVolume':
            LOG.info('Called Fake DeleteVolume...')
            return {'result': {}, 'id': 1}

        elif method is 'ListVolumesForAccount':
            test_name = 'OS-VOLID-a720b3c0-d1f0-11e1-9b23-0800200c9a66'
            LOG.info('Called Fake ListVolumesForAccount...')
            result = {'result': {
                'volumes': [{'volumeID': 5,
                             'name': test_name,
                             'accountID': 25,
                             'sliceCount': 1,
                             'totalSize': 1048576 * 1024,
                             'enable512e': True,
                             'access': "readWrite",
                             'status': "active",
                             'attributes':None,
                             'qos': None,
                             'iqn': test_name}]}}
            return result

        else:
            LOG.error('Crap, unimplemented API call in Fake:%s' % method)

    def fake_issue_api_request_no_volume(obj, method, params):
        if method is 'ListVolumesForAccount':
            LOG.info('Called Fake ListVolumesForAccount...')
            return {'result': {'volumes': []}}
        else:
            return obj.fake_issue_api_request(method, params)

    def fake_issue_api_request_fails(obj, method, params):
        return {'error': {'code': 000,
                          'name': 'DummyError',
                          'message': 'This is a fake error response'},
                'id': 1}

    def fake_volume_get(obj, key, default=None):
        return {'qos': 'fast'}

    def test_create_volume(self):
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}
        sfv = SolidFire()
        model_update = sfv.create_volume(testvol)

    def test_create_volume_with_qos(self):
        preset_qos = {}
        preset_qos['qos'] = 'fast'
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request)

        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'metadata': [preset_qos]}

        sfv = SolidFire()
        model_update = sfv.create_volume(testvol)

    def test_create_volume_fails(self):
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}
        sfv = SolidFire()
        self.assertRaises(exception.SolidFireAPIDataException,
                          sfv.create_volume, testvol)

    def test_create_sfaccount(self):
        sfv = SolidFire()
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request)
        account = sfv._create_sfaccount('project-id')
        self.assertNotEqual(account, None)

    def test_create_sfaccount_fails(self):
        sfv = SolidFire()
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        account = sfv._create_sfaccount('project-id')
        self.assertEqual(account, None)

    def test_get_sfaccount_by_name(self):
        sfv = SolidFire()
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request)
        account = sfv._get_sfaccount_by_name('some-name')
        self.assertNotEqual(account, None)

    def test_get_sfaccount_by_name_fails(self):
        sfv = SolidFire()
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        account = sfv._get_sfaccount_by_name('some-name')
        self.assertEqual(account, None)

    def test_delete_volume(self):
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}
        sfv = SolidFire()
        model_update = sfv.delete_volume(testvol)

    def test_delete_volume_fails_no_volume(self):
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request_no_volume)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}
        sfv = SolidFire()
        self.assertRaises(exception.VolumeNotFound,
                          sfv.delete_volume, testvol)

    def test_delete_volume_fails_account_lookup(self):
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66'}
        sfv = SolidFire()
        self.assertRaises(exception.SfAccountNotFound,
                          sfv.delete_volume,
                          testvol)

    def test_get_cluster_info(self):
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request)
        sfv = SolidFire()
        sfv._get_cluster_info()

    def test_get_cluster_info_fail(self):
        self.stubs.Set(SolidFire, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        sfv = SolidFire()
        self.assertRaises(exception.SolidFireAPIException,
                          sfv._get_cluster_info)
