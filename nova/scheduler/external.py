# Copyright (c) 2025 SAP SE
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
"""
This module provides functionality to interact with an external scheduler API
to reorder and filter hosts based on additional criteria.

The external scheduler API is expected to take a list of weighed hosts and
their weights, along with the request specification, and return a reordered
and filtered list of host names.
"""
import jsonschema
from oslo_log import log as logging
import requests

import nova.conf
from nova.scheduler import utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


# The expected response schema from the external scheduler api.
# The response should contain a list of ordered host names.
response_schema = {
  "type": "object",
  "properties": {
    "hosts": {
      "type": "array",
      "items": {
        "type": "string"
      }
    }
  },
  "required": ["hosts"],
  "additionalProperties": False,
}


def call_external_scheduler_api(weighed_hosts, weights, spec_obj):
    """Reorder and filter hosts using an external scheduler service."""
    if not weighed_hosts:
        return weighed_hosts
    if not (url := CONF.filter_scheduler.external_scheduler_api_url):
        LOG.debug("External scheduler API is not enabled.")
        return weighed_hosts
    timeout = CONF.filter_scheduler.external_scheduler_timeout

    json_data = {
        "spec": spec_obj.obj_to_primitive(),
        # Extract some flags from the spec to indicate the type of
        # request. This will allow the external scheduler to quickly
        # decide if it wants to handle the request or not.
        "rebuild": utils.request_is_rebuild(spec_obj),
        "resize": utils.request_is_resize(spec_obj),
        "live": utils.request_is_live_migrate(spec_obj),
        "vmware": not utils.is_non_vmware_spec(spec_obj),
        # Only provide basic information for the hosts for now.
        # The external scheduler is expected to fetch statistics
        # about the hosts separately, so we don't need to pass
        # them here.
        "hosts": [
            {
                "host": h.host,  # e.g. nova-compute-bb123
                "hypervisor_hostname": h.hypervisor_hostname,
            } for h in weighed_hosts
        ],
        # Also pass previous weights from the Nova weigher pipeline.
        # The external scheduler api is expected to take these weights
        # into account if provided.
        "weights": weights,
    }
    LOG.debug("Calling external scheduler API with %s", json_data)
    try:
        response = requests.post(url, json=json_data, timeout=timeout)
        response.raise_for_status()
        # If the JSON parsing fails, this will also raise a RequestException.
        response_json = response.json()
    except requests.RequestException as e:
        LOG.error("Failed to call external scheduler API: %s", e)
        return weighed_hosts

    # The external scheduler api is expected to return a json with
    # a sorted list of host names. Note that no weights are returned.
    try:
        jsonschema.validate(response_json, response_schema)
    except jsonschema.ValidationError as e:
        LOG.error("External scheduler response is invalid: %s", e)
        return weighed_hosts

    # The list of host names can also be empty. In this case, we trust
    # the external scheduler decision and return an empty list.
    if not (host_names := response_json["hosts"]):
        # If this case happens often, it may indicate an issue.
        LOG.warning("External scheduler filtered out all hosts.")

    # Reorder the weighed hosts based on the list of host names returned
    # by the external scheduler api.
    weighed_hosts_dict = {h.host: h for h in weighed_hosts}
    return [weighed_hosts_dict[h] for h in host_names]
