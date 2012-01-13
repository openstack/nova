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

import webob
from lxml import etree

from nova.api import auth
from nova.api.openstack import compute
from nova.api.openstack.compute import wsgi
from nova.api.openstack.compute.contrib import cloudpipe
from nova import context
from nova import db
from nova import flags
from nova import test
from nova.tests.api.openstack import fakes
from nova import utils


EMPTY_INSTANCE_LIST = True
FLAGS = flags.FLAGS


class FakeProject(object):
    def __init__(self, id, name, manager, desc, members, ip, port):
        self.id = id
        self.name = name
        self.project_manager_id = manager
        self.description = desc
        self.member_ids = members
        self.vpn_ip = ip
        self.vpn_port = port


def fake_vpn_instance():
    return {'id': 7, 'image_id': FLAGS.vpn_image_id, 'vm_state': 'active',
            'created_at': utils.parse_strtime('1981-10-20T00:00:00.000000'),
            'uuid': 7777}


def fake_vpn_instance_low_id():
    return {'id': 4, 'image_id': FLAGS.vpn_image_id, 'vm_state': 'active',
            'created_at': utils.parse_strtime('1981-10-20T00:00:00.000000')}


def fake_project():
    proj = FakeProject(1, '1', 'fakeuser', '', [1], '127.0.0.1', 22)
    return proj


def db_instance_get_all_by_project(self, project_id):
    if EMPTY_INSTANCE_LIST:
        return []
    else:
        return [fake_vpn_instance()]


def db_security_group_exists(context, project_id, group_name):
    # used in pipelib
    return True


def pipelib_launch_vpn_instance(self, project_id, user_id):
    global EMPTY_INSTANCE_LIST
    EMPTY_INSTANCE_LIST = False


def auth_manager_get_project(self, project_id):
    return fake_project()


def auth_manager_get_projects(self):
    return [fake_project()]


def utils_vpn_ping(addr, port, timoeout=0.05, session_id=None):
    return True


def better_not_call_this(*args, **kwargs):
    raise Exception("You should not have done that")


class FakeAuthManager(object):
    def get_projects(self):
        return [fake_project()]

    def get_project(self, project_id):
        return fake_project()


class CloudpipeTest(test.TestCase):

    def setUp(self):
        super(CloudpipeTest, self).setUp()
        self.flags(allow_admin_api=True)
        self.app = fakes.wsgi_app()
        inner_app = compute.APIRouter()
        self.context = context.RequestContext('fake', 'fake', is_admin=True)
        self.app = auth.InjectContext(self.context, inner_app)
        route = inner_app.map.match('/1234/os-cloudpipe')
        self.controller = route['controller'].controller
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.stubs.Set(db, "instance_get_all_by_project",
                       db_instance_get_all_by_project)
        self.stubs.Set(db, "security_group_exists",
                       db_security_group_exists)
        self.stubs.SmartSet(self.controller.cloudpipe, "launch_vpn_instance",
                            pipelib_launch_vpn_instance)
        #self.stubs.SmartSet(self.controller.auth_manager, "get_project",
        #                    auth_manager_get_project)
        #self.stubs.SmartSet(self.controller.auth_manager, "get_projects",
        #                    auth_manager_get_projects)
        # NOTE(todd): The above code (just setting the stub, not invoking it)
        # causes failures in AuthManagerLdapTestCase.  So use a fake object.
        self.controller.auth_manager = FakeAuthManager()
        self.stubs.Set(utils, 'vpn_ping', utils_vpn_ping)
        global EMPTY_INSTANCE_LIST
        EMPTY_INSTANCE_LIST = True

    def test_cloudpipe_list_none_running(self):
        """Should still get an entry per-project, just less descriptive."""
        req = webob.Request.blank('/fake/os-cloudpipe')
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        response = {'cloudpipes': [{'project_id': 1, 'public_ip': '127.0.0.1',
                     'public_port': 22, 'state': 'pending'}]}
        self.assertEqual(res_dict, response)

    def test_cloudpipe_list(self):
        global EMPTY_INSTANCE_LIST
        EMPTY_INSTANCE_LIST = False
        req = webob.Request.blank('/fake/os-cloudpipe')
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        response = {'cloudpipes': [{'project_id': 1, 'public_ip': '127.0.0.1',
                     'public_port': 22, 'state': 'running',
                     'instance_id': 7777,
                     'created_at': '1981-10-20T00:00:00Z'}]}
        self.assertEqual(res_dict, response)

    def test_cloudpipe_create(self):
        body = {'cloudpipe': {'project_id': 1}}
        req = webob.Request.blank('/fake/os-cloudpipe')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        response = {'instance_id': 7777}
        self.assertEqual(res_dict, response)

    def test_cloudpipe_create_already_running(self):
        global EMPTY_INSTANCE_LIST
        EMPTY_INSTANCE_LIST = False
        self.stubs.SmartSet(self.controller.cloudpipe, 'launch_vpn_instance',
                            better_not_call_this)
        body = {'cloudpipe': {'project_id': 1}}
        req = webob.Request.blank('/fake/os-cloudpipe')
        req.method = 'POST'
        req.body = json.dumps(body)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(self.app)
        self.assertEqual(res.status_int, 200)
        res_dict = json.loads(res.body)
        response = {'instance_id': 7777}
        self.assertEqual(res_dict, response)


class CloudpipesXMLSerializerTest(test.TestCase):
    def test_default_serializer(self):
        serializer = cloudpipe.CloudpipeTemplate()
        exemplar = dict(cloudpipe=dict(instance_id='1234-1234-1234-1234'))
        text = serializer.serialize(exemplar)
        tree = etree.fromstring(text)
        self.assertEqual('cloudpipe', tree.tag)
        for child in tree:
            self.assertTrue(child.tag in exemplar['cloudpipe'])
            self.assertEqual(child.text, exemplar['cloudpipe'][child.tag])

    def test_index_serializer(self):
        serializer = cloudpipe.CloudpipesTemplate()
        exemplar = dict(cloudpipes=[
                dict(cloudpipe=dict(
                        project_id='1234',
                        public_ip='1.2.3.4',
                        public_port='321',
                        instance_id='1234-1234-1234-1234',
                        created_at=utils.isotime(datetime.datetime.utcnow()),
                        state='running')),
                dict(cloudpipe=dict(
                        project_id='4321',
                        public_ip='4.3.2.1',
                        public_port='123',
                        state='pending'))])
        text = serializer.serialize(exemplar)
        tree = etree.fromstring(text)
        self.assertEqual('cloudpipes', tree.tag)
        self.assertEqual(len(exemplar['cloudpipes']), len(tree))
        for idx, cl_pipe in enumerate(tree):
            self.assertEqual('cloudpipe', cl_pipe.tag)
            kp_data = exemplar['cloudpipes'][idx]['cloudpipe']
            for child in cl_pipe:
                self.assertTrue(child.tag in kp_data)
                self.assertEqual(child.text, kp_data[child.tag])

    def test_deserializer(self):
        deserializer = wsgi.XMLDeserializer()
        exemplar = dict(cloudpipe=dict(project_id='4321'))
        intext = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                  '<cloudpipe><project_id>4321</project_id></cloudpipe>')
        result = deserializer.deserialize(intext)['body']
        self.assertEqual(result, exemplar)
