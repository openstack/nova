# Copyright (c) 2012 Citrix Systems, Inc.
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

"""Tests for the aggregates admin api."""

from webob import exc

from nova.api.openstack.compute.plugins.v3 import aggregates
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import matchers

AGGREGATE_LIST = [
        {"name": "aggregate1", "id": "1", "availability_zone": "nova1"},
        {"name": "aggregate2", "id": "2", "availability_zone": "nova1"},
        {"name": "aggregate3", "id": "3", "availability_zone": "nova2"},
        {"name": "aggregate1", "id": "4", "availability_zone": "nova1"}]
AGGREGATE = {"name": "aggregate1",
                  "id": "1",
                  "availability_zone": "nova1",
                  "metadata": {"foo": "bar"},
                  "hosts": ["host1, host2"]}


class AggregateTestCase(test.NoDBTestCase):
    """Test Case for aggregates admin api."""

    def setUp(self):
        super(AggregateTestCase, self).setUp()
        self.controller = aggregates.AggregateController()
        self.req = fakes.HTTPRequest.blank('/v3/os-aggregates',
                                           use_admin_context=True)
        self.user_req = fakes.HTTPRequest.blank('/v3/os-aggregates')
        self.context = self.req.environ['nova.context']

    def test_index(self):
        def stub_list_aggregates(context):
            if context is None:
                raise Exception()
            return AGGREGATE_LIST
        self.stubs.Set(self.controller.api, 'get_aggregate_list',
                       stub_list_aggregates)

        result = self.controller.index(self.req)

        self.assertEqual(AGGREGATE_LIST, result["aggregates"])

    def test_index_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.index,
                          self.user_req)

    def test_create(self):
        def stub_create_aggregate(context, name, availability_zone):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("test", name, "name")
            self.assertEqual("nova1", availability_zone, "availability_zone")
            return AGGREGATE
        self.stubs.Set(self.controller.api, "create_aggregate",
                       stub_create_aggregate)

        result = self.controller.create(self.req, {"aggregate":
                                          {"name": "test",
                                           "availability_zone": "nova1"}})
        self.assertEqual(AGGREGATE, result["aggregate"])

    def test_create_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.create, self.user_req,
                          {"aggregate":
                              {"name": "test",
                               "availability_zone": "nova1"}})

    def test_create_with_duplicate_aggregate_name(self):
        def stub_create_aggregate(context, name, availability_zone):
            raise exception.AggregateNameExists(aggregate_name=name)
        self.stubs.Set(self.controller.api, "create_aggregate",
                       stub_create_aggregate)

        self.assertRaises(exc.HTTPConflict, self.controller.create,
                          self.req, {"aggregate":
                                     {"name": "test",
                                      "availability_zone": "nova1"}})

    def test_create_with_incorrect_availability_zone(self):
        def stub_create_aggregate(context, name, availability_zone):
            raise exception.InvalidAggregateAction(action='create_aggregate',
                                                   aggregate_id="'N/A'",
                                                   reason='invalid zone')

        self.stubs.Set(self.controller.api, "create_aggregate",
                       stub_create_aggregate)

        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, {"aggregate":
                                     {"name": "test",
                                      "availability_zone": "nova_bad"}})

    def test_create_with_no_aggregate(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          self.req, {"foo":
                                     {"name": "test",
                                      "availability_zone": "nova1"}})

    def test_create_with_no_name(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          self.req, {"aggregate":
                                     {"availability_zone": "nova1"}})

    def test_create_with_no_availability_zone(self):
        def stub_create_aggregate(context, name, availability_zone):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("test", name, "name")
            self.assertEqual(None, availability_zone, "availability_zone")
            return AGGREGATE
        self.stubs.Set(self.controller.api, "create_aggregate",
                       stub_create_aggregate)

        result = self.controller.create(self.req,
                                        {"aggregate": {"name": "test"}})
        self.assertEqual(AGGREGATE, result["aggregate"])

    def test_create_with_null_name(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          self.req, {"aggregate":
                                     {"name": "",
                                      "availability_zone": "nova1"}})

    def test_create_with_name_too_long(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          self.req, {"aggregate":
                                     {"name": "x" * 256,
                                      "availability_zone": "nova1"}})

    def test_show(self):
        def stub_get_aggregate(context, id):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("1", id, "id")
            return AGGREGATE
        self.stubs.Set(self.controller.api, 'get_aggregate',
                       stub_get_aggregate)

        aggregate = self.controller.show(self.req, "1")

        self.assertEqual(AGGREGATE, aggregate["aggregate"])

    def test_show_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.show,
                          self.user_req, "1")

    def test_show_with_invalid_id(self):
        def stub_get_aggregate(context, id):
            raise exception.AggregateNotFound(aggregate_id=2)

        self.stubs.Set(self.controller.api, 'get_aggregate',
                       stub_get_aggregate)

        self.assertRaises(exc.HTTPNotFound,
                          self.controller.show, self.req, "2")

    def test_update(self):
        body = {"aggregate": {"name": "new_name",
                              "availability_zone": "nova1"}}

        def stub_update_aggregate(context, aggregate, values):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("1", aggregate, "aggregate")
            self.assertEqual(body["aggregate"], values, "values")
            return AGGREGATE
        self.stubs.Set(self.controller.api, "update_aggregate",
                       stub_update_aggregate)

        result = self.controller.update(self.req, "1", body=body)

        self.assertEqual(AGGREGATE, result["aggregate"])

    def test_update_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.update,
                          self.user_req, "1", body={})

    def test_update_with_only_name(self):
        body = {"aggregate": {"name": "new_name"}}

        def stub_update_aggregate(context, aggregate, values):
            return AGGREGATE
        self.stubs.Set(self.controller.api, "update_aggregate",
                       stub_update_aggregate)

        result = self.controller.update(self.req, "1", body=body)

        self.assertEqual(AGGREGATE, result["aggregate"])

    def test_update_with_only_availability_zone(self):
        body = {"aggregate": {"availability_zone": "nova1"}}

        def stub_update_aggregate(context, aggregate, values):
            return AGGREGATE
        self.stubs.Set(self.controller.api, "update_aggregate",
                       stub_update_aggregate)
        result = self.controller.update(self.req, "1", body=body)
        self.assertEqual(AGGREGATE, result["aggregate"])

    def test_update_with_no_updates(self):
        test_metadata = {"aggregate": {}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
            self.req, "2", body=test_metadata)

    def test_update_with_wrong_updates(self):
        test_metadata = {"aggregate": {"status": "disable",
                                       "foo": "bar"}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          self.req, "2", body=test_metadata)

    def test_update_with_null_name(self):
        test_metadata = {"aggregate": {"name": ""}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          self.req, "2", body=test_metadata)

    def test_update_with_name_too_long(self):
        test_metadata = {"aggregate": {"name": "x" * 256}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          self.req, "2", body=test_metadata)

    def test_update_with_bad_aggregate(self):
        test_metadata = {"aggregate": {"name": "test_name"}}

        def stub_update_aggregate(context, aggregate, metadata):
            raise exception.AggregateNotFound(aggregate_id=2)
        self.stubs.Set(self.controller.api, "update_aggregate",
                       stub_update_aggregate)

        self.assertRaises(exc.HTTPNotFound, self.controller.update,
                self.req, "2", body=test_metadata)

    def test_update_with_invalid_request(self):
        test_metadata = {"aggregate": 1}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
            self.req, "2", body=test_metadata)

    def test_add_host(self):
        def stub_add_host_to_aggregate(context, aggregate, host):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("1", aggregate, "aggregate")
            self.assertEqual("host1", host, "host")
            return AGGREGATE
        self.stubs.Set(self.controller.api, "add_host_to_aggregate",
                       stub_add_host_to_aggregate)

        aggregate = self.controller._add_host(self.req, "1",
                                           body={"add_host": {"host":
                                                              "host1"}})

        self.assertEqual(aggregate["aggregate"], AGGREGATE)
        self.assertEqual(self.controller._add_host.wsgi_code, 202)

    def test_add_host_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller._add_host,
                          self.user_req, "1",
                          body={"add_host": {"host": "host1"}})

    def test_add_host_with_already_added_host(self):
        def stub_add_host_to_aggregate(context, aggregate, host):
            raise exception.AggregateHostExists(aggregate_id=aggregate,
                                                host=host)
        self.stubs.Set(self.controller.api, "add_host_to_aggregate",
                       stub_add_host_to_aggregate)

        self.assertRaises(exc.HTTPConflict, self.controller._add_host,
                          self.req, "1",
                          body={"add_host": {"host": "host1"}})

    def test_add_host_with_bad_aggregate(self):
        def stub_add_host_to_aggregate(context, aggregate, host):
            raise exception.AggregateNotFound(aggregate_id=aggregate)
        self.stubs.Set(self.controller.api, "add_host_to_aggregate",
                       stub_add_host_to_aggregate)

        self.assertRaises(exc.HTTPNotFound, self.controller._add_host,
                          self.req, "bogus_aggregate",
                          body={"add_host": {"host": "host1"}})

    def test_add_host_with_bad_host(self):
        def stub_add_host_to_aggregate(context, aggregate, host):
            raise exception.ComputeHostNotFound(host=host)
        self.stubs.Set(self.controller.api, "add_host_to_aggregate",
                       stub_add_host_to_aggregate)

        self.assertRaises(exc.HTTPNotFound, self.controller._add_host,
                          self.req, "1",
                          body={"add_host": {"host": "bogus_host"}})

    def test_add_host_with_missing_host(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller._add_host,
                self.req, "1", body={"add_host": {}})

    def test_add_host_with_invalid_request(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller._add_host,
                self.req, "1", body={"add_host": 1})

    def test_add_host_with_non_string(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller._add_host,
                self.req, "1", body={"add_host": {"host": 1}})

    def test_remove_host(self):
        def stub_remove_host_from_aggregate(context, aggregate, host):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("1", aggregate, "aggregate")
            self.assertEqual("host1", host, "host")
            stub_remove_host_from_aggregate.called = True
            return {}
        self.stubs.Set(self.controller.api,
                       "remove_host_from_aggregate",
                       stub_remove_host_from_aggregate)
        self.controller._remove_host(self.req, "1",
                               body={"remove_host": {"host": "host1"}})

        self.assertTrue(stub_remove_host_from_aggregate.called)
        self.assertEqual(self.controller._remove_host.wsgi_code, 202)

    def test_remove_host_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller._remove_host,
                          self.user_req, "1",
                          body={"remove_host": {"host": "host1"}})

    def test_remove_host_with_host_not_in_aggregate(self):
        def stub_remove_host_from_aggregate(context, aggregate, host):
            raise exception.AggregateHostNotFound(aggregate_id=aggregate,
                                                  host=host)
        self.stubs.Set(self.controller.api,
                       "remove_host_from_aggregate",
                       stub_remove_host_from_aggregate)

        self.assertRaises(exc.HTTPNotFound, self.controller._remove_host,
                          self.req, "1",
                          body={"remove_host": {"host": "host1"}})

    def test_remove_host_with_bad_host(self):
        def stub_remove_host_from_aggregate(context, aggregate, host):
            raise exception.ComputeHostNotFound(host=host)
        self.stubs.Set(self.controller.api,
                       "remove_host_from_aggregate",
                       stub_remove_host_from_aggregate)

        self.assertRaises(exc.HTTPNotFound, self.controller._remove_host,
                self.req, "1", body={"remove_host": {"host": "bogushost"}})

    def test_remove_host_with_invalid_request(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller._remove_host,
                self.req, "1", body={"remove_host": 1})

    def test_remove_host_with_missing_host(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller._remove_host,
                self.req, "1", body={"remove_host": {}})

    def test_remove_host_with_missing_host(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller._remove_host,
                self.req, "1", body={"remove_host": {"host": 1}})

    def test_set_metadata(self):
        body = {"set_metadata": {"metadata": {"foo": "bar"}}}

        def stub_update_aggregate(context, aggregate, values):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("1", aggregate, "aggregate")
            self.assertThat(body["set_metadata"]['metadata'],
                            matchers.DictMatches(values))
            return AGGREGATE
        self.stubs.Set(self.controller.api,
                       "update_aggregate_metadata",
                       stub_update_aggregate)

        result = self.controller._set_metadata(self.req, "1", body=body)

        self.assertEqual(AGGREGATE, result["aggregate"])

    def test_set_metadata_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller._set_metadata,
                          self.user_req, "1",
                          body={"set_metadata": {"metadata":
                                                    {"foo": "bar"}}})

    def test_set_metadata_with_bad_aggregate(self):
        body = {"set_metadata": {"metadata": {"foo": "bar"}}}

        def stub_update_aggregate(context, aggregate, metadata):
            raise exception.AggregateNotFound(aggregate_id=aggregate)
        self.stubs.Set(self.controller.api,
                       "update_aggregate_metadata",
                       stub_update_aggregate)

        self.assertRaises(exc.HTTPNotFound, self.controller._set_metadata,
                self.req, "bad_aggregate", body=body)

    def test_set_metadata_with_missing_metadata(self):
        body = {"set_metadata": {}}
        self.assertRaises(exc.HTTPBadRequest, self.controller._set_metadata,
                          self.req, "1", body=body)

    def test_set_metadata_with_invalid_request(self):
        body = {"set_metadata": 1}
        self.assertRaises(exc.HTTPBadRequest, self.controller._set_metadata,
                          self.req, "1", body=body)

    def test_set_metadata_without_dict(self):
        body = {"set_metadata": {'metadata': 1}}
        self.assertRaises(exc.HTTPBadRequest, self.controller._set_metadata,
                          self.req, "1", body=body)

    def test_delete_aggregate(self):
        def stub_delete_aggregate(context, aggregate):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("1", aggregate, "aggregate")
            stub_delete_aggregate.called = True
        self.stubs.Set(self.controller.api, "delete_aggregate",
                       stub_delete_aggregate)

        self.controller.delete(self.req, "1")
        self.assertTrue(stub_delete_aggregate.called)

    def test_delete_aggregate_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.delete,
                          self.user_req, "1")

    def test_delete_aggregate_with_bad_aggregate(self):
        def stub_delete_aggregate(context, aggregate):
            raise exception.AggregateNotFound(aggregate_id=aggregate)
        self.stubs.Set(self.controller.api, "delete_aggregate",
                       stub_delete_aggregate)

        self.assertRaises(exc.HTTPNotFound, self.controller.delete,
                self.req, "bogus_aggregate")
