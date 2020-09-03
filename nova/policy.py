# Copyright (c) 2011 OpenStack Foundation
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

"""Policy Engine For Nova."""
import copy
import re

from oslo_config import cfg
from oslo_log import log as logging
from oslo_policy import opts
from oslo_policy import policy
from oslo_utils import excutils


from nova import exception
from nova import policies


CONF = cfg.CONF
LOG = logging.getLogger(__name__)
_ENFORCER = None
# This list is about the resources which support user based policy enforcement.
# Avoid sending deprecation warning for those resources.
USER_BASED_RESOURCES = ['os-keypairs']
# oslo_policy will read the policy configuration file again when the file
# is changed in runtime so the old policy rules will be saved to
# saved_file_rules and used to compare with new rules to determine the
# rules whether were updated.
saved_file_rules = []
KEY_EXPR = re.compile(r'%\((\w+)\)s')

# TODO(gmann): Remove setting the default value of config policy_file
# once oslo_policy change the default value to 'policy.yaml'.
# https://github.com/openstack/oslo.policy/blob/a626ad12fe5a3abd49d70e3e5b95589d279ab578/oslo_policy/opts.py#L49
DEFAULT_POLICY_FILE = 'policy.yaml'
opts.set_defaults(cfg.CONF, DEFAULT_POLICY_FILE)


def pick_policy_file(policy_file):
    # TODO(gmann): We have changed the default value of
    # CONF.oslo_policy.policy_file option to 'policy.yaml' in Victoria
    # release. To avoid breaking any deployment relying on default
    # value, we need to add this is fallback logic to pick the old default
    # policy file (policy.json) if exist. We can to remove this fallback
    # logic sometime in future.
    if policy_file:
        return policy_file

    if CONF.oslo_policy.policy_file == DEFAULT_POLICY_FILE:
        location = CONF.get_location('policy_file', 'oslo_policy').location
        if CONF.find_file(CONF.oslo_policy.policy_file):
            return CONF.oslo_policy.policy_file
        elif location in [cfg.Locations.opt_default,
                          cfg.Locations.set_default]:
            old_default = 'policy.json'
            if CONF.find_file(old_default):
                return old_default
    # Return overridden value
    return CONF.oslo_policy.policy_file


def reset():
    global _ENFORCER
    if _ENFORCER:
        _ENFORCER.clear()
        _ENFORCER = None


def init(policy_file=None, rules=None, default_rule=None, use_conf=True,
         suppress_deprecation_warnings=False):
    """Init an Enforcer class.

       :param policy_file: Custom policy file to use, if none is specified,
                           `CONF.policy_file` will be used.
       :param rules: Default dictionary / Rules to use. It will be
                     considered just in the first instantiation.
       :param default_rule: Default rule to use, CONF.default_rule will
                            be used if none is specified.
       :param use_conf: Whether to load rules from config file.
       :param suppress_deprecation_warnings: Whether to suppress the
                                             deprecation warnings.
    """

    global _ENFORCER
    global saved_file_rules

    if not _ENFORCER:
        _ENFORCER = policy.Enforcer(
            CONF,
            policy_file=pick_policy_file(policy_file),
            rules=rules,
            default_rule=default_rule,
            use_conf=use_conf)
        # NOTE(gmann): Explictly disable the warnings for policies
        # changing their default check_str. During policy-defaults-refresh
        # work, all the policy defaults have been changed and warning for
        # each policy started filling the logs limit for various tool.
        # Once we move to new defaults only world then we can enable these
        # warning again.
        _ENFORCER.suppress_default_change_warnings = True
        if suppress_deprecation_warnings:
            _ENFORCER.suppress_deprecation_warnings = True
        register_rules(_ENFORCER)
        _ENFORCER.load_rules()

    # Only the rules which are loaded from file may be changed.
    current_file_rules = _ENFORCER.file_rules
    current_file_rules = _serialize_rules(current_file_rules)

    # Checks whether the rules are updated in the runtime
    if saved_file_rules != current_file_rules:
        _warning_for_deprecated_user_based_rules(current_file_rules)
        saved_file_rules = copy.deepcopy(current_file_rules)


def _serialize_rules(rules):
    """Serialize all the Rule object as string which is used to compare the
    rules list.
    """
    result = [(rule_name, str(rule))
              for rule_name, rule in rules.items()]
    return sorted(result, key=lambda rule: rule[0])


def _warning_for_deprecated_user_based_rules(rules):
    """Warning user based policy enforcement used in the rule but the rule
    doesn't support it.
    """
    for rule in rules:
        # We will skip the warning for the resources which support user based
        # policy enforcement.
        if [resource for resource in USER_BASED_RESOURCES
                if resource in rule[0]]:
            continue
        if 'user_id' in KEY_EXPR.findall(rule[1]):
            LOG.warning(
                "The user_id attribute isn't supported in the rule '%s'. "
                "All the user_id based policy enforcement will be removed in "
                "the future.",
                rule[0]
            )


def set_rules(rules, overwrite=True, use_conf=False):
    """Set rules based on the provided dict of rules.

       :param rules: New rules to use. It should be an instance of dict.
       :param overwrite: Whether to overwrite current rules or update them
                         with the new rules.
       :param use_conf: Whether to reload rules from config file.
    """

    init(use_conf=False)
    _ENFORCER.set_rules(rules, overwrite, use_conf)


def authorize(context, action, target=None, do_raise=True, exc=None):
    """Verifies that the action is valid on the target in this context.

       :param context: nova context
       :param action: string representing the action to be checked
           this should be colon separated for clarity.
           i.e. ``compute:create_instance``,
           ``compute:attach_volume``,
           ``volume:attach_volume``
       :param target: dictionary representing the object of the action
           for object creation this should be a dictionary representing the
           location of the object e.g. ``{'project_id': instance.project_id}``
            If None, then this default target will be considered:
            {'project_id': self.project_id, 'user_id': self.user_id}
       :param do_raise: if True (the default), raises PolicyNotAuthorized;
           if False, returns False
       :param exc: Class of the exception to raise if the check fails.
                   Any remaining arguments passed to :meth:`authorize` (both
                   positional and keyword arguments) will be passed to
                   the exception class. If not specified,
                   :class:`PolicyNotAuthorized` will be used.

       :raises nova.exception.PolicyNotAuthorized: if verification fails
           and do_raise is True. Or if 'exc' is specified it will raise an
           exception of that type.

       :return: returns a non-False value (not necessarily "True") if
           authorized, and the exact value False if not authorized and
           do_raise is False.
    """
    init()
    if not exc:
        exc = exception.PolicyNotAuthorized

    # Legacy fallback for emtpy target from context.can()
    # should be removed once we improve testing and scope checks
    if target is None:
        target = default_target(context)

    try:
        result = _ENFORCER.authorize(action, target, context,
                                     do_raise=do_raise, exc=exc, action=action)
    except policy.PolicyNotRegistered:
        with excutils.save_and_reraise_exception():
            LOG.exception('Policy not registered')
    except policy.InvalidScope:
        LOG.debug('Policy check for %(action)s failed with scope check '
                  '%(credentials)s',
                  {'action': action,
                   'credentials': context.to_policy_values()})
        raise exc(action=action)
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.debug('Policy check for %(action)s failed with credentials '
                      '%(credentials)s',
                      {'action': action,
                       'credentials': context.to_policy_values()})
    return result


def default_target(context):
    return {'project_id': context.project_id, 'user_id': context.user_id}


def check_is_admin(context):
    """Whether or not roles contains 'admin' role according to policy setting.

    """

    init()
    # the target is user-self
    target = default_target(context)
    return _ENFORCER.authorize('context_is_admin', target, context)


@policy.register('is_admin')
class IsAdminCheck(policy.Check):
    """An explicit check for is_admin."""

    def __init__(self, kind, match):
        """Initialize the check."""

        self.expected = (match.lower() == 'true')

        super(IsAdminCheck, self).__init__(kind, str(self.expected))

    def __call__(self, target, creds, enforcer):
        """Determine whether is_admin matches the requested value."""

        return creds['is_admin'] == self.expected


def get_rules():
    if _ENFORCER:
        return _ENFORCER.rules


def register_rules(enforcer):
    enforcer.register_defaults(policies.list_rules())


def get_enforcer():
    # This method is used by oslopolicy CLI scripts in order to generate policy
    # files from overrides on disk and defaults in code.
    cfg.CONF([], project='nova')
    init()
    return _ENFORCER


def verify_deprecated_policy(old_policy, new_policy, default_rule, context):
    """Check the rule of the deprecated policy action

    If the current rule of the deprecated policy action is set to a non-default
    value, then a warning message is logged stating that the new policy
    action should be used to dictate permissions as the old policy action is
    being deprecated.

    :param old_policy: policy action that is being deprecated
    :param new_policy: policy action that is replacing old_policy
    :param default_rule: the old_policy action default rule value
    :param context: the nova context
    """

    if _ENFORCER:
        current_rule = str(_ENFORCER.rules[old_policy])
    else:
        current_rule = None

    if current_rule != default_rule:
        LOG.warning("Start using the new action '%(new_policy)s'. "
                    "The existing action '%(old_policy)s' is being deprecated "
                    "and will be removed in future release.",
                    {'new_policy': new_policy, 'old_policy': old_policy})
        context.can(old_policy)
        return True
    else:
        return False
