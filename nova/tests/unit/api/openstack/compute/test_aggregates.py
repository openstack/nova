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

import mock
import uuid
from webob import exc

from nova.api.openstack.compute import aggregates as aggregates_v21
from nova.api.openstack.compute.legacy_v2.contrib import aggregates \
        as aggregates_v2
from nova.compute import api as compute_api
from nova import context
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import matchers
from nova.tests import uuidsentinel


def _make_agg_obj(agg_dict):
    return objects.Aggregate(**agg_dict)


def _make_agg_list(agg_list):
    return objects.AggregateList(objects=[_make_agg_obj(a) for a in agg_list])


def _transform_aggregate_az(agg_dict):
    # the Aggregate object looks for availability_zone within metadata,
    # so if availability_zone is in the top-level dict, move it down into
    # metadata. We also have to delete the key from the top-level dict because
    # availability_zone is a read-only property on the Aggregate object
    md = agg_dict.get('metadata', {})
    if 'availability_zone' in agg_dict:
        md['availability_zone'] = agg_dict['availability_zone']
        del agg_dict['availability_zone']
        agg_dict['metadata'] = md
    return agg_dict


def _transform_aggregate_list_azs(agg_list):
    for agg_dict in agg_list:
        yield _transform_aggregate_az(agg_dict)


AGGREGATE_LIST = [
        {"name": "aggregate1", "id": "1",
            "metadata": {"availability_zone": "nova1"}},
        {"name": "aggregate2", "id": "2",
            "metadata": {"availability_zone": "nova1"}},
        {"name": "aggregate3", "id": "3",
            "metadata": {"availability_zone": "nova2"}},
        {"name": "aggregate1", "id": "4",
            "metadata": {"availability_zone": "nova1"}}]
AGGREGATE_LIST = _make_agg_list(AGGREGATE_LIST)

AGGREGATE = {"name": "aggregate1",
                  "id": "1",
                  "metadata": {"foo": "bar",
                               "availability_zone": "nova1"},
                  "hosts": ["host1", "host2"]}
AGGREGATE = _make_agg_obj(AGGREGATE)

FORMATTED_AGGREGATE = {"name": "aggregate1",
                  "id": "1",
                  "metadata": {"availability_zone": "nova1"}}
FORMATTED_AGGREGATE = _make_agg_obj(FORMATTED_AGGREGATE)


class FakeRequest(object):
    environ = {"nova.context": context.get_admin_context()}


class AggregateTestCaseV21(test.NoDBTestCase):
    """Test Case for aggregates admin api."""

    add_host = 'self.controller._add_host'
    remove_host = 'self.controller._remove_host'
    set_metadata = 'self.controller._set_metadata'
    bad_request = exception.ValidationError

    def _set_up(self):
        self.controller = aggregates_v21.AggregateController()
        self.req = fakes.HTTPRequest.blank('/v2/os-aggregates',
                                           use_admin_context=True)
        self.user_req = fakes.HTTPRequest.blank('/v2/os-aggregates')
        self.context = self.req.environ['nova.context']

    def setUp(self):
        super(AggregateTestCaseV21, self).setUp()
        self._set_up()

    def test_index(self):
        def stub_list_aggregates(context):
            if context is None:
                raise Exception()
            return AGGREGATE_LIST
        self.stubs.Set(self.controller.api, 'get_aggregate_list',
                       stub_list_aggregates)

        result = self.controller.index(self.req)
        result = _transform_aggregate_list_azs(result['aggregates'])
        self._assert_agg_data(AGGREGATE_LIST, _make_agg_list(result))

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

        result = self.controller.create(self.req, body={"aggregate":
                                          {"name": "test",
                                           "availability_zone": "nova1"}})
        result = _transform_aggregate_az(result['aggregate'])
        self._assert_agg_data(FORMATTED_AGGREGATE, _make_agg_obj(result))

    def test_create_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.create, self.user_req,
                          body={"aggregate":
                              {"name": "test",
                               "availability_zone": "nova1"}})

    def test_create_with_duplicate_aggregate_name(self):
        def stub_create_aggregate(context, name, availability_zone):
            raise exception.AggregateNameExists(aggregate_name=name)
        self.stubs.Set(self.controller.api, "create_aggregate",
                       stub_create_aggregate)

        self.assertRaises(exc.HTTPConflict, self.controller.create,
                          self.req, body={"aggregate":
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
                          self.req, body={"aggregate":
                                     {"name": "test",
                                      "availability_zone": "nova_bad"}})

    def test_create_with_no_aggregate(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"foo":
                                     {"name": "test",
                                      "availability_zone": "nova1"}})

    def test_create_with_no_name(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"aggregate":
                                     {"foo": "test",
                                      "availability_zone": "nova1"}})

    def test_create_name_with_leading_trailing_spaces(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"aggregate":
                                          {"name": "  test  ",
                                           "availability_zone": "nova1"}})

    def test_create_name_with_leading_trailing_spaces_compat_mode(self):

        def fake_mock_aggs(context, name, az):
            self.assertEqual('test', name)
            return AGGREGATE

        with mock.patch.object(compute_api.AggregateAPI,
                               'create_aggregate') as mock_aggs:
            mock_aggs.side_effect = fake_mock_aggs
            self.req.set_legacy_v2()
            self.controller.create(self.req,
                                   body={"aggregate":
                                         {"name": "  test  ",
                                          "availability_zone": "nova1"}})

    def test_create_with_no_availability_zone(self):
        def stub_create_aggregate(context, name, availability_zone):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("test", name, "name")
            self.assertIsNone(availability_zone, "availability_zone")
            return AGGREGATE
        self.stubs.Set(self.controller.api, "create_aggregate",
                       stub_create_aggregate)

        result = self.controller.create(self.req,
                                        body={"aggregate": {"name": "test"}})

        result = _transform_aggregate_az(result['aggregate'])
        self._assert_agg_data(FORMATTED_AGGREGATE, _make_agg_obj(result))

    def test_create_with_null_name(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"aggregate":
                                     {"name": "",
                                      "availability_zone": "nova1"}})

    def test_create_with_name_too_long(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"aggregate":
                                     {"name": "x" * 256,
                                      "availability_zone": "nova1"}})

    def test_create_with_availability_zone_too_long(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"aggregate":
                                     {"name": "test",
                                      "availability_zone": "x" * 256}})

    def test_create_availability_zone_with_leading_trailing_spaces(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"aggregate":
                                          {"name": "test",
                                           "availability_zone": "  nova1  "}})

    def test_create_availabiltiy_zone_with_leading_trailing_spaces_compat_mode(
            self):

        def fake_mock_aggs(context, name, az):
            self.assertEqual('nova1', az)
            return AGGREGATE

        with mock.patch.object(compute_api.AggregateAPI,
                               'create_aggregate') as mock_aggs:
            mock_aggs.side_effect = fake_mock_aggs
            self.req.set_legacy_v2()
            self.controller.create(self.req,
                                   body={"aggregate":
                                         {"name": "test",
                                          "availability_zone": "  nova1  "}})

    def test_create_with_empty_availability_zone(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"aggregate":
                                     {"name": "test",
                                      "availability_zone": ""}})

    @mock.patch('nova.compute.api.AggregateAPI.create_aggregate')
    def test_create_with_none_availability_zone(self, mock_create_agg):
        mock_create_agg.return_value = objects.Aggregate(self.context,
                                                         name='test',
                                                         uuid=uuid.uuid4(),
                                                         hosts=[],
                                                         metadata={})
        body = {"aggregate": {"name": "test",
                              "availability_zone": None}}
        result = self.controller.create(self.req, body=body)
        mock_create_agg.assert_called_once_with(self.context, 'test', None)
        self.assertEqual(result['aggregate']['name'], 'test')

    def test_create_with_extra_invalid_arg(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"name": "test",
                                          "availability_zone": "nova1",
                                          "foo": 'bar'})

    def test_show(self):
        def stub_get_aggregate(context, id):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("1", id, "id")
            return AGGREGATE
        self.stubs.Set(self.controller.api, 'get_aggregate',
                       stub_get_aggregate)

        aggregate = self.controller.show(self.req, "1")
        aggregate = _transform_aggregate_az(aggregate['aggregate'])
        self._assert_agg_data(AGGREGATE, _make_agg_obj(aggregate))

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

        result = _transform_aggregate_az(result['aggregate'])
        self._assert_agg_data(AGGREGATE, _make_agg_obj(result))

    def test_update_no_admin(self):
        body = {"aggregate": {"availability_zone": "nova"}}
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.update,
                          self.user_req, "1", body=body)

    def test_update_with_only_name(self):
        body = {"aggregate": {"name": "new_name"}}

        def stub_update_aggregate(context, aggregate, values):
            return AGGREGATE
        self.stubs.Set(self.controller.api, "update_aggregate",
                       stub_update_aggregate)

        result = self.controller.update(self.req, "1", body=body)

        result = _transform_aggregate_az(result['aggregate'])
        self._assert_agg_data(AGGREGATE, _make_agg_obj(result))

    def test_update_with_only_availability_zone(self):
        body = {"aggregate": {"availability_zone": "nova1"}}

        def stub_update_aggregate(context, aggregate, values):
            return AGGREGATE
        self.stubs.Set(self.controller.api, "update_aggregate",
                       stub_update_aggregate)
        result = self.controller.update(self.req, "1", body=body)

        result = _transform_aggregate_az(result['aggregate'])
        self._assert_agg_data(AGGREGATE, _make_agg_obj(result))

    def test_update_with_no_updates(self):
        test_metadata = {"aggregate": {}}
        self.assertRaises(self.bad_request, self.controller.update,
                          self.req, "2", body=test_metadata)

    def test_update_with_no_update_key(self):
        test_metadata = {"asdf": {}}
        self.assertRaises(self.bad_request, self.controller.update,
                          self.req, "2", body=test_metadata)

    def test_update_with_wrong_updates(self):
        test_metadata = {"aggregate": {"status": "disable",
                                     "foo": "bar"}}
        self.assertRaises(self.bad_request, self.controller.update,
                          self.req, "2", body=test_metadata)

    def test_update_with_null_name(self):
        test_metadata = {"aggregate": {"name": ""}}
        self.assertRaises(self.bad_request, self.controller.update,
                          self.req, "2", body=test_metadata)

    def test_update_with_name_too_long(self):
        test_metadata = {"aggregate": {"name": "x" * 256}}
        self.assertRaises(self.bad_request, self.controller.update,
                          self.req, "2", body=test_metadata)

    def test_update_with_availability_zone_too_long(self):
        test_metadata = {"aggregate": {"availability_zone": "x" * 256}}
        self.assertRaises(self.bad_request, self.controller.update,
                          self.req, "2", body=test_metadata)

    def test_update_with_empty_availability_zone(self):
        test_metadata = {"aggregate": {"availability_zone": ""}}
        self.assertRaises(self.bad_request, self.controller.update,
                          self.req, "2", body=test_metadata)

    @mock.patch('nova.compute.api.AggregateAPI.update_aggregate')
    def test_update_with_none_availability_zone(self, mock_update_agg):
        agg_id = uuid.uuid4()
        mock_update_agg.return_value = objects.Aggregate(self.context,
                                                         name='test',
                                                         uuid=agg_id,
                                                         hosts=[],
                                                         metadata={})
        body = {"aggregate": {"name": "test",
                              "availability_zone": None}}
        result = self.controller.update(self.req, agg_id, body=body)
        mock_update_agg.assert_called_once_with(self.context, agg_id,
                                                body['aggregate'])
        self.assertEqual(result['aggregate']['name'], 'test')

    def test_update_with_bad_aggregate(self):
        test_metadata = {"aggregate": {"name": "test_name"}}

        def stub_update_aggregate(context, aggregate, metadata):
            raise exception.AggregateNotFound(aggregate_id=2)
        self.stubs.Set(self.controller.api, "update_aggregate",
                       stub_update_aggregate)

        self.assertRaises(exc.HTTPNotFound, self.controller.update,
                self.req, "2", body=test_metadata)

    def test_update_with_duplicated_name(self):
        test_metadata = {"aggregate": {"name": "test_name"}}

        def stub_update_aggregate(context, aggregate, metadata):
            raise exception.AggregateNameExists(aggregate_name="test_name")

        self.stubs.Set(self.controller.api, "update_aggregate",
                       stub_update_aggregate)
        self.assertRaises(exc.HTTPConflict, self.controller.update,
                self.req, "2", body=test_metadata)

    def test_invalid_action(self):
        body = {"append_host": {"host": "host1"}}
        self.assertRaises(self.bad_request,
                          eval(self.add_host), self.req, "1", body=body)

    def test_update_with_invalid_action(self):
        with mock.patch.object(self.controller.api, "update_aggregate",
            side_effect=exception.InvalidAggregateAction(
                action='invalid', aggregate_id='agg1', reason= "not empty")):
            body = {"aggregate": {"availability_zone": "nova"}}
            self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                              self.req, "1", body=body)

    def test_add_host(self):
        def stub_add_host_to_aggregate(context, aggregate, host):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("1", aggregate, "aggregate")
            self.assertEqual("host1", host, "host")
            return AGGREGATE
        self.stubs.Set(self.controller.api, "add_host_to_aggregate",
                       stub_add_host_to_aggregate)

        aggregate = eval(self.add_host)(self.req, "1",
                                        body={"add_host": {"host":
                                                           "host1"}})

        aggregate = _transform_aggregate_az(aggregate['aggregate'])
        self._assert_agg_data(AGGREGATE, _make_agg_obj(aggregate))

    def test_add_host_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          eval(self.add_host),
                          self.user_req, "1",
                          body={"add_host": {"host": "host1"}})

    def test_add_host_with_already_added_host(self):
        def stub_add_host_to_aggregate(context, aggregate, host):
            raise exception.AggregateHostExists(aggregate_id=aggregate,
                                                host=host)
        self.stubs.Set(self.controller.api, "add_host_to_aggregate",
                       stub_add_host_to_aggregate)

        self.assertRaises(exc.HTTPConflict, eval(self.add_host),
                          self.req, "1",
                          body={"add_host": {"host": "host1"}})

    def test_add_host_with_bad_aggregate(self):
        def stub_add_host_to_aggregate(context, aggregate, host):
            raise exception.AggregateNotFound(aggregate_id=aggregate)
        self.stubs.Set(self.controller.api, "add_host_to_aggregate",
                       stub_add_host_to_aggregate)

        self.assertRaises(exc.HTTPNotFound, eval(self.add_host),
                          self.req, "bogus_aggregate",
                          body={"add_host": {"host": "host1"}})

    def test_add_host_with_bad_host(self):
        def stub_add_host_to_aggregate(context, aggregate, host):
            raise exception.ComputeHostNotFound(host=host)
        self.stubs.Set(self.controller.api, "add_host_to_aggregate",
                       stub_add_host_to_aggregate)

        self.assertRaises(exc.HTTPNotFound, eval(self.add_host),
                          self.req, "1",
                          body={"add_host": {"host": "bogus_host"}})

    def test_add_host_with_missing_host(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": {"asdf": "asdf"}})

    def test_add_host_with_invalid_format_host(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": {"host": "a" * 300}})

    def test_add_host_with_multiple_hosts(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": {"host": ["host1", "host2"]}})

    def test_add_host_raises_key_error(self):
        def stub_add_host_to_aggregate(context, aggregate, host):
            raise KeyError
        self.stubs.Set(self.controller.api, "add_host_to_aggregate",
                       stub_add_host_to_aggregate)
        self.assertRaises(exc.HTTPInternalServerError,
                          eval(self.add_host), self.req, "1",
                          body={"add_host": {"host": "host1"}})

    def test_add_host_with_invalid_request(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": "1"})

    def test_add_host_with_non_string(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": {"host": 1}})

    def test_remove_host(self):
        def stub_remove_host_from_aggregate(context, aggregate, host):
            self.assertEqual(context, self.context, "context")
            self.assertEqual("1", aggregate, "aggregate")
            self.assertEqual("host1", host, "host")
            stub_remove_host_from_aggregate.called = True
            # at minimum, metadata is always set to {} in the api
            return _make_agg_obj({'metadata': {}})
        self.stubs.Set(self.controller.api,
                       "remove_host_from_aggregate",
                       stub_remove_host_from_aggregate)
        eval(self.remove_host)(self.req, "1",
                                  body={"remove_host": {"host": "host1"}})

        self.assertTrue(stub_remove_host_from_aggregate.called)

    def test_remove_host_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          eval(self.remove_host),
                          self.user_req, "1",
                          body={"remove_host": {"host": "host1"}})

    def test_remove_host_with_bad_aggregate(self):
        def stub_remove_host_from_aggregate(context, aggregate, host):
            raise exception.AggregateNotFound(aggregate_id=aggregate)
        self.stubs.Set(self.controller.api,
                       "remove_host_from_aggregate",
                       stub_remove_host_from_aggregate)

        self.assertRaises(exc.HTTPNotFound, eval(self.remove_host),
                          self.req, "bogus_aggregate",
                          body={"remove_host": {"host": "host1"}})

    def test_remove_host_with_host_not_in_aggregate(self):
        def stub_remove_host_from_aggregate(context, aggregate, host):
            raise exception.AggregateHostNotFound(aggregate_id=aggregate,
                                                  host=host)
        self.stubs.Set(self.controller.api,
                       "remove_host_from_aggregate",
                       stub_remove_host_from_aggregate)

        self.assertRaises(exc.HTTPNotFound, eval(self.remove_host),
                          self.req, "1",
                          body={"remove_host": {"host": "host1"}})

    def test_remove_host_with_bad_host(self):
        def stub_remove_host_from_aggregate(context, aggregate, host):
            raise exception.ComputeHostNotFound(host=host)
        self.stubs.Set(self.controller.api,
                       "remove_host_from_aggregate",
                       stub_remove_host_from_aggregate)

        self.assertRaises(exc.HTTPNotFound, eval(self.remove_host),
                self.req, "1", body={"remove_host": {"host": "bogushost"}})

    def test_remove_host_with_missing_host(self):
        self.assertRaises(self.bad_request, eval(self.remove_host),
                self.req, "1", body={"asdf": "asdf"})

    def test_remove_host_with_multiple_hosts(self):
        self.assertRaises(self.bad_request, eval(self.remove_host),
                self.req, "1", body={"remove_host": {"host":
                                                     ["host1", "host2"]}})

    def test_remove_host_with_extra_param(self):
        self.assertRaises(self.bad_request, eval(self.remove_host),
                self.req, "1", body={"remove_host": {"asdf": "asdf",
                                                     "host": "asdf"}})

    def test_remove_host_with_invalid_request(self):
        self.assertRaises(self.bad_request,
                          eval(self.remove_host),
                self.req, "1", body={"remove_host": "1"})

    def test_remove_host_with_missing_host_empty(self):
        self.assertRaises(self.bad_request,
                          eval(self.remove_host),
                self.req, "1", body={"remove_host": {}})

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

        result = eval(self.set_metadata)(self.req, "1", body=body)

        result = _transform_aggregate_az(result['aggregate'])
        self._assert_agg_data(AGGREGATE, _make_agg_obj(result))

    def test_set_metadata_delete(self):
        body = {"set_metadata": {"metadata": {"foo": None}}}

        with mock.patch.object(self.controller.api,
                               'update_aggregate_metadata') as mocked:
            mocked.return_value = AGGREGATE
            result = eval(self.set_metadata)(self.req, "1", body=body)

        result = _transform_aggregate_az(result['aggregate'])
        self._assert_agg_data(AGGREGATE, _make_agg_obj(result))
        mocked.assert_called_once_with(self.context, "1",
                                       body["set_metadata"]["metadata"])

    def test_set_metadata_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          eval(self.set_metadata),
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
        self.assertRaises(exc.HTTPNotFound, eval(self.set_metadata),
                self.req, "bad_aggregate", body=body)

    def test_set_metadata_with_missing_metadata(self):
        body = {"asdf": {"foo": "bar"}}
        self.assertRaises(self.bad_request, eval(self.set_metadata),
                          self.req, "1", body=body)

    def test_set_metadata_with_extra_params(self):
        body = {"metadata": {"foo": "bar"}, "asdf": {"foo": "bar"}}
        self.assertRaises(self.bad_request, eval(self.set_metadata),
                          self.req, "1", body=body)

    def test_set_metadata_without_dict(self):
        body = {"set_metadata": {'metadata': 1}}
        self.assertRaises(self.bad_request, eval(self.set_metadata),
                          self.req, "1", body=body)

    def test_set_metadata_with_empty_key(self):
        body = {"set_metadata": {"metadata": {"": "value"}}}
        self.assertRaises(self.bad_request, eval(self.set_metadata),
                          self.req, "1", body=body)

    def test_set_metadata_with_key_too_long(self):
        body = {"set_metadata": {"metadata": {"x" * 256: "value"}}}
        self.assertRaises(self.bad_request, eval(self.set_metadata),
                          self.req, "1", body=body)

    def test_set_metadata_with_value_too_long(self):
        body = {"set_metadata": {"metadata": {"key": "x" * 256}}}
        self.assertRaises(self.bad_request, eval(self.set_metadata),
                          self.req, "1", body=body)

    def test_set_metadata_with_string(self):
        body = {"set_metadata": {"metadata": "test"}}
        self.assertRaises(self.bad_request, eval(self.set_metadata),
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

    def test_delete_aggregate_with_host(self):
        with mock.patch.object(self.controller.api, "delete_aggregate",
                               side_effect=exception.InvalidAggregateAction(
                               action="delete", aggregate_id="agg1",
                               reason="not empty")):
            self.assertRaises(exc.HTTPBadRequest,
                              self.controller.delete,
                              self.req, "agg1")

    def test_marshall_aggregate(self):
        # _marshall_aggregate() just basically turns the aggregate returned
        # from the AggregateAPI into a dict, so this tests that transform.
        # We would expect the dictionary that comes out is the same one
        # that we pump into the aggregate object in the first place
        agg = {'name': 'aggregate1',
               'id': 1, 'uuid': uuidsentinel.aggregate,
               'metadata': {'foo': 'bar', 'availability_zone': 'nova'},
               'hosts': ['host1', 'host2']}
        agg_obj = _make_agg_obj(agg)
        marshalled_agg = self.controller._marshall_aggregate(agg_obj)

        # _marshall_aggregate() puts all fields and obj_extra_fields in the
        # top-level dict, so we need to put availability_zone at the top also
        agg['availability_zone'] = 'nova'
        del agg['uuid']
        self.assertEqual(agg, marshalled_agg['aggregate'])

    def _assert_agg_data(self, expected, actual):
        self.assertTrue(obj_base.obj_equal_prims(expected, actual),
                        "The aggregate objects were not equal")


class AggregateTestCaseV2(AggregateTestCaseV21):
    add_host = 'self.controller.action'
    remove_host = 'self.controller.action'
    set_metadata = 'self.controller.action'
    bad_request = exc.HTTPBadRequest

    def _set_up(self):
        self.controller = aggregates_v2.AggregateController()
        self.req = FakeRequest()
        self.user_req = fakes.HTTPRequest.blank('/v2/os-aggregates')
        self.context = self.req.environ['nova.context']

    def test_add_host_raises_key_error(self):
        def stub_add_host_to_aggregate(context, aggregate, host):
            raise KeyError
        self.stubs.Set(self.controller.api, "add_host_to_aggregate",
                       stub_add_host_to_aggregate)
        # NOTE(mtreinish) The check for a KeyError here is to ensure that
        # if add_host_to_aggregate() raises a KeyError it propagates. At
        # one point the api code would mask the error as a HTTPBadRequest.
        # This test is to ensure that this doesn't occur again.
        self.assertRaises(KeyError, eval(self.add_host), self.req, "1",
                          body={"add_host": {"host": "host1"}})

    def test_add_host_to_aggregate_with_non_admin(self):
        rule_name = "compute_extension:aggregates"
        self.policy.set_rules({rule_name: ""})
        self.assertRaises(exception.AdminRequired, self.controller._add_host,
                          self.user_req, '1', {'host': 'fake_host'})

    def test_remove_host_from_aggregate_with_non_admin(self):
        rule_name = "compute_extension:aggregates"
        self.policy.set_rules({rule_name: ""})
        self.assertRaises(exception.AdminRequired,
                          self.controller._remove_host, self.user_req,
                          '1', {'host': 'fake_host'})

    def test_create_name_with_leading_trailing_spaces(self):

        def fake_mock_aggs(context, name, az):
            # NOTE(alex_xu): legacy v2 api didn't strip the spaces.
            self.assertEqual('  test  ', name)
            return AGGREGATE

        with mock.patch.object(compute_api.AggregateAPI,
                               'create_aggregate') as mock_aggs:
            mock_aggs.side_effect = fake_mock_aggs
            self.controller.create(self.req,
                                   body={"aggregate":
                                         {"name": "  test  ",
                                          "availability_zone": "nova1"}})

    def test_create_name_with_leading_trailing_spaces_compat_mode(self):
        pass

    def test_create_availability_zone_with_leading_trailing_spaces(self):

        def fake_mock_aggs(context, name, az):
            # NOTE(alex_xu): legacy v2 api didn't strip the spaces.
            self.assertEqual('  nova1  ', az)
            return AGGREGATE

        with mock.patch.object(compute_api.AggregateAPI,
                               'create_aggregate') as mock_aggs:
            mock_aggs.side_effect = fake_mock_aggs
            self.controller.create(self.req,
                                   body={"aggregate":
                                         {"name": "  test  ",
                                          "availability_zone": "  nova1  "}})

    def test_create_availabiltiy_zone_with_leading_trailing_spaces_compat_mode(
            self):
        pass
