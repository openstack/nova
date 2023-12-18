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

import functools
import typing as ty

from oslo_limit import exception as limit_exceptions
from oslo_limit import limit
from oslo_log import log as logging

import nova.conf
from nova import exception
from nova.limit import utils as nova_limit_utils
from nova import objects

LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF

# Entity types for API Limits, same as names of config options prefixed with
# "server_" to disambiguate them in keystone
SERVER_METADATA_ITEMS = "server_metadata_items"
INJECTED_FILES = "server_injected_files"
INJECTED_FILES_CONTENT = "server_injected_file_content_bytes"
INJECTED_FILES_PATH = "server_injected_file_path_bytes"
API_LIMITS = set([
    SERVER_METADATA_ITEMS,
    INJECTED_FILES,
    INJECTED_FILES_CONTENT,
    INJECTED_FILES_PATH,
])

# Entity types for all DB limits, same as names of config options prefixed with
# "server_" to disambiguate them in keystone
KEY_PAIRS = "server_key_pairs"
SERVER_GROUPS = "server_groups"
SERVER_GROUP_MEMBERS = "server_group_members"
DB_LIMITS = set([
    KEY_PAIRS,
    SERVER_GROUPS,
    SERVER_GROUP_MEMBERS,
])

# Checks only happen when we are using the unified limits driver
UNIFIED_LIMITS_DRIVER = "nova.quota.UnifiedLimitsDriver"

# Map entity types to the exception we raise in the case that the resource is
# over the allowed limit. Each of these should be a subclass of
# exception.OverQuota.
EXCEPTIONS = {
    KEY_PAIRS: exception.KeypairLimitExceeded,
    INJECTED_FILES_CONTENT: exception.OnsetFileContentLimitExceeded,
    INJECTED_FILES_PATH: exception.OnsetFilePathLimitExceeded,
    INJECTED_FILES: exception.OnsetFileLimitExceeded,
    SERVER_METADATA_ITEMS: exception.MetadataLimitExceeded,
    SERVER_GROUPS: exception.ServerGroupLimitExceeded,
    SERVER_GROUP_MEMBERS: exception.GroupMemberLimitExceeded,
}

# Map new limit-based quota names to the legacy ones.
LEGACY_LIMITS = {
    SERVER_METADATA_ITEMS: "metadata_items",
    INJECTED_FILES: "injected_files",
    INJECTED_FILES_CONTENT: "injected_file_content_bytes",
    INJECTED_FILES_PATH: "injected_file_path_bytes",
    KEY_PAIRS: "key_pairs",
    SERVER_GROUPS: SERVER_GROUPS,
    SERVER_GROUP_MEMBERS: SERVER_GROUP_MEMBERS,
}


def get_in_use(
    context: 'nova.context.RequestContext', project_id: str
) -> ty.Dict[str, int]:
    """Returns in use counts for each resource, for given project.

    This sounds simple but many resources can't be counted per project,
    so the only sensible value is 0. For example, key pairs are counted
    per user, and server group members are counted per server group,
    and metadata items are counted per server.
    This behaviour is consistent with what is returned today by the
    DB based quota driver.
    """
    count = _server_group_count(context, project_id)['server_groups']
    usages = {
        # DB limits
        SERVER_GROUPS: count,
        SERVER_GROUP_MEMBERS: 0,
        KEY_PAIRS: 0,
        # API limits
        SERVER_METADATA_ITEMS: 0,
        INJECTED_FILES: 0,
        INJECTED_FILES_CONTENT: 0,
        INJECTED_FILES_PATH: 0,
    }
    return _convert_keys_to_legacy_name(usages)


def always_zero_usage(
    project_id: str, resource_names: ty.List[str]
) -> ty.Dict[str, int]:
    """Called by oslo_limit's enforcer"""
    # Return usage of 0 for API limits. Values in API requests will be used as
    # the deltas.
    return {resource_name: 0 for resource_name in resource_names}


def enforce_api_limit(entity_type: str, count: int) -> None:
    """Check if the values given are over the limit for that key.

    This is generally used for limiting the size of certain API requests
    that eventually get stored in the database.
    """
    if not nova_limit_utils.use_unified_limits():
        return

    if entity_type not in API_LIMITS:
        fmt = "%s is not a valid API limit: %s"
        raise ValueError(fmt % (entity_type, API_LIMITS))

    try:
        enforcer = limit.Enforcer(always_zero_usage)
    except limit_exceptions.SessionInitError as e:
        msg = ("Failed to connect to keystone while enforcing %s quota limit."
               % entity_type)
        LOG.error(msg + " Error: " + str(e))
        raise exception.KeystoneConnectionFailed(msg)

    try:
        enforcer.enforce(None, {entity_type: count})
    except limit_exceptions.ProjectOverLimit as e:
        # Copy the exception message to a OverQuota to propagate to the
        # API layer.
        raise EXCEPTIONS.get(entity_type, exception.OverQuota)(str(e))


def enforce_db_limit(
    context: 'nova.context.RequestContext',
    entity_type: str,
    entity_scope: ty.Any,
    delta: int
) -> None:
    """Check provided delta does not put resource over limit.

    Firstly we count the current usage given the specified scope.
    We then add that count to the specified  delta to see if we
    are over the limit for that kind of entity.

    Note previously we used to recheck these limits.
    However these are really soft DDoS protections,
    not hard resource limits, so we don't do the recheck for these.

    The scope is specific to the limit type:
    * key_pairs scope is context.user_id
    * server_groups scope is context.project_id
    * server_group_members scope is server_group_uuid
    """
    if not nova_limit_utils.use_unified_limits():
        return

    if entity_type not in DB_COUNT_FUNCTION.keys():
        fmt = "%s does not have a DB count function defined: %s"
        raise ValueError(fmt % (entity_type, DB_COUNT_FUNCTION.keys()))
    if delta < 0:
        raise ValueError("delta must be a positive integer")

    count_function = DB_COUNT_FUNCTION[entity_type]

    try:
        enforcer = limit.Enforcer(
            functools.partial(count_function, context, entity_scope))
    except limit_exceptions.SessionInitError as e:
        msg = ("Failed to connect to keystone while enforcing %s quota limit."
               % entity_type)
        LOG.error(msg + " Error: " + str(e))
        raise exception.KeystoneConnectionFailed(msg)

    try:
        enforcer.enforce(None, {entity_type: delta})
    except limit_exceptions.ProjectOverLimit as e:
        # Copy the exception message to a OverQuota to propagate to the
        # API layer.
        raise EXCEPTIONS.get(entity_type, exception.OverQuota)(str(e))


def _convert_keys_to_legacy_name(
    new_dict: ty.Dict[str, int]
) -> ty.Dict[str, int]:
    legacy = {}
    for new_name, old_name in LEGACY_LIMITS.items():
        # defensive in case oslo or keystone doesn't give us an answer
        legacy[old_name] = new_dict.get(new_name) or 0
    return legacy


def get_legacy_default_limits() -> ty.Dict[str, int]:
    # TODO(johngarbutt): need oslo.limit API for this, it should do caching
    enforcer = limit.Enforcer(lambda: None)
    new_limits = enforcer.get_registered_limits(LEGACY_LIMITS.keys())
    return _convert_keys_to_legacy_name(dict(new_limits))


def _keypair_count(context, user_id, *args):
    count = objects.KeyPairList.get_count_by_user(context, user_id)
    return {'server_key_pairs': count}


def _server_group_count(context, project_id, *args):
    raw_counts = objects.InstanceGroupList.get_counts(context, project_id)
    return {'server_groups': raw_counts['project']['server_groups']}


def _server_group_members_count(context, server_group_uuid, *args):
    # NOTE(johngarbutt) we used to count members added per user
    server_group = objects.InstanceGroup.get_by_uuid(context,
                                                     server_group_uuid)
    return {'server_group_members': len(server_group.members)}


DB_COUNT_FUNCTION = {
    KEY_PAIRS: _keypair_count,
    SERVER_GROUPS: _server_group_count,
    SERVER_GROUP_MEMBERS: _server_group_members_count
}
