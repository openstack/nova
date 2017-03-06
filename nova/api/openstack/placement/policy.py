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
"""Policy Enforcement for placement API."""

from oslo_config import cfg
from oslo_log import log as logging
from oslo_policy import policy
from oslo_serialization import jsonutils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)
_ENFORCER_PLACEMENT = None


def placement_init():
    """Init an Enforcer class for placement policy.

    This method uses a different list of policies than other parts of Nova.
    This is done to facilitate a split out of the placement service later.
    """
    global _ENFORCER_PLACEMENT
    if not _ENFORCER_PLACEMENT:
        # TODO(cdent): Using is_admin everywhere (except /) is
        # insufficiently flexible for future use case but is
        # convenient for initial exploration. We will need to
        # determine how to manage authorization/policy and
        # implement that, probably per handler.
        rules = policy.Rules.load(jsonutils.dumps({'placement': 'role:admin'}))
        # Enforcer is initialized so that the above rule is loaded in and no
        # policy file is read.
        # TODO(alaski): Register a default rule rather than loading it in like
        # this. That requires that a policy file is specified to be read. When
        # this is split out such that a placement policy file makes sense then
        # change to rule registration.
        _ENFORCER_PLACEMENT = policy.Enforcer(CONF, rules=rules,
                                              use_conf=False)


def placement_authorize(context, action, target=None):
    """Verifies that the action is valid on the target in this context.

       :param context: RequestContext object
       :param action: string representing the action to be checked
       :param target: dictionary representing the object of the action
           for object creation this should be a dictionary representing the
           location of the object e.g. ``{'project_id': context.project_id}``

       :return: returns a non-False value (not necessarily "True") if
           authorized, and the exact value False if not authorized.
    """
    placement_init()
    if target is None:
        target = {'project_id': context.project_id,
                  'user_id': context.user_id}
    credentials = context.to_policy_values()
    # TODO(alaski): Change this to use authorize() when rules are registered.
    # noqa the following line because a hacking check disallows using enforce.
    result = _ENFORCER_PLACEMENT.enforce(action, target, credentials,
                                         do_raise=False, exc=None,
                                         action=action)
    if result is False:
        LOG.debug('Policy check for %(action)s failed with credentials '
                  '%(credentials)s',
                  {'action': action, 'credentials': credentials})
    return result
