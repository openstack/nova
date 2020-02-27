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
from oslo_utils.fixture import uuidsentinel
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import aggregates as aggregates_v21
from nova.compute import api as compute_api
from nova import context
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova import test
from nova.tests.unit.api.openstack import fakes


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
        def _list_aggregates(context):
            if context is None:
                raise Exception()
            return AGGREGATE_LIST

        with mock.patch.object(self.controller.api, 'get_aggregate_list',
                               side_effect=_list_aggregates) as mock_list:
            result = self.controller.index(self.req)
            result = _transform_aggregate_list_azs(result['aggregates'])
            self._assert_agg_data(AGGREGATE_LIST, _make_agg_list(result))
            self.assertTrue(mock_list.called)

    def test_index_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.index,
                          self.user_req)

    def test_create(self):
        with mock.patch.object(self.controller.api, 'create_aggregate',
                               return_value=AGGREGATE) as mock_create:
            result = self.controller.create(self.req,
                body={"aggregate": {"name": "test",
                                    "availability_zone": "nova1"}})
            result = _transform_aggregate_az(result['aggregate'])
            self._assert_agg_data(FORMATTED_AGGREGATE, _make_agg_obj(result))
            mock_create.assert_called_once_with(self.context, 'test', 'nova1')

    def test_create_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.create, self.user_req,
                          body={"aggregate": {"name": "test",
                                              "availability_zone": "nova1"}})

    def test_create_with_duplicate_aggregate_name(self):
        side_effect = exception.AggregateNameExists(aggregate_name="test")
        with mock.patch.object(self.controller.api, 'create_aggregate',
                               side_effect=side_effect) as mock_create:
            self.assertRaises(exc.HTTPConflict, self.controller.create,
                self.req, body={"aggregate": {"name": "test",
                                              "availability_zone": "nova1"}})
            mock_create.assert_called_once_with(self.context, 'test', 'nova1')

    @mock.patch.object(compute_api.AggregateAPI, 'create_aggregate')
    def test_create_with_unmigrated_aggregates(self, mock_create_aggregate):
        mock_create_aggregate.side_effect = \
                exception.ObjectActionError(action='create',
                    reason='main database still contains aggregates')

        self.assertRaises(exc.HTTPConflict, self.controller.create,
                          self.req, body={"aggregate":
                                     {"name": "test",
                                      "availability_zone": "nova1"}})

    def test_create_with_incorrect_availability_zone(self):
        side_effect = exception.InvalidAggregateAction(
                        action='create_aggregate',
                        aggregate_id="'N/A'",
                        reason='invalid zone')
        with mock.patch.object(self.controller.api, 'create_aggregate',
                               side_effect=side_effect) as mock_create:
            self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                self.req,
                body={"aggregate": {"name": "test",
                                    "availability_zone": "nova_bad"}})
            mock_create.assert_called_once_with(self.context, 'test',
                                                'nova_bad')

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
        with mock.patch.object(self.controller.api, 'create_aggregate',
                               return_value=AGGREGATE) as mock_create:
            result = self.controller.create(self.req,
                body={"aggregate": {"name": "test"}})

            result = _transform_aggregate_az(result['aggregate'])
            self._assert_agg_data(FORMATTED_AGGREGATE, _make_agg_obj(result))
            mock_create.assert_called_once_with(self.context, 'test', None)

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

    def test_create_with_availability_zone_invalid(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"aggregate":
                                     {"name": "test",
                                      "availability_zone": "bad:az"}})

    def test_create_availability_zone_with_leading_trailing_spaces(self):
        self.assertRaises(self.bad_request, self.controller.create,
                          self.req, body={"aggregate":
                                          {"name": "test",
                                           "availability_zone": "  nova1  "}})

    def test_create_availability_zone_with_leading_trailing_spaces_compat_mode(
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
        mock_create_agg.return_value = objects.Aggregate(
            self.context,
            name='test',
            uuid=uuidsentinel.aggregate,
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
        with mock.patch.object(self.controller.api, 'get_aggregate',
                               return_value=AGGREGATE) as mock_get:
            aggregate = self.controller.show(self.req, "1")
            aggregate = _transform_aggregate_az(aggregate['aggregate'])
            self._assert_agg_data(AGGREGATE, _make_agg_obj(aggregate))
            mock_get.assert_called_once_with(self.context, '1')

    def test_show_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.show,
                          self.user_req, "1")

    def test_show_with_bad_aggregate(self):
        side_effect = exception.AggregateNotFound(aggregate_id='2')
        with mock.patch.object(self.controller.api, 'get_aggregate',
                               side_effect=side_effect) as mock_get:
            self.assertRaises(exc.HTTPNotFound, self.controller.show,
                              self.req, "2")
            mock_get.assert_called_once_with(self.context, '2')

    def test_show_with_invalid_id(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller.show,
                          self.req, 'foo')

    def test_update(self):
        body = {"aggregate": {"name": "new_name",
                              "availability_zone": "nova1"}}
        with mock.patch.object(self.controller.api, 'update_aggregate',
                               return_value=AGGREGATE) as mock_update:
            result = self.controller.update(self.req, "1", body=body)

            result = _transform_aggregate_az(result['aggregate'])
            self._assert_agg_data(AGGREGATE, _make_agg_obj(result))
            mock_update.assert_called_once_with(self.context, '1',
                                                body["aggregate"])

    def test_update_no_admin(self):
        body = {"aggregate": {"availability_zone": "nova"}}
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.update,
                          self.user_req, "1", body=body)

    def test_update_with_only_name(self):
        body = {"aggregate": {"name": "new_name"}}
        with mock.patch.object(self.controller.api, 'update_aggregate',
                               return_value=AGGREGATE) as mock_update:
            result = self.controller.update(self.req, "1", body=body)

            result = _transform_aggregate_az(result['aggregate'])
            self._assert_agg_data(AGGREGATE, _make_agg_obj(result))
            mock_update.assert_called_once_with(self.context, '1',
                                                body["aggregate"])

    def test_update_with_only_availability_zone(self):
        body = {"aggregate": {"availability_zone": "nova1"}}
        with mock.patch.object(self.controller.api, 'update_aggregate',
                               return_value=AGGREGATE) as mock_update:
            result = self.controller.update(self.req, "1", body=body)

            result = _transform_aggregate_az(result['aggregate'])
            self._assert_agg_data(AGGREGATE, _make_agg_obj(result))
            mock_update.assert_called_once_with(self.context, '1',
                                                body["aggregate"])

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

    def test_update_with_availability_zone_invalid(self):
        test_metadata = {"aggregate": {"availability_zone": "bad:az"}}
        self.assertRaises(self.bad_request, self.controller.update,
                          self.req, "2", body=test_metadata)

    def test_update_with_empty_availability_zone(self):
        test_metadata = {"aggregate": {"availability_zone": ""}}
        self.assertRaises(self.bad_request, self.controller.update,
                          self.req, "2", body=test_metadata)

    @mock.patch('nova.compute.api.AggregateAPI.update_aggregate')
    def test_update_with_none_availability_zone(self, mock_update_agg):
        agg_id = 173
        mock_update_agg.return_value = objects.Aggregate(self.context,
                                                         name='test',
                                                         uuid=uuidsentinel.agg,
                                                         id=agg_id,
                                                         hosts=[],
                                                         metadata={})
        body = {"aggregate": {"name": "test",
                              "availability_zone": None}}
        result = self.controller.update(self.req, agg_id, body=body)
        mock_update_agg.assert_called_once_with(self.context, agg_id,
                                                body['aggregate'])
        self.assertEqual(result['aggregate']['name'], 'test')

    def test_update_with_bad_aggregate(self):
        body = {"aggregate": {"name": "test_name"}}
        side_effect = exception.AggregateNotFound(aggregate_id=2)

        with mock.patch.object(self.controller.api, 'update_aggregate',
                               side_effect=side_effect) as mock_update:
            self.assertRaises(exc.HTTPNotFound, self.controller.update,
                self.req, "2", body=body)
            mock_update.assert_called_once_with(self.context, '2',
                                                body["aggregate"])

    def test_update_with_invalid_id(self):
        body = {"aggregate": {"name": "test_name"}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body=body)

    def test_update_with_duplicated_name(self):
        body = {"aggregate": {"name": "test_name"}}
        side_effect = exception.AggregateNameExists(aggregate_name="test_name")

        with mock.patch.object(self.controller.api, 'update_aggregate',
                               side_effect=side_effect) as mock_update:
            self.assertRaises(exc.HTTPConflict, self.controller.update,
                self.req, "2", body=body)
            mock_update.assert_called_once_with(self.context, '2',
                                                body["aggregate"])

    def test_invalid_action(self):
        body = {"append_host": {"host": "host1"}}
        self.assertRaises(self.bad_request,
                          eval(self.add_host), self.req, "1", body=body)

    def test_update_with_invalid_action(self):
        with mock.patch.object(self.controller.api, "update_aggregate",
            side_effect=exception.InvalidAggregateAction(
                action='invalid', aggregate_id='1', reason= "not empty")):
            body = {"aggregate": {"availability_zone": "nova"}}
            self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                              self.req, "1", body=body)

    def test_add_host(self):
        with mock.patch.object(self.controller.api, 'add_host_to_aggregate',
                               return_value=AGGREGATE) as mock_add:
            aggregate = eval(self.add_host)(self.req, "1",
                                            body={"add_host": {"host":
                                                               "host1"}})

            aggregate = _transform_aggregate_az(aggregate['aggregate'])
            self._assert_agg_data(AGGREGATE, _make_agg_obj(aggregate))
            mock_add.assert_called_once_with(self.context, "1", "host1")

    def test_add_host_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          eval(self.add_host),
                          self.user_req, "1",
                          body={"add_host": {"host": "host1"}})

    def test_add_host_with_already_added_host(self):
        side_effect = exception.AggregateHostExists(aggregate_id="1",
                                                    host="host1")
        with mock.patch.object(self.controller.api, 'add_host_to_aggregate',
                               side_effect=side_effect) as mock_add:
            self.assertRaises(exc.HTTPConflict, eval(self.add_host),
                              self.req, "1",
                              body={"add_host": {"host": "host1"}})
            mock_add.assert_called_once_with(self.context, "1", "host1")

    def test_add_host_with_bad_aggregate(self):
        side_effect = exception.AggregateNotFound(
            aggregate_id="2")
        with mock.patch.object(self.controller.api, 'add_host_to_aggregate',
                               side_effect=side_effect) as mock_add:
            self.assertRaises(exc.HTTPNotFound, eval(self.add_host),
                              self.req, "2",
                              body={"add_host": {"host": "host1"}})
            mock_add.assert_called_once_with(self.context, "2",
                                             "host1")

    def test_add_host_with_invalid_id(self):
        body = {"add_host": {"host": "host1"}}
        self.assertRaises(exc.HTTPBadRequest, eval(self.add_host),
                          self.req, 'foo', body=body)

    def test_add_host_with_bad_host(self):
        side_effect = exception.ComputeHostNotFound(host="bogus_host")
        with mock.patch.object(self.controller.api, 'add_host_to_aggregate',
                               side_effect=side_effect) as mock_add:
            self.assertRaises(exc.HTTPNotFound, eval(self.add_host),
                              self.req, "1",
                              body={"add_host": {"host": "bogus_host"}})
            mock_add.assert_called_once_with(self.context, "1", "bogus_host")

    def test_add_host_with_missing_host(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": {"asdf": "asdf"}})

    def test_add_host_with_invalid_format_host(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": {"host": "a" * 300}})

    def test_add_host_with_invalid_name_host(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": {"host": "bad:host"}})

    def test_add_host_with_multiple_hosts(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": {"host": ["host1", "host2"]}})

    def test_add_host_raises_key_error(self):
        with mock.patch.object(self.controller.api, 'add_host_to_aggregate',
                               side_effect=KeyError) as mock_add:
            self.assertRaises(exc.HTTPInternalServerError,
                              eval(self.add_host), self.req, "1",
                              body={"add_host": {"host": "host1"}})
            mock_add.assert_called_once_with(self.context, "1", "host1")

    def test_add_host_with_invalid_request(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": "1"})

    def test_add_host_with_non_string(self):
        self.assertRaises(self.bad_request, eval(self.add_host),
                self.req, "1", body={"add_host": {"host": 1}})

    def test_remove_host(self):
        return_value = _make_agg_obj({'metadata': {}})
        with mock.patch.object(self.controller.api,
                               'remove_host_from_aggregate',
                               return_value=return_value) as mock_rem:
            eval(self.remove_host)(self.req, "1",
                                   body={"remove_host": {"host": "host1"}})
            mock_rem.assert_called_once_with(self.context, "1", "host1")

    def test_remove_host_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          eval(self.remove_host),
                          self.user_req, "1",
                          body={"remove_host": {"host": "host1"}})

    def test_remove_host_with_bad_aggregate(self):
        side_effect = exception.AggregateNotFound(
            aggregate_id="2")
        with mock.patch.object(self.controller.api,
                               'remove_host_from_aggregate',
                               side_effect=side_effect) as mock_rem:
            self.assertRaises(exc.HTTPNotFound, eval(self.remove_host),
                              self.req, "2",
                              body={"remove_host": {"host": "host1"}})
            mock_rem.assert_called_once_with(self.context, "2",
                                             "host1")

    def test_remove_host_with_invalid_id(self):
        body = {"remove_host": {"host": "host1"}}
        self.assertRaises(exc.HTTPBadRequest, eval(self.remove_host),
                          self.req, 'foo', body=body)

    def test_remove_host_with_host_not_in_aggregate(self):
        side_effect = exception.AggregateHostNotFound(aggregate_id="1",
                                                      host="host1")
        with mock.patch.object(self.controller.api,
                               'remove_host_from_aggregate',
                               side_effect=side_effect) as mock_rem:
            self.assertRaises(exc.HTTPNotFound, eval(self.remove_host),
                              self.req, "1",
                              body={"remove_host": {"host": "host1"}})
            mock_rem.assert_called_once_with(self.context, "1", "host1")

    def test_remove_host_with_bad_host(self):
        side_effect = exception.ComputeHostNotFound(host="bogushost")
        with mock.patch.object(self.controller.api,
                               'remove_host_from_aggregate',
                               side_effect=side_effect) as mock_rem:
            self.assertRaises(exc.HTTPNotFound, eval(self.remove_host),
                self.req, "1", body={"remove_host": {"host": "bogushost"}})
            mock_rem.assert_called_once_with(self.context, "1", "bogushost")

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
        with mock.patch.object(self.controller.api,
                               'update_aggregate_metadata',
                               return_value=AGGREGATE) as mock_update:
            result = eval(self.set_metadata)(self.req, "1", body=body)
            result = _transform_aggregate_az(result['aggregate'])
            self._assert_agg_data(AGGREGATE, _make_agg_obj(result))
            mock_update.assert_called_once_with(self.context, "1",
                body["set_metadata"]['metadata'])

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
        side_effect = exception.AggregateNotFound(aggregate_id="2")

        with mock.patch.object(self.controller.api,
                               'update_aggregate_metadata',
                               side_effect=side_effect) as mock_update:
            self.assertRaises(exc.HTTPNotFound, eval(self.set_metadata),
                self.req, "2", body=body)
            mock_update.assert_called_once_with(self.context, "2",
                body["set_metadata"]['metadata'])

    def test_set_metadata_with_invalid_id(self):
        body = {"set_metadata": {"metadata": {"foo": "bar"}}}
        self.assertRaises(exc.HTTPBadRequest, eval(self.set_metadata),
                          self.req, 'foo', body=body)

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
        with mock.patch.object(self.controller.api,
                               'delete_aggregate') as mock_del:
            self.controller.delete(self.req, "1")
            mock_del.assert_called_once_with(self.context, "1")

    def test_delete_aggregate_no_admin(self):
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.delete,
                          self.user_req, "1")

    def test_delete_aggregate_with_bad_aggregate(self):
        side_effect = exception.AggregateNotFound(
            aggregate_id="2")
        with mock.patch.object(self.controller.api, 'delete_aggregate',
                               side_effect=side_effect) as mock_del:
            self.assertRaises(exc.HTTPNotFound, self.controller.delete,
                self.req, "2")
            mock_del.assert_called_once_with(self.context, "2")

    def test_delete_with_invalid_id(self):
        self.assertRaises(exc.HTTPBadRequest, self.controller.delete,
                          self.req, 'foo')

    def test_delete_aggregate_with_host(self):
        with mock.patch.object(self.controller.api, "delete_aggregate",
                               side_effect=exception.InvalidAggregateAction(
                               action="delete", aggregate_id="2",
                               reason="not empty")):
            self.assertRaises(exc.HTTPBadRequest,
                              self.controller.delete,
                              self.req, "2")

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

        # _marshall_aggregate() puts all fields and obj_extra_fields in the
        # top-level dict, so we need to put availability_zone at the top also
        agg['availability_zone'] = 'nova'

        avr_v240 = api_version_request.APIVersionRequest("2.40")
        avr_v241 = api_version_request.APIVersionRequest("2.41")

        req = mock.MagicMock(api_version_request=avr_v241)
        marshalled_agg = self.controller._marshall_aggregate(req, agg_obj)

        self.assertEqual(agg, marshalled_agg['aggregate'])

        req = mock.MagicMock(api_version_request=avr_v240)
        marshalled_agg = self.controller._marshall_aggregate(req, agg_obj)

        # UUID isn't in microversion 2.40 and before
        del agg['uuid']
        self.assertEqual(agg, marshalled_agg['aggregate'])

    def _assert_agg_data(self, expected, actual):
        self.assertTrue(obj_base.obj_equal_prims(expected, actual),
                        "The aggregate objects were not equal")
