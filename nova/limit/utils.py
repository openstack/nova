# Copyright 2022 StackHPC
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

from oslo_limit import exception as limit_exceptions
from oslo_limit import limit
from oslo_log import log as logging

import nova.conf

LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF

UNIFIED_LIMITS_DRIVER = "nova.quota.UnifiedLimitsDriver"
ENDPOINT = None


def use_unified_limits():
    return CONF.quota.driver == UNIFIED_LIMITS_DRIVER


def _endpoint():
    global ENDPOINT
    if ENDPOINT is None:
        # This is copied from oslo_limit/limit.py
        endpoint_id = CONF.oslo_limit.endpoint_id
        if not endpoint_id:
            raise ValueError("endpoint_id is not configured")
        enforcer = limit.Enforcer(lambda: None)
        ENDPOINT = enforcer.connection.get_endpoint(endpoint_id)
    return ENDPOINT


def should_enforce(exc: limit_exceptions.ProjectOverLimit) -> bool:
    """Whether the exceeded resource limit should be enforced.

    Given a ProjectOverLimit exception from oslo.limit, check whether the
    involved limit(s) should be enforced. This is needed if we need more logic
    than is available by default in oslo.limit.

    :param exc: An oslo.limit ProjectOverLimit exception instance, which
        contains a list of OverLimitInfo. Each OverLimitInfo includes a
        resource_name, limit, current_usage, and delta.
    """
    # If any exceeded limit is greater than zero, it means an explicitly set
    # limit has been enforced. And if any explicitly set limit has gone over
    # quota, the enforcement should be upheld and there is no need to consider
    # the potential for unset limits.
    if any(info.limit > 0 for info in exc.over_limit_info_list):
        return True

    # Next, if all of the exceeded limits are -1, we don't need to enforce and
    # we can avoid calling Keystone for the list of registered limits.
    #
    # A value of -1 is documented in Keystone as meaning unlimited:
    #
    # "Note
    #  The default limit of registered limit and the resource limit of project
    #  limit now are limited from -1 to 2147483647 (integer). -1 means no limit
    #  and 2147483647 is the max value for user to define limits."
    #
    # https://docs.openstack.org/keystone/latest/admin/unified-limits.html#what-is-a-limit
    #
    # but oslo.limit enforce does not treat -1 as unlimited at this time and
    # instead uses its literal integer value. We will consider any negative
    # limit value as unlimited.
    if all(info.limit < 0 for info in exc.over_limit_info_list):
        return False

    # Only resources with exceeded limits of "0" are candidates for
    # enforcement.
    #
    # A limit of "0" in the over_limit_info_list means that oslo.limit is
    # telling us the limit is 0. But oslo.limit returns 0 for two cases:
    # a) it found a limit of 0 in Keystone or b) it did not find a limit in
    # Keystone at all.
    #
    # We will need to query the list of registered limits from Keystone in
    # order to determine whether each "0" limit is case a) or case b).
    enforce_candidates = {
        info.resource_name for info in exc.over_limit_info_list
            if info.limit == 0}

    # Get a list of all the registered limits. There is not a way to filter by
    # resource names however this will do one API call whereas the alternative
    # is calling GET /registered_limits/{registered_limit_id} for each resource
    # name.
    enforcer = limit.Enforcer(lambda: None)
    registered_limits = list(enforcer.connection.registered_limits(
        service_id=_endpoint().service_id, region_id=_endpoint().region_id))

    # Make a set of resource names of the registered limits.
    have_limits_set = {limit.resource_name for limit in registered_limits}

    # If any candidates have limits set, enforce. It means at least one limit
    # has been explicitly set to 0.
    if enforce_candidates & have_limits_set:
        return True

    # The resource list will be either a require list or an ignore list.
    require_or_ignore = CONF.quota.unified_limits_resource_list

    strategy = CONF.quota.unified_limits_resource_strategy
    enforced = enforce_candidates
    if strategy == 'require':
        # Resources that are in both the candidate list and in the require list
        # should be enforced.
        enforced = enforce_candidates & set(require_or_ignore)
    elif strategy == 'ignore':
        # Resources that are in the candidate list but are not in the ignore
        # list should be enforced.
        enforced = enforce_candidates - set(require_or_ignore)
    else:
        LOG.error(
            f'Invalid strategy value: {strategy} is specified in the '
            '[quota]unified_limits_resource_strategy config option, so '
            f'enforcing for resources {enforced}')
    # Log in case we need to debug unexpected enforcement or non-enforcement.
    msg = (
        f'enforcing for resources {enforced}' if enforced else 'not enforcing')
    LOG.debug(
        f'Resources {enforce_candidates} have no registered limits set in '
        f'Keystone. [quota]unified_limits_resource_strategy is {strategy} and '
        f'[quota]unified_limits_resource_list is {require_or_ignore}, '
        f'so {msg}')
    return bool(enforced)
