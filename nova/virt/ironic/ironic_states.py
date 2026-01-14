# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
NOTE(JayF): This file is verbatim copied from ironic/common/states.py at
            c69caf28e88565fbf5cd2b4ee71ba49fc13738c7 and should not be
            modified except by copying newer versions from ironic.

Constants for bare metal node states.

This module contains only state constant definitions with no executable code.
For the state machine implementation, see ironic.common.states.
"""

#####################
# Provisioning states
#####################

VERBS = {
    'active': 'deploy',
    'deploy': 'deploy',
    'deleted': 'delete',
    'undeploy': 'delete',
    'manage': 'manage',
    'provide': 'provide',
    'inspect': 'inspect',
    'abort': 'abort',
    'clean': 'clean',
    'adopt': 'adopt',
    'rescue': 'rescue',
    'unrescue': 'unrescue',
    'unhold': 'unhold',
    'service': 'service',
}
""" Mapping of state-changing events that are PUT to the REST API

This is a mapping of target states which are PUT to the API, eg,
    PUT /v1/node/states/provision {'target': 'active'}

The dict format is:
    {target string used by the API: internal verb}

This provides a reference set of supported actions, and in the future
may be used to support renaming these actions.
"""

NOSTATE = None
""" No state information.

This state is used with power_state to represent a lack of knowledge of
power state, and in target_*_state fields when there is no target.
"""

ENROLL = 'enroll'
""" Node is enrolled.

This state indicates that Ironic is aware of a node, but is not managing it.
"""

VERIFYING = 'verifying'
""" Node power management credentials are being verified. """

MANAGEABLE = 'manageable'
""" Node is in a manageable state.

This state indicates that Ironic has verified, at least once, that it had
sufficient information to manage the hardware. While in this state, the node
is not available for provisioning (it must be in the AVAILABLE state for that).
"""

AVAILABLE = 'available'
""" Node is available for use and scheduling.

This state is replacing the NOSTATE state used prior to Kilo.
"""

ACTIVE = 'active'
""" Node is successfully deployed and associated with an instance. """

DEPLOY = 'deploy'
""" Node is successfully deployed and associated with an instance.
This is an alias for ACTIVE.
"""

DEPLOYWAIT = 'wait call-back'
""" Node is waiting to be deployed.

This will be the node `provision_state` while the node is waiting for
the driver to finish deployment.
"""

DEPLOYING = 'deploying'
""" Node is ready to receive a deploy request, or is currently being deployed.

A node will have its `provision_state` set to DEPLOYING briefly before it
receives its initial deploy request. It will also move to this state from
DEPLOYWAIT after the callback is triggered and deployment is continued
(disk partitioning and image copying).
"""

DEPLOYFAIL = 'deploy failed'
""" Node deployment failed. """

DEPLOYDONE = 'deploy complete'
""" Node was successfully deployed.

This is mainly a target provision state used during deployment. A successfully
deployed node should go to ACTIVE status.
"""

DEPLOYHOLD = 'deploy hold'
""" Node is being held by a deploy step. """

DELETING = 'deleting'
""" Node is actively being torn down. """

DELETED = 'deleted'
""" Node tear down was successful.

This is a transitory value of provision_state, and never
represented in target_provision_state.
"""

CLEANING = 'cleaning'
""" Node is being automatically cleaned to prepare it for provisioning. """

UNDEPLOY = 'undeploy'
""" Node tear down process has started.

This is an alias for DELETED.
"""

CLEANWAIT = 'clean wait'
""" Node is waiting for a clean step to be finished.

This will be the node's `provision_state` while the node is waiting for
the driver to finish a cleaning step.
"""

CLEANFAIL = 'clean failed'
""" Node failed cleaning. This requires operator intervention to resolve. """

CLEANHOLD = 'clean hold'
""" Node is a holding state due to a clean step. """

ERROR = 'error'
""" An error occurred during node processing.

The `last_error` attribute of the node details should contain an error message.
"""

REBUILD = 'rebuild'
""" Node is to be rebuilt.

This is not used as a state, but rather as a "verb" when changing the node's
provision_state via the REST API.
"""

INSPECTING = 'inspecting'
""" Node is under inspection.

This is the provision state used when inspection is started. A successfully
inspected node shall transition to MANAGEABLE state. For asynchronous
inspection, node shall transition to INSPECTWAIT state.
"""

INSPECTFAIL = 'inspect failed'
""" Node inspection failed. """

INSPECTWAIT = 'inspect wait'
""" Node is under inspection.

This is the provision state used when an asynchronous inspection is in
progress. A successfully inspected node shall transition to MANAGEABLE state.
"""

ADOPTING = 'adopting'
""" Node is being adopted.

This provision state is intended for use to move a node from MANAGEABLE to
ACTIVE state to permit designation of nodes as being "managed" by Ironic,
however "deployed" previously by external means.
"""

ADOPTFAIL = 'adopt failed'
""" Node failed to complete the adoption process.

This state is the resulting state of a node that failed to complete adoption,
potentially due to invalid or incompatible information being defined for the
node.
"""

RESCUE = 'rescue'
""" Node is in rescue mode. """

RESCUEFAIL = 'rescue failed'
""" Node rescue failed. """

RESCUEWAIT = 'rescue wait'
""" Node is waiting on an external callback.

This will be the node `provision_state` while the node is waiting for
the driver to finish rescuing the node.
"""

RESCUING = 'rescuing'
""" Node is in process of being rescued. """

UNRESCUEFAIL = 'unrescue failed'
""" Node unrescue failed. """

UNRESCUING = 'unrescuing'
""" Node is being restored from rescue mode (to active state). """

SERVICE = 'service'
""" Node is being requested to be modified through a service step. """

SERVICING = 'servicing'
""" Node is actively being changed by a service step. """

SERVICEWAIT = 'service wait'
""" Node is waiting for an operation to complete. """

SERVICEFAIL = 'service failed'
""" Node has failed in a service step execution. """

SERVICEHOLD = 'service hold'
""" Node is being held for direct intervention from a service step. """


"""All Node states related to servicing."""
SERVICING_STATES = frozenset((SERVICING, SERVICEWAIT,
                              SERVICEFAIL, SERVICEHOLD))


# NOTE(kaifeng): INSPECTING is allowed to keep backwards compatibility,
# starting from API 1.39 node update is disallowed in this state.
UPDATE_ALLOWED_STATES = (DEPLOYFAIL, INSPECTING, INSPECTFAIL, INSPECTWAIT,
                         CLEANFAIL, ERROR, VERIFYING, ADOPTFAIL, RESCUEFAIL,
                         UNRESCUEFAIL, SERVICE, SERVICEHOLD, SERVICEFAIL)
"""Transitional states in which we allow updating a node."""

DELETE_ALLOWED_STATES = (MANAGEABLE, ENROLL, ADOPTFAIL)
"""States in which node deletion is allowed."""

STABLE_STATES = (ENROLL, MANAGEABLE, AVAILABLE, ACTIVE, ERROR, RESCUE)
"""States that will not transition unless receiving a request."""

UNSTABLE_STATES = (DEPLOYING, DEPLOYWAIT, CLEANING, CLEANWAIT, VERIFYING,
                   DELETING, INSPECTING, INSPECTWAIT, ADOPTING, RESCUING,
                   RESCUEWAIT, UNRESCUING, SERVICING, SERVICEWAIT)
"""States that can be changed without external request."""

STUCK_STATES_TREATED_AS_FAIL = (DEPLOYING, CLEANING, VERIFYING, INSPECTING,
                                ADOPTING, RESCUING, UNRESCUING, DELETING,
                                SERVICING)
"""States that cannot be resumed once a conductor dies.

If a node gets stuck with one of these states for some reason
(eg. conductor goes down when executing task), node will be moved
to fail state.
"""

_LOOKUP_ALLOWED_STATES = (DEPLOYING, DEPLOYWAIT, CLEANING, CLEANWAIT,
                          INSPECTING, INSPECTWAIT, RESCUING, RESCUEWAIT)
LOOKUP_ALLOWED_STATES = frozenset(_LOOKUP_ALLOWED_STATES)

"""States when API lookups are normally allowed for nodes."""

_FASTTRACK_LOOKUP_ALLOWED_STATES = (ENROLL, MANAGEABLE, AVAILABLE,
                                    DEPLOYING, DEPLOYWAIT,
                                    CLEANING, CLEANWAIT,
                                    INSPECTING, INSPECTWAIT,
                                    RESCUING, RESCUEWAIT,
                                    SERVICING, SERVICEWAIT,
                                    SERVICEHOLD)
FASTTRACK_LOOKUP_ALLOWED_STATES = frozenset(_FASTTRACK_LOOKUP_ALLOWED_STATES)
"""States where API lookups are permitted with fast track enabled."""

FAILURE_STATES = frozenset((DEPLOYFAIL, CLEANFAIL, INSPECTFAIL,
                            RESCUEFAIL, UNRESCUEFAIL, ADOPTFAIL,
                            SERVICEFAIL))

# NOTE(JayF) This isn't used in Ironic, but is used in Nova as a copy of this
#            file will be proposed into the nova driver.
ALL_STATES = frozenset((ACTIVE, ADOPTFAIL, ADOPTING, AVAILABLE, CLEANFAIL,
    CLEANHOLD, CLEANING, CLEANWAIT, DELETED, DELETING, DEPLOYDONE, DEPLOYFAIL,
    DEPLOYHOLD, DEPLOYING, DEPLOYWAIT, ENROLL, ERROR, INSPECTFAIL, INSPECTING,
    INSPECTWAIT, MANAGEABLE, RESCUE, RESCUEFAIL, RESCUING, RESCUEWAIT,
    SERVICEFAIL, SERVICEHOLD, SERVICING, SERVICEWAIT, UNRESCUEFAIL,
    UNRESCUING, VERIFYING))  # noqa

##############
# Power states
##############

POWER_ON = 'power on'
""" Node is powered on. """

POWER_OFF = 'power off'
""" Node is powered off. """

REBOOT = 'rebooting'
""" Node is rebooting. """

SOFT_REBOOT = 'soft rebooting'
""" Node is rebooting gracefully. """

SOFT_POWER_OFF = 'soft power off'
""" Node is in the process of soft power off. """

###################
# Allocation states
###################

ALLOCATING = 'allocating'

# States ERROR and ACTIVE are reused.

###########################
# History Event State Types
###########################

PROVISIONING = "provisioning"
TAKEOVER = "takeover"
INTROSPECTION = "introspection"
CONDUCTOR = "conductor"
TRANSITION = "transition"
STARTFAIL = "startup failure"
UNPROVISION = "unprovision"
ADOPTION = "adoption"
CONSOLE = "console"
MONITORING = "monitoring"
VERIFY = "verify"
