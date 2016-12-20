# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright 2010 OpenStack Foundation
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
Mapping of bare metal node states.

Setting the node `power_state` is handled by the conductor's power
synchronization thread. Based on the power state retrieved from the driver
for the node, the state is set to POWER_ON or POWER_OFF, accordingly.
Should this fail, the `power_state` value is left unchanged, and the node
is placed into maintenance mode.

The `power_state` can also be set manually via the API. A failure to change
the state leaves the current state unchanged. The node is NOT placed into
maintenance mode in this case.
"""


#####################
# Provisioning states
#####################

NOSTATE = None
""" No state information.

This state is used with power_state to represent a lack of knowledge of
power state, and in target_*_state fields when there is no target.

Prior to the Kilo release, Ironic set node.provision_state to NOSTATE
when the node was available for provisioning. During Kilo cycle, this was
changed to the AVAILABLE state.
"""

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

DELETING = 'deleting'
""" Node is actively being torn down. """

DELETED = 'deleted'
""" Node tear down was successful.

In Juno, target_provision_state was set to this value during node tear down.
In Kilo, this will be a transitory value of provision_state, and never
represented in target_provision_state.
"""

CLEANING = 'cleaning'
""" Node is being automatically cleaned to prepare it for provisioning. """

CLEANWAIT = 'clean wait'
""" Node is waiting for a clean step to be finished.

This will be the node's `provision_state` while the node is waiting for
the driver to finish a cleaning step.
"""

CLEANFAIL = 'clean failed'
""" Node failed cleaning. This requires operator intervention to resolve. """

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
inspected node shall transition to MANAGEABLE status.
"""

INSPECTFAIL = 'inspect failed'
""" Node inspection failed. """


RESCUE = 'rescue'
""" Node is in rescue mode.
This is also used as a "verb" when changing the node's provision_state via the
REST API"""

RESCUEFAIL = 'rescue failed'
""" Node rescue failed. """

RESCUEWAIT = 'rescue wait'
""" Node is waiting for rescue callback. """

RESCUING = 'rescuing'
""" Node is waiting to be rescued. """

UNRESCUE = 'unrescue'
""" Node is to be unrescued.
This is not used as a state, but rather as a "verb" when changing the node's
provision_state via the REST API.
"""

UNRESCUEFAIL = 'unrescue failed'
""" Node unrescue failed. """

UNRESCUING = "unrescuing"
""" Node is unrescuing. """

##############
# Power states
##############

POWER_ON = 'power on'
""" Node is powered on. """

POWER_OFF = 'power off'
""" Node is powered off. """

REBOOT = 'rebooting'
""" Node is rebooting. """

##################
# Helper constants
##################

PROVISION_STATE_LIST = (NOSTATE, MANAGEABLE, AVAILABLE, ACTIVE, DEPLOYWAIT,
                        DEPLOYING, DEPLOYFAIL, DEPLOYDONE, DELETING, DELETED,
                        CLEANING, CLEANWAIT, CLEANFAIL, ERROR, REBUILD,
                        INSPECTING, INSPECTFAIL)
""" A list of all provision states. """
