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

"""Placement API handlers for getting allocation candidates."""

import collections

from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import timeutils
import six
import webob

from nova.api.openstack.placement import exception
from nova.api.openstack.placement import microversion
from nova.api.openstack.placement.objects import resource_provider as rp_obj
from nova.api.openstack.placement.policies import allocation_candidate as \
    policies
from nova.api.openstack.placement.schemas import allocation_candidate as schema
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova.i18n import _


def _transform_allocation_requests_dict(alloc_reqs):
    """Turn supplied list of AllocationRequest objects into a list of
    allocations dicts keyed by resource provider uuid of resources involved
    in the allocation request. The returned results are intended to be used
    as the body of a PUT /allocations/{consumer_uuid} HTTP request at
    micoversion 1.12 (and beyond). The JSON objects look like the following:

    [
        {
            "allocations": {
                $rp_uuid1: {
                    "resources": {
                        "MEMORY_MB": 512
                        ...
                    }
                },
                $rp_uuid2: {
                    "resources": {
                        "DISK_GB": 1024
                        ...
                    }
                }
            },
        },
        ...
    ]
    """
    results = []

    for ar in alloc_reqs:
        # A default dict of {$rp_uuid: "resources": {})
        rp_resources = collections.defaultdict(lambda: dict(resources={}))
        for rr in ar.resource_requests:
            res_dict = rp_resources[rr.resource_provider.uuid]['resources']
            res_dict[rr.resource_class] = rr.amount
        results.append(dict(allocations=rp_resources))

    return results


def _transform_allocation_requests_list(alloc_reqs):
    """Turn supplied list of AllocationRequest objects into a list of dicts of
    resources involved in the allocation request. The returned results is
    intended to be able to be used as the body of a PUT
    /allocations/{consumer_uuid} HTTP request, prior to microversion 1.12,
    so therefore we return a list of JSON objects that looks like the
    following:

    [
        {
            "allocations": [
                {
                    "resource_provider": {
                        "uuid": $rp_uuid,
                    }
                    "resources": {
                        $resource_class: $requested_amount, ...
                    },
                }, ...
            ],
        }, ...
    ]
    """
    results = []
    for ar in alloc_reqs:
        provider_resources = collections.defaultdict(dict)
        for rr in ar.resource_requests:
            res_dict = provider_resources[rr.resource_provider.uuid]
            res_dict[rr.resource_class] = rr.amount

        allocs = [
            {
                "resource_provider": {
                    "uuid": rp_uuid,
                },
                "resources": resources,
            } for rp_uuid, resources in provider_resources.items()
        ]
        alloc = {
            "allocations": allocs
        }
        results.append(alloc)
    return results


def _transform_provider_summaries(p_sums, requests, want_version):
    """Turn supplied list of ProviderSummary objects into a dict, keyed by
    resource provider UUID, of dicts of provider and inventory information.
    The traits only show up when `want_version` is 1.17 or newer. All the
    resource classes are shown when `want_version` is 1.27 or newer while
    only requested resources are included in the `provider_summaries`
    for older versions. The parent and root provider uuids only show up
    when `want_version` is 1.29 or newer.

    {
       RP_UUID_1: {
           'resources': {
              'DISK_GB': {
                'capacity': 100,
                'used': 0,
              },
              'VCPU': {
                'capacity': 4,
                'used': 0,
              }
           },
           # traits shows up from microversion 1.17
           'traits': [
                'HW_CPU_X86_AVX512F',
                'HW_CPU_X86_AVX512CD'
           ]
           # parent/root provider uuids show up from microversion 1.29
           parent_provider_uuid: null,
           root_provider_uuid: RP_UUID_1
       },
       RP_UUID_2: {
           'resources': {
              'DISK_GB': {
                'capacity': 100,
                'used': 0,
              },
              'VCPU': {
                'capacity': 4,
                'used': 0,
              }
           },
           # traits shows up from microversion 1.17
           'traits': [
                'HW_NIC_OFFLOAD_TSO',
                'HW_NIC_OFFLOAD_GRO'
           ],
           # parent/root provider uuids show up from microversion 1.29
           parent_provider_uuid: null,
           root_provider_uuid: RP_UUID_2
       }
    }
    """
    include_traits = want_version.matches((1, 17))
    include_all_resources = want_version.matches((1, 27))
    enable_nested_providers = want_version.matches((1, 29))

    ret = {}
    requested_resources = set()

    for requested_group in requests.values():
        requested_resources |= set(requested_group.resources)

    # if include_all_resources is false, only requested resources are
    # included in the provider_summaries.
    for ps in p_sums:
        resources = {
            psr.resource_class: {
                'capacity': psr.capacity,
                'used': psr.used,
            } for psr in ps.resources if (
                include_all_resources or
                psr.resource_class in requested_resources)
        }

        ret[ps.resource_provider.uuid] = {'resources': resources}

        if include_traits:
            ret[ps.resource_provider.uuid]['traits'] = [
                t.name for t in ps.traits]

        if enable_nested_providers:
            ret[ps.resource_provider.uuid]['parent_provider_uuid'] = (
                ps.resource_provider.parent_provider_uuid)
            ret[ps.resource_provider.uuid]['root_provider_uuid'] = (
                ps.resource_provider.root_provider_uuid)

    return ret


def _exclude_nested_providers(alloc_cands):
    """Exclude allocation requests and provider summaries for old microversions
    if they involve more than one provider from the same tree.
    """
    # Build a temporary dict, keyed by root RP UUID of sets of UUIDs of all RPs
    # in that tree.
    tree_rps_by_root = collections.defaultdict(set)
    for ps in alloc_cands.provider_summaries:
        rp_uuid = ps.resource_provider.uuid
        root_uuid = ps.resource_provider.root_provider_uuid
        tree_rps_by_root[root_uuid].add(rp_uuid)
    # We use this to get a list of sets of providers in each tree
    tree_sets = list(tree_rps_by_root.values())

    for a_req in alloc_cands.allocation_requests[:]:
        alloc_rp_uuids = set([
            arr.resource_provider.uuid for arr in a_req.resource_requests])
        # If more than one allocation is provided by the same tree, kill
        # that allocation request.
        if any(len(tree_set & alloc_rp_uuids) > 1 for tree_set in tree_sets):
            alloc_cands.allocation_requests.remove(a_req)

    # Exclude eliminated providers from the provider summaries.
    all_rp_uuids = set()
    for a_req in alloc_cands.allocation_requests:
        all_rp_uuids |= set(
            arr.resource_provider.uuid for arr in a_req.resource_requests)
    for ps in alloc_cands.provider_summaries[:]:
        if ps.resource_provider.uuid not in all_rp_uuids:
            alloc_cands.provider_summaries.remove(ps)

    return alloc_cands


def _transform_allocation_candidates(alloc_cands, requests, want_version):
    """Turn supplied AllocationCandidates object into a dict containing
    allocation requests and provider summaries.

    {
        'allocation_requests': <ALLOC_REQUESTS>,
        'provider_summaries': <PROVIDER_SUMMARIES>,
    }
    """
    # exclude nested providers with old microversions
    if not want_version.matches((1, 29)):
        alloc_cands = _exclude_nested_providers(alloc_cands)

    if want_version.matches((1, 12)):
        a_reqs = _transform_allocation_requests_dict(
            alloc_cands.allocation_requests)
    else:
        a_reqs = _transform_allocation_requests_list(
            alloc_cands.allocation_requests)

    p_sums = _transform_provider_summaries(
        alloc_cands.provider_summaries, requests, want_version)

    return {
        'allocation_requests': a_reqs,
        'provider_summaries': p_sums,
    }


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.10')
@util.check_accept('application/json')
def list_allocation_candidates(req):
    """GET a JSON object with a list of allocation requests and a JSON object
    of provider summary objects

    On success return a 200 and an application/json body representing
    a collection of allocation requests and provider summaries
    """
    context = req.environ['placement.context']
    context.can(policies.LIST)
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    get_schema = schema.GET_SCHEMA_1_10
    if want_version.matches((1, 25)):
        get_schema = schema.GET_SCHEMA_1_25
    elif want_version.matches((1, 21)):
        get_schema = schema.GET_SCHEMA_1_21
    elif want_version.matches((1, 17)):
        get_schema = schema.GET_SCHEMA_1_17
    elif want_version.matches((1, 16)):
        get_schema = schema.GET_SCHEMA_1_16
    util.validate_query_params(req, get_schema)

    requests = util.parse_qs_request_groups(req)
    limit = req.GET.getall('limit')
    # JSONschema has already confirmed that limit has the form
    # of an integer.
    if limit:
        limit = int(limit[0])

    group_policy = req.GET.getall('group_policy') or None
    # Schema ensures we get either "none" or "isolate"
    if group_policy:
        group_policy = group_policy[0]
    else:
        # group_policy is required if more than one numbered request group was
        # specified.
        if len([rg for rg in requests.values() if rg.use_same_provider]) > 1:
            raise webob.exc.HTTPBadRequest(
                _('The "group_policy" parameter is required when specifying '
                  'more than one "resources{N}" parameter.'))

    try:
        cands = rp_obj.AllocationCandidates.get_by_requests(
            context, requests, limit=limit, group_policy=group_policy)
    except exception.ResourceClassNotFound as exc:
        raise webob.exc.HTTPBadRequest(
            _('Invalid resource class in resources parameter: %(error)s') %
            {'error': exc})
    except exception.TraitNotFound as exc:
        raise webob.exc.HTTPBadRequest(six.text_type(exc))

    response = req.response
    trx_cands = _transform_allocation_candidates(cands, requests, want_version)
    json_data = jsonutils.dumps(trx_cands)
    response.body = encodeutils.to_utf8(json_data)
    response.content_type = 'application/json'
    if want_version.matches((1, 15)):
        response.cache_control = 'no-cache'
        response.last_modified = timeutils.utcnow(with_timezone=True)
    return response
