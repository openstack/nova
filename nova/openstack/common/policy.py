# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack, LLC.
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

"""Common Policy Engine Implementation"""

import logging
import urllib
import urllib2

from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils


LOG = logging.getLogger(__name__)


_BRAIN = None


def set_brain(brain):
    """Set the brain used by enforce().

    Defaults use Brain() if not set.

    """
    global _BRAIN
    _BRAIN = brain


def reset():
    """Clear the brain used by enforce()."""
    global _BRAIN
    _BRAIN = None


def enforce(match_list, target_dict, credentials_dict, exc=None,
            *args, **kwargs):
    """Enforces authorization of some rules against credentials.

    :param match_list: nested tuples of data to match against

        The basic brain supports three types of match lists:

            1) rules

                looks like: ``('rule:compute:get_instance',)``

                Retrieves the named rule from the rules dict and recursively
                checks against the contents of the rule.

            2) roles

                looks like: ``('role:compute:admin',)``

                Matches if the specified role is in credentials_dict['roles'].

            3) generic

                looks like: ``('tenant_id:%(tenant_id)s',)``

                Substitutes values from the target dict into the match using
                the % operator and matches them against the creds dict.

        Combining rules:

            The brain returns True if any of the outer tuple of rules
            match and also True if all of the inner tuples match. You
            can use this to perform simple boolean logic.  For
            example, the following rule would return True if the creds
            contain the role 'admin' OR the if the tenant_id matches
            the target dict AND the the creds contains the role
            'compute_sysadmin':

            ::

                {
                    "rule:combined": (
                        'role:admin',
                        ('tenant_id:%(tenant_id)s', 'role:compute_sysadmin')
                    )
                }

        Note that rule and role are reserved words in the credentials match, so
        you can't match against properties with those names. Custom brains may
        also add new reserved words. For example, the HttpBrain adds http as a
        reserved word.

    :param target_dict: dict of object properties

      Target dicts contain as much information as we can about the object being
      operated on.

    :param credentials_dict: dict of actor properties

      Credentials dicts contain as much information as we can about the user
      performing the action.

    :param exc: exception to raise

      Class of the exception to raise if the check fails.  Any remaining
      arguments passed to enforce() (both positional and keyword arguments)
      will be passed to the exception class.  If exc is not provided, returns
      False.

    :return: True if the policy allows the action
    :return: False if the policy does not allow the action and exc is not set
    """
    global _BRAIN
    if not _BRAIN:
        _BRAIN = Brain()
    if not _BRAIN.check(match_list, target_dict, credentials_dict):
        if exc:
            raise exc(*args, **kwargs)
        return False
    return True


class Brain(object):
    """Implements policy checking."""

    _checks = {}

    @classmethod
    def _register(cls, name, func):
        cls._checks[name] = func

    @classmethod
    def load_json(cls, data, default_rule=None):
        """Init a brain using json instead of a rules dictionary."""
        rules_dict = jsonutils.loads(data)
        return cls(rules=rules_dict, default_rule=default_rule)

    def __init__(self, rules=None, default_rule=None):
        if self.__class__ != Brain:
            LOG.warning(_("Inheritance-based rules are deprecated; use "
                          "the default brain instead of %s.") %
                        self.__class__.__name__)

        self.rules = rules or {}
        self.default_rule = default_rule

    def add_rule(self, key, match):
        self.rules[key] = match

    def _check(self, match, target_dict, cred_dict):
        try:
            match_kind, match_value = match.split(':', 1)
        except Exception:
            LOG.exception(_("Failed to understand rule %(match)r") % locals())
            # If the rule is invalid, fail closed
            return False

        func = None
        try:
            old_func = getattr(self, '_check_%s' % match_kind)
        except AttributeError:
            func = self._checks.get(match_kind, self._checks.get(None, None))
        else:
            LOG.warning(_("Inheritance-based rules are deprecated; update "
                          "_check_%s") % match_kind)
            func = lambda brain, kind, value, target, cred: old_func(value,
                                                                     target,
                                                                     cred)

        if not func:
            LOG.error(_("No handler for matches of kind %s") % match_kind)
            # Fail closed
            return False

        return func(self, match_kind, match_value, target_dict, cred_dict)

    def check(self, match_list, target_dict, cred_dict):
        """Checks authorization of some rules against credentials.

        Detailed description of the check with examples in policy.enforce().

        :param match_list: nested tuples of data to match against
        :param target_dict: dict of object properties
        :param credentials_dict: dict of actor properties

        :returns: True if the check passes

        """
        if not match_list:
            return True
        for and_list in match_list:
            if isinstance(and_list, basestring):
                and_list = (and_list,)
            if all([self._check(item, target_dict, cred_dict)
                    for item in and_list]):
                return True
        return False


class HttpBrain(Brain):
    """A brain that can check external urls for policy.

    Posts json blobs for target and credentials.

    Note that this brain is deprecated; the http check is registered
    by default.
    """

    pass


def register(name, func=None):
    """
    Register a function as a policy check.

    :param name: Gives the name of the check type, e.g., 'rule',
                 'role', etc.  If name is None, a default function
                 will be registered.
    :param func: If given, provides the function to register.  If not
                 given, returns a function taking one argument to
                 specify the function to register, allowing use as a
                 decorator.
    """

    # Perform the actual decoration by registering the function.
    # Returns the function for compliance with the decorator
    # interface.
    def decorator(func):
        # Register the function
        Brain._register(name, func)
        return func

    # If the function is given, do the registration
    if func:
        return decorator(func)

    return decorator


@register("rule")
def _check_rule(brain, match_kind, match, target_dict, cred_dict):
    """Recursively checks credentials based on the brains rules."""
    try:
        new_match_list = brain.rules[match]
    except KeyError:
        if brain.default_rule and match != brain.default_rule:
            new_match_list = ('rule:%s' % brain.default_rule,)
        else:
            return False

    return brain.check(new_match_list, target_dict, cred_dict)


@register("role")
def _check_role(brain, match_kind, match, target_dict, cred_dict):
    """Check that there is a matching role in the cred dict."""
    return match.lower() in [x.lower() for x in cred_dict['roles']]


@register('http')
def _check_http(brain, match_kind, match, target_dict, cred_dict):
    """Check http: rules by calling to a remote server.

    This example implementation simply verifies that the response is
    exactly 'True'. A custom brain using response codes could easily
    be implemented.

    """
    url = 'http:' + (match % target_dict)
    data = {'target': jsonutils.dumps(target_dict),
            'credentials': jsonutils.dumps(cred_dict)}
    post_data = urllib.urlencode(data)
    f = urllib2.urlopen(url, post_data)
    return f.read() == "True"


@register(None)
def _check_generic(brain, match_kind, match, target_dict, cred_dict):
    """Check an individual match.

    Matches look like:

        tenant:%(tenant_id)s
        role:compute:admin

    """

    # TODO(termie): do dict inspection via dot syntax
    match = match % target_dict
    if match_kind in cred_dict:
        return match == unicode(cred_dict[match_kind])
    return False
