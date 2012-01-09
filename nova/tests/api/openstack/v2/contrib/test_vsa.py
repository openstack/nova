# Copyright 2011 OpenStack LLC.
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

import datetime
import json

from lxml import etree
import stubout
import webob

from nova.api.openstack.v2.contrib import virtual_storage_arrays as vsa_ext
from nova import context
import nova.db
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova.tests.api.openstack import fakes
from nova import volume
from nova import vsa


FLAGS = flags.FLAGS

LOG = logging.getLogger('nova.tests.api.openstack.v2.contrib.test_vsa')

last_param = {}


def _get_default_vsa_param():
    return {
        'display_name': 'Test_VSA_name',
        'display_description': 'Test_VSA_description',
        'vc_count': 1,
        'instance_type': 'm1.small',
        'instance_type_id': 5,
        'image_name': None,
        'availability_zone': None,
        'storage': [],
        'shared': False,
        }


def stub_vsa_create(self, context, **param):
    global last_param
    LOG.debug(_("_create: param=%s"), param)
    param['id'] = 123
    param['name'] = 'Test name'
    param['instance_type_id'] = 5
    last_param = param
    return param


def stub_vsa_delete(self, context, vsa_id):
    global last_param
    last_param = dict(vsa_id=vsa_id)

    LOG.debug(_("_delete: %s"), locals())
    if vsa_id != '123':
        raise exception.NotFound


def stub_vsa_get(self, context, vsa_id):
    global last_param
    last_param = dict(vsa_id=vsa_id)

    LOG.debug(_("_get: %s"), locals())
    if vsa_id != '123':
        raise exception.NotFound

    param = _get_default_vsa_param()
    param['id'] = vsa_id
    return param


def stub_vsa_get_all(self, context):
    LOG.debug(_("_get_all: %s"), locals())
    param = _get_default_vsa_param()
    param['id'] = 123
    return [param]


class VSAApiTest(test.TestCase):
    def setUp(self):
        super(VSAApiTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(vsa.api.API, "create", stub_vsa_create)
        self.stubs.Set(vsa.api.API, "delete", stub_vsa_delete)
        self.stubs.Set(vsa.api.API, "get", stub_vsa_get)
        self.stubs.Set(vsa.api.API, "get_all", stub_vsa_get_all)

        self.context = context.get_admin_context()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(VSAApiTest, self).tearDown()

    def test_vsa_create(self):
        global last_param
        last_param = {}

        vsa = {"displayName": "VSA Test Name",
               "displayDescription": "VSA Test Desc"}
        body = dict(vsa=vsa)
        req = webob.Request.blank('/v2/777/zadr-vsa')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        # Compare if parameters were correctly passed to stub
        self.assertEqual(last_param['display_name'], "VSA Test Name")
        self.assertEqual(last_param['display_description'], "VSA Test Desc")

        resp_dict = json.loads(resp.body)
        self.assertTrue('vsa' in resp_dict)
        self.assertEqual(resp_dict['vsa']['displayName'], vsa['displayName'])
        self.assertEqual(resp_dict['vsa']['displayDescription'],
                         vsa['displayDescription'])

    def test_vsa_create_no_body(self):
        req = webob.Request.blank('/v2/777/zadr-vsa')
        req.method = 'POST'
        req.body = json.dumps({})
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 422)

    def test_vsa_delete(self):
        global last_param
        last_param = {}

        vsa_id = 123
        req = webob.Request.blank('/v2/777/zadr-vsa/%d' % vsa_id)
        req.method = 'DELETE'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

    def test_vsa_delete_invalid_id(self):
        global last_param
        last_param = {}

        vsa_id = 234
        req = webob.Request.blank('/v2/777/zadr-vsa/%d' % vsa_id)
        req.method = 'DELETE'

        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

    def test_vsa_show(self):
        global last_param
        last_param = {}

        vsa_id = 123
        req = webob.Request.blank('/v2/777/zadr-vsa/%d' % vsa_id)
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

        resp_dict = json.loads(resp.body)
        self.assertTrue('vsa' in resp_dict)
        self.assertEqual(resp_dict['vsa']['id'], str(vsa_id))

    def test_vsa_show_invalid_id(self):
        global last_param
        last_param = {}

        vsa_id = 234
        req = webob.Request.blank('/v2/777/zadr-vsa/%d' % vsa_id)
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)
        self.assertEqual(str(last_param['vsa_id']), str(vsa_id))

    def test_vsa_index(self):
        req = webob.Request.blank('/v2/777/zadr-vsa')
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        resp_dict = json.loads(resp.body)

        self.assertTrue('vsaSet' in resp_dict)
        resp_vsas = resp_dict['vsaSet']
        self.assertEqual(len(resp_vsas), 1)

        resp_vsa = resp_vsas.pop()
        self.assertEqual(resp_vsa['id'], 123)

    def test_vsa_detail(self):
        req = webob.Request.blank('/v2/777/zadr-vsa/detail')
        req.method = 'GET'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

        resp_dict = json.loads(resp.body)

        self.assertTrue('vsaSet' in resp_dict)
        resp_vsas = resp_dict['vsaSet']
        self.assertEqual(len(resp_vsas), 1)

        resp_vsa = resp_vsas.pop()
        self.assertEqual(resp_vsa['id'], 123)


def _get_default_volume_param():
    return {
        'id': 123,
        'status': 'available',
        'size': 100,
        'availability_zone': 'nova',
        'created_at': None,
        'attach_status': 'detached',
        'name': 'vol name',
        'display_name': 'Default vol name',
        'display_description': 'Default vol description',
        'volume_type_id': 1,
        'volume_metadata': [],
        'snapshot_id': None,
        }


def stub_get_vsa_volume_type(self, context):
    return {'id': 1,
            'name': 'VSA volume type',
            'extra_specs': {'type': 'vsa_volume'}}


def stub_volume_create(self, context, size, snapshot_id, name, description,
                       **param):
    LOG.debug(_("_create: param=%s"), size)
    vol = _get_default_volume_param()
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    vol['snapshot_id'] = snapshot_id
    return vol


def stub_volume_update(self, context, **param):
    LOG.debug(_("_volume_update: param=%s"), param)
    pass


def stub_volume_delete(self, context, **param):
    LOG.debug(_("_volume_delete: param=%s"), param)
    pass


def stub_volume_get(self, context, volume_id):
    LOG.debug(_("_volume_get: volume_id=%s"), volume_id)
    vol = _get_default_volume_param()
    vol['id'] = volume_id
    meta = {'key': 'from_vsa_id', 'value': '123'}
    if volume_id == '345':
        meta = {'key': 'to_vsa_id', 'value': '123'}
    vol['volume_metadata'].append(meta)
    return vol


def stub_volume_get_notfound(self, context, volume_id):
    raise exception.NotFound


def stub_volume_get_all(self, context, search_opts):
    vol = stub_volume_get(self, context, '123')
    vol['metadata'] = search_opts['metadata']
    return [vol]


def return_vsa(context, vsa_id):
    return {'id': vsa_id}


class VSAVolumeApiTest(test.TestCase):

    def setUp(self, test_obj=None, test_objs=None):
        super(VSAVolumeApiTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(nova.db, 'vsa_get', return_vsa)
        self.stubs.Set(vsa.api.API, "get_vsa_volume_type",
                        stub_get_vsa_volume_type)

        self.stubs.Set(volume.api.API, "update", stub_volume_update)
        self.stubs.Set(volume.api.API, "delete", stub_volume_delete)
        self.stubs.Set(volume.api.API, "get", stub_volume_get)
        self.stubs.Set(volume.api.API, "get_all", stub_volume_get_all)

        self.context = context.get_admin_context()
        self.test_obj = test_obj if test_obj else "volume"
        self.test_objs = test_objs if test_objs else "volumes"

    def tearDown(self):
        self.stubs.UnsetAll()
        super(VSAVolumeApiTest, self).tearDown()

    def test_vsa_volume_create(self):
        self.stubs.Set(volume.api.API, "create", stub_volume_create)

        vol = {"size": 100,
               "displayName": "VSA Volume Test Name",
               "displayDescription": "VSA Volume Test Desc"}
        body = {self.test_obj: vol}
        req = webob.Request.blank('/v2/777/zadr-vsa/123/%s' % self.test_objs)
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'
        resp = req.get_response(fakes.wsgi_app())

        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 200)

            resp_dict = json.loads(resp.body)
            self.assertTrue(self.test_obj in resp_dict)
            self.assertEqual(resp_dict[self.test_obj]['size'],
                             vol['size'])
            self.assertEqual(resp_dict[self.test_obj]['displayName'],
                             vol['displayName'])
            self.assertEqual(resp_dict[self.test_obj]['displayDescription'],
                             vol['displayDescription'])
        else:
            self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_create_no_body(self):
        req = webob.Request.blank('/v2/777/zadr-vsa/123/%s' % self.test_objs)
        req.method = 'POST'
        req.body = json.dumps({})
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 422)
        else:
            self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_index(self):
        req = webob.Request.blank('/v2/777/zadr-vsa/123/%s' % self.test_objs)
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

    def test_vsa_volume_detail(self):
        req = webob.Request.blank('/v2/777/zadr-vsa/123/%s/detail' % \
                self.test_objs)
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

    def test_vsa_volume_show(self):
        obj_num = 234 if self.test_objs == "volumes" else 345
        req = webob.Request.blank('/v2/777/zadr-vsa/123/%s/%s' % \
                (self.test_objs, obj_num))
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)

    def test_vsa_volume_show_no_vsa_assignment(self):
        req = webob.Request.blank('/v2/777/zadr-vsa/4/%s/333' % \
                (self.test_objs))
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_show_no_volume(self):
        self.stubs.Set(volume.api.API, "get", stub_volume_get_notfound)

        req = webob.Request.blank('/v2/777/zadr-vsa/123/%s/333' % \
                (self.test_objs))
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 404)

    def test_vsa_volume_update(self):
        obj_num = 234 if self.test_objs == "volumes" else 345
        update = {"status": "available",
                  "displayName": "Test Display name"}
        body = {self.test_obj: update}
        req = webob.Request.blank('/v2/777/zadr-vsa/123/%s/%s' % \
                (self.test_objs, obj_num))
        req.method = 'PUT'
        req.body = json.dumps(body)
        req.headers['content-type'] = 'application/json'

        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 202)
        else:
            self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_delete(self):
        obj_num = 234 if self.test_objs == "volumes" else 345
        req = webob.Request.blank('/v2/777/zadr-vsa/123/%s/%s' % \
                (self.test_objs, obj_num))
        req.method = 'DELETE'
        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 202)
        else:
            self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_delete_no_vsa_assignment(self):
        req = webob.Request.blank('/v2/777/zadr-vsa/4/%s/333' % \
                (self.test_objs))
        req.method = 'DELETE'
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 400)

    def test_vsa_volume_delete_no_volume(self):
        self.stubs.Set(volume.api.API, "get", stub_volume_get_notfound)

        req = webob.Request.blank('/v2/777/zadr-vsa/123/%s/333' % \
                (self.test_objs))
        req.method = 'DELETE'
        resp = req.get_response(fakes.wsgi_app())
        if self.test_obj == "volume":
            self.assertEqual(resp.status_int, 404)
        else:
            self.assertEqual(resp.status_int, 400)


class VSADriveApiTest(VSAVolumeApiTest):
    def setUp(self):
        super(VSADriveApiTest, self).setUp(test_obj="drive",
                                           test_objs="drives")

    def tearDown(self):
        self.stubs.UnsetAll()
        super(VSADriveApiTest, self).tearDown()


class SerializerTestCommon(test.TestCase):
    def _verify_attrs(self, obj, tree, attrs):
        for attr in attrs:
            self.assertEqual(str(obj[attr]), tree.get(attr))


class VsaSerializerTest(SerializerTestCommon):
    def test_serialize_show_create(self):
        serializer = vsa_ext.VsaTemplate()
        exemplar = dict(
            id='vsa_id',
            name='vsa_name',
            displayName='vsa_display_name',
            displayDescription='vsa_display_desc',
            createTime=datetime.datetime.now(),
            status='active',
            vcType='vsa_instance_type',
            vcCount=24,
            driveCount=48,
            ipAddress='10.11.12.13')
        text = serializer.serialize(dict(vsa=exemplar))

        print text
        tree = etree.fromstring(text)

        self.assertEqual('vsa', tree.tag)
        self._verify_attrs(exemplar, tree, exemplar.keys())

    def test_serialize_index_detail(self):
        serializer = vsa_ext.VsaSetTemplate()
        exemplar = [dict(
                id='vsa1_id',
                name='vsa1_name',
                displayName='vsa1_display_name',
                displayDescription='vsa1_display_desc',
                createTime=datetime.datetime.now(),
                status='active',
                vcType='vsa1_instance_type',
                vcCount=24,
                driveCount=48,
                ipAddress='10.11.12.13'),
                    dict(
                id='vsa2_id',
                name='vsa2_name',
                displayName='vsa2_display_name',
                displayDescription='vsa2_display_desc',
                createTime=datetime.datetime.now(),
                status='active',
                vcType='vsa2_instance_type',
                vcCount=42,
                driveCount=84,
                ipAddress='11.12.13.14')]
        text = serializer.serialize(dict(vsaSet=exemplar))

        print text
        tree = etree.fromstring(text)

        self.assertEqual('vsaSet', tree.tag)
        self.assertEqual(len(exemplar), len(tree))
        for idx, child in enumerate(tree):
            self.assertEqual('vsa', child.tag)
            self._verify_attrs(exemplar[idx], child, exemplar[idx].keys())


class VsaVolumeSerializerTest(SerializerTestCommon):
    show_serializer = vsa_ext.VsaVolumeTemplate
    index_serializer = vsa_ext.VsaVolumesTemplate
    object = 'volume'
    objects = 'volumes'

    def _verify_voldrive(self, vol, tree):
        self.assertEqual(self.object, tree.tag)

        self._verify_attrs(vol, tree, ('id', 'status', 'size',
                                       'availabilityZone', 'createdAt',
                                       'displayName', 'displayDescription',
                                       'volumeType', 'vsaId', 'name'))

        for child in tree:
            self.assertTrue(child.tag in ('attachments', 'metadata'))
            if child.tag == 'attachments':
                self.assertEqual(1, len(child))
                self.assertEqual('attachment', child[0].tag)
                self._verify_attrs(vol['attachments'][0], child[0],
                                   ('id', 'volumeId', 'serverId', 'device'))
            elif child.tag == 'metadata':
                not_seen = set(vol['metadata'].keys())
                for gr_child in child:
                    self.assertTrue(gr_child.tag in not_seen)
                    self.assertEqual(str(vol['metadata'][gr_child.tag]),
                                     gr_child.text)
                    not_seen.remove(gr_child.tag)
                self.assertEqual(0, len(not_seen))

    def test_show_create_serializer(self):
        serializer = self.show_serializer()
        raw_volume = dict(
            id='vol_id',
            status='vol_status',
            size=1024,
            availabilityZone='vol_availability',
            createdAt=datetime.datetime.now(),
            attachments=[dict(
                    id='vol_id',
                    volumeId='vol_id',
                    serverId='instance_uuid',
                    device='/foo')],
            displayName='vol_name',
            displayDescription='vol_desc',
            volumeType='vol_type',
            metadata=dict(
                foo='bar',
                baz='quux',
                ),
            vsaId='vol_vsa_id',
            name='vol_vsa_name',
            )
        text = serializer.serialize({self.object: raw_volume})

        print text
        tree = etree.fromstring(text)

        self._verify_voldrive(raw_volume, tree)

    def test_index_detail_serializer(self):
        serializer = self.index_serializer()
        raw_volumes = [dict(
                id='vol1_id',
                status='vol1_status',
                size=1024,
                availabilityZone='vol1_availability',
                createdAt=datetime.datetime.now(),
                attachments=[dict(
                        id='vol1_id',
                        volumeId='vol1_id',
                        serverId='instance_uuid',
                        device='/foo1')],
                displayName='vol1_name',
                displayDescription='vol1_desc',
                volumeType='vol1_type',
                metadata=dict(
                    foo='vol1_foo',
                    bar='vol1_bar',
                    ),
                vsaId='vol1_vsa_id',
                name='vol1_vsa_name',
                ),
                       dict(
                id='vol2_id',
                status='vol2_status',
                size=1024,
                availabilityZone='vol2_availability',
                createdAt=datetime.datetime.now(),
                attachments=[dict(
                        id='vol2_id',
                        volumeId='vol2_id',
                        serverId='instance_uuid',
                        device='/foo2')],
                displayName='vol2_name',
                displayDescription='vol2_desc',
                volumeType='vol2_type',
                metadata=dict(
                    foo='vol2_foo',
                    bar='vol2_bar',
                    ),
                vsaId='vol2_vsa_id',
                name='vol2_vsa_name',
                )]
        text = serializer.serialize({self.objects: raw_volumes})

        print text
        tree = etree.fromstring(text)

        self.assertEqual(self.objects, tree.tag)
        self.assertEqual(len(raw_volumes), len(tree))
        for idx, child in enumerate(tree):
            self._verify_voldrive(raw_volumes[idx], child)


class VsaDriveSerializerTest(VsaVolumeSerializerTest):
    show_serializer = vsa_ext.VsaDriveTemplate
    index_serializer = vsa_ext.VsaDrivesTemplate
    object = 'drive'
    objects = 'drives'


class VsaVPoolSerializerTest(SerializerTestCommon):
    def _verify_vpool(self, vpool, tree):
        self._verify_attrs(vpool, tree, ('id', 'vsaId', 'name', 'displayName',
                                         'displayDescription', 'driveCount',
                                         'protection', 'stripeSize',
                                         'stripeWidth', 'createTime',
                                         'status'))

        self.assertEqual(1, len(tree))
        self.assertEqual('driveIds', tree[0].tag)
        self.assertEqual(len(vpool['driveIds']), len(tree[0]))
        for idx, gr_child in enumerate(tree[0]):
            self.assertEqual('driveId', gr_child.tag)
            self.assertEqual(str(vpool['driveIds'][idx]), gr_child.text)

    def test_vpool_create_show_serializer(self):
        serializer = vsa_ext.VsaVPoolTemplate()
        exemplar = dict(
            id='vpool_id',
            vsaId='vpool_vsa_id',
            name='vpool_vsa_name',
            displayName='vpool_display_name',
            displayDescription='vpool_display_desc',
            driveCount=24,
            driveIds=['drive1', 'drive2', 'drive3'],
            protection='protected',
            stripeSize=1024,
            stripeWidth=2048,
            createTime=datetime.datetime.now(),
            status='available')
        text = serializer.serialize(dict(vpool=exemplar))

        print text
        tree = etree.fromstring(text)

        self._verify_vpool(exemplar, tree)

    def test_vpool_index_serializer(self):
        serializer = vsa_ext.VsaVPoolsTemplate()
        exemplar = [dict(
                id='vpool1_id',
                vsaId='vpool1_vsa_id',
                name='vpool1_vsa_name',
                displayName='vpool1_display_name',
                displayDescription='vpool1_display_desc',
                driveCount=24,
                driveIds=['drive1', 'drive2', 'drive3'],
                protection='protected',
                stripeSize=1024,
                stripeWidth=2048,
                createTime=datetime.datetime.now(),
                status='available'),
                    dict(
                id='vpool2_id',
                vsaId='vpool2_vsa_id',
                name='vpool2_vsa_name',
                displayName='vpool2_display_name',
                displayDescription='vpool2_display_desc',
                driveCount=42,
                driveIds=['drive4', 'drive5', 'drive6'],
                protection='protected',
                stripeSize=512,
                stripeWidth=256,
                createTime=datetime.datetime.now(),
                status='available')]
        text = serializer.serialize(dict(vpools=exemplar))

        print text
        tree = etree.fromstring(text)

        self.assertEqual('vpools', tree.tag)
        self.assertEqual(len(exemplar), len(tree))
        for idx, child in enumerate(tree):
            self._verify_vpool(exemplar[idx], child)
