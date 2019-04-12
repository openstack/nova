# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from oslo_serialization import jsonutils

from nova.tests.functional.api_sample_tests import api_sample_base


class AggregatesSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-aggregates"
    # extra_subs is a noop in the base v2.1 test class; it's used to sub in
    # additional details for response verification of actions performed on an
    # existing aggregate.
    extra_subs = {}

    def _test_aggregate_create(self):
        subs = {
            "aggregate_id": r'(?P<id>\d+)'
        }
        response = self._do_post('os-aggregates', 'aggregate-post-req', subs)
        return self._verify_response('aggregate-post-resp',
                                     subs, response, 200)

    def test_aggregate_create(self):
        self._test_aggregate_create()

    def _test_add_host(self, aggregate_id, host):
        subs = {
            "host_name": host
        }
        response = self._do_post('os-aggregates/%s/action' % aggregate_id,
                                 'aggregate-add-host-post-req', subs)
        subs.update(self.extra_subs)
        self._verify_response('aggregates-add-host-post-resp', subs,
                              response, 200)

    def test_list_aggregates(self):
        aggregate_id = self._test_aggregate_create()
        self._test_add_host(aggregate_id, self.compute.host)
        response = self._do_get('os-aggregates')
        self._verify_response('aggregates-list-get-resp', {}, response, 200)

    def test_aggregate_get(self):
        agg_id = self._test_aggregate_create()
        response = self._do_get('os-aggregates/%s' % agg_id)
        self._verify_response('aggregates-get-resp', self.extra_subs,
                              response, 200)

    def test_add_metadata(self):
        agg_id = self._test_aggregate_create()
        response = self._do_post('os-aggregates/%s/action' % agg_id,
                                 'aggregate-metadata-post-req',
                                 {'action': 'set_metadata'})
        self._verify_response('aggregates-metadata-post-resp', self.extra_subs,
                              response, 200)

    def test_add_host(self):
        aggregate_id = self._test_aggregate_create()
        self._test_add_host(aggregate_id, self.compute.host)

    def test_remove_host(self):
        self.test_add_host()
        subs = {
            "host_name": self.compute.host,
        }
        response = self._do_post('os-aggregates/1/action',
                                 'aggregate-remove-host-post-req', subs)
        subs.update(self.extra_subs)
        self._verify_response('aggregates-remove-host-post-resp',
                              subs, response, 200)

    def test_update_aggregate(self):
        aggregate_id = self._test_aggregate_create()
        response = self._do_put('os-aggregates/%s' % aggregate_id,
                                  'aggregate-update-post-req', {})
        self._verify_response('aggregate-update-post-resp',
                              self.extra_subs, response, 200)


class AggregatesV2_41_SampleJsonTest(AggregatesSampleJsonTest):
    microversion = '2.41'
    scenarios = [
        (
            "v2_41", {
                'api_major_version': 'v2.1',
            },
        )
    ]

    def _test_aggregate_create(self):
        subs = {
            "aggregate_id": r'(?P<id>\d+)',
        }
        response = self._do_post('os-aggregates', 'aggregate-post-req', subs)
        # This feels like cheating since we're getting the uuid from the
        # response before we even validate that it exists in the response based
        # on the sample, but we'll fail with a KeyError if it doesn't which is
        # maybe good enough. Alternatively we have to mock out the DB API
        # to return a fake aggregate with a hard-coded uuid that matches the
        # API sample which isn't fun either.
        subs['uuid'] = jsonutils.loads(response.content)['aggregate']['uuid']
        # save off the uuid for subs validation on other actions performed
        # on this aggregate
        self.extra_subs['uuid'] = subs['uuid']
        return self._verify_response('aggregate-post-resp',
                                     subs, response, 200)
