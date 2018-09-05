# Copyright 2014 Hewlett-Packard Development Company, L.P
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

import mock
from oslo_config import cfg
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils
import webob

from nova.api.openstack.compute import server_groups as sg_v21
from nova import context
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes


CONF = cfg.CONF


class AttrDict(dict):
    def __getattr__(self, k):
        return self[k]


def server_group_template(**kwargs):
    sgroup = kwargs.copy()
    sgroup.setdefault('name', 'test')
    return sgroup


def server_group_db(sg):
    attrs = sg.copy()
    if 'id' in attrs:
        attrs['uuid'] = attrs.pop('id')
    if 'policies' in attrs:
        policies = attrs.pop('policies')
        attrs['policies'] = policies
    else:
        attrs['policies'] = []
    if 'members' in attrs:
        members = attrs.pop('members')
        attrs['members'] = members
    else:
        attrs['members'] = []
    if 'metadata' in attrs:
        attrs['metadetails'] = attrs.pop('metadata')
    else:
        attrs['metadetails'] = {}
    attrs['deleted'] = 0
    attrs['deleted_at'] = None
    attrs['created_at'] = None
    attrs['updated_at'] = None
    if 'user_id' not in attrs:
        attrs['user_id'] = fakes.FAKE_USER_ID
    if 'project_id' not in attrs:
        attrs['project_id'] = fakes.FAKE_PROJECT_ID
    attrs['id'] = 7

    return AttrDict(attrs)


class ServerGroupQuotasTestV21(test.TestCase):

    def setUp(self):
        super(ServerGroupQuotasTestV21, self).setUp()
        self._setup_controller()
        self.req = fakes.HTTPRequest.blank('')

    def _setup_controller(self):
        self.controller = sg_v21.ServerGroupController()

    def _setup_quotas(self):
        pass

    def _assert_server_groups_in_use(self, project_id, user_id, in_use):
        ctxt = context.get_admin_context()
        counts = objects.InstanceGroupList.get_counts(ctxt, project_id,
                                                      user_id=user_id)
        self.assertEqual(in_use, counts['project']['server_groups'])
        self.assertEqual(in_use, counts['user']['server_groups'])

    def test_create_server_group_normal(self):
        self._setup_quotas()
        sgroup = server_group_template()
        policies = ['anti-affinity']
        sgroup['policies'] = policies
        res_dict = self.controller.create(self.req,
                                          body={'server_group': sgroup})
        self.assertEqual(res_dict['server_group']['name'], 'test')
        self.assertTrue(uuidutils.is_uuid_like(res_dict['server_group']['id']))
        self.assertEqual(res_dict['server_group']['policies'], policies)

    def test_create_server_group_quota_limit(self):
        self._setup_quotas()
        sgroup = server_group_template()
        policies = ['anti-affinity']
        sgroup['policies'] = policies
        # Start by creating as many server groups as we're allowed to.
        for i in range(CONF.quota.server_groups):
            self.controller.create(self.req, body={'server_group': sgroup})

        # Then, creating a server group should fail.
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.create,
                          self.req, body={'server_group': sgroup})

    @mock.patch('nova.objects.Quotas.check_deltas')
    def test_create_server_group_recheck_disabled(self, mock_check):
        self.flags(recheck_quota=False, group='quota')
        self._setup_quotas()
        sgroup = server_group_template()
        policies = ['anti-affinity']
        sgroup['policies'] = policies
        self.controller.create(self.req, body={'server_group': sgroup})
        ctxt = self.req.environ['nova.context']
        mock_check.assert_called_once_with(ctxt, {'server_groups': 1},
                                           ctxt.project_id, ctxt.user_id)

    def test_delete_server_group_by_admin(self):
        self._setup_quotas()
        sgroup = server_group_template()
        policies = ['anti-affinity']
        sgroup['policies'] = policies
        res = self.controller.create(self.req, body={'server_group': sgroup})
        sg_id = res['server_group']['id']
        context = self.req.environ['nova.context']

        self._assert_server_groups_in_use(context.project_id,
                                          context.user_id, 1)

        # Delete the server group we've just created.
        req = fakes.HTTPRequest.blank('', use_admin_context=True)
        self.controller.delete(req, sg_id)

        # Make sure the quota in use has been released.
        self._assert_server_groups_in_use(context.project_id,
                                          context.user_id, 0)

    @mock.patch('nova.objects.InstanceGroup.destroy')
    def test_delete_server_group_by_id(self, mock_destroy):
        self._setup_quotas()
        sg = server_group_template(id=uuids.sg1_id)

        def return_server_group(_cls, context, group_id):
            self.assertEqual(sg['id'], group_id)
            return objects.InstanceGroup(**server_group_db(sg))

        self.stub_out('nova.objects.InstanceGroup.get_by_uuid',
                      return_server_group)

        resp = self.controller.delete(self.req, uuids.sg1_id)
        mock_destroy.assert_called_once_with()

        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.controller, sg_v21.ServerGroupController):
            status_int = self.controller.delete.wsgi_code
        else:
            status_int = resp.status_int
        self.assertEqual(204, status_int)
