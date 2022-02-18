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

from oslo_policy import policy

RULE_ADMIN_OR_OWNER = 'rule:admin_or_owner'  # Admins or owners of the resource
RULE_ADMIN_API = 'rule:admin_api'  # Allow only users with the admin role
RULE_ANY = '@'  # Any user is allowed to perform the action.
RULE_NOBODY = '!'  # No users are allowed to perform the action.

DEPRECATED_REASON = """
Nova API policies are introducing new default roles with scope_type
capabilities. Old policies are deprecated and silently going to be ignored
in nova 23.0.0 release.
"""

DEPRECATED_ADMIN_POLICY = policy.DeprecatedRule(
    name=RULE_ADMIN_API,
    check_str='is_admin:True',
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since='21.0.0'
)

DEPRECATED_ADMIN_OR_OWNER_POLICY = policy.DeprecatedRule(
    name=RULE_ADMIN_OR_OWNER,
    check_str='is_admin:True or project_id:%(project_id)s',
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since='21.0.0'
)
PROJECT_ADMIN = 'rule:project_admin_api'
PROJECT_MEMBER = 'rule:project_member_api'
PROJECT_READER = 'rule:project_reader_api'
PROJECT_READER_OR_ADMIN = 'rule:project_reader_or_admin'
ADMIN = 'rule:context_is_admin'

# NOTE(gmann): Below is the mapping of new roles and scope_types
# with legacy roles::

# Legacy Rule        |    New Rules        |Operation       |scope_type|
# -------------------+---------------------+----------------+-----------
#                    |-> ADMIN             |Global resource | [system]
# RULE_ADMIN_API     |                     |Write & Read    |
#                    |-> PROJECT_ADMIN     |Project resource| [project]
#                    |                     |Write           |
# ----------------------------------------------------------------------
#                    |-> PROJECT_ADMIN     |Project resource| [project]
#                    |                     |Write           |
#                    |-> PROJECT_MEMBER    |Project resource| [project]
# RULE_ADMIN_OR_OWNER|                     |Write           |
#                    |-> PROJECT_READER    |Project resource| [project]
#                    |                     |Read            |

# NOTE(johngarbutt) The base rules here affect so many APIs the list
# of related API operations has not been populated. It would be
# crazy hard to manually maintain such a list.

# NOTE(gmann): Keystone already support implied roles means assignment
# of one role implies the assignment of another. New defaults roles
# `reader`, `member` also has been added in bootstrap. If the bootstrap
# process is re-run, and a `reader`, `member`, or `admin` role already
# exists, a role implication chain will be created: `admin` implies
# `member` implies `reader`.
# For example: If we give access to 'reader' it means the 'admin' and
# 'member' also get access.
rules = [
    policy.RuleDefault(
        "context_is_admin",
        "role:admin",
        "Decides what is required for the 'is_admin:True' check to succeed.",
        deprecated_rule=DEPRECATED_ADMIN_POLICY),
    policy.RuleDefault(
        "admin_or_owner",
        "is_admin:True or project_id:%(project_id)s",
        "Default rule for most non-Admin APIs.",
        deprecated_for_removal=True,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.RuleDefault(
        "admin_api",
        "is_admin:True",
        "Default rule for most Admin APIs.",
        deprecated_for_removal=True,
        deprecated_reason=DEPRECATED_REASON,
        deprecated_since='21.0.0'),
    policy.RuleDefault(
        "project_admin_api",
        "role:admin and project_id:%(project_id)s",
        "Default rule for Project level admin APIs.",
        deprecated_rule=DEPRECATED_ADMIN_POLICY),
    policy.RuleDefault(
        "project_member_api",
        "role:member and project_id:%(project_id)s",
        "Default rule for Project level non admin APIs.",
        deprecated_rule=DEPRECATED_ADMIN_OR_OWNER_POLICY),
    policy.RuleDefault(
        "project_reader_api",
        "role:reader and project_id:%(project_id)s",
        "Default rule for Project level read only APIs.",
        deprecated_rule=DEPRECATED_ADMIN_OR_OWNER_POLICY),
    policy.RuleDefault(
        "project_reader_or_admin",
        "rule:project_reader_api or rule:context_is_admin",
        "Default rule for Project reader and admin APIs.",
        deprecated_rule=DEPRECATED_ADMIN_OR_OWNER_POLICY)
]


def list_rules():
    return rules
