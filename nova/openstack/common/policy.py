# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack, LLC.
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
Common Policy Engine Implementation

Policies can be expressed in one of two forms: A list of lists, or a
string written in the new policy language.

In the list-of-lists representation, each check inside the innermost
list is combined as with an "and" conjunction--for that check to pass,
all the specified checks must pass.  These innermost lists are then
combined as with an "or" conjunction.  This is the original way of
expressing policies, but there now exists a new way: the policy
language.

In the policy language, each check is specified the same way as in the
list-of-lists representation: a simple "a:b" pair that is matched to
the correct code to perform that check.  However, conjunction
operators are available, allowing for more expressiveness in crafting
policies.

As an example, take the following rule, expressed in the list-of-lists
representation::

    [["role:admin"], ["project_id:%(project_id)s", "role:projectadmin"]]

In the policy language, this becomes::

    role:admin or (project_id:%(project_id)s and role:projectadmin)

The policy language also has the "not" operator, allowing a richer
policy rule::

    project_id:%(project_id)s and not role:dunce

Finally, two special policy checks should be mentioned; the policy
check "@" will always accept an access, and the policy check "!" will
always reject an access.  (Note that if a rule is either the empty
list ("[]") or the empty string, this is equivalent to the "@" policy
check.)  Of these, the "!" policy check is probably the most useful,
as it allows particular rules to be explicitly disabled.
"""

import abc
import logging
import re
import urllib

import urllib2

from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils


LOG = logging.getLogger(__name__)


_rules = None
_checks = {}


class Rules(dict):
    """
    A store for rules.  Handles the default_rule setting directly.
    """

    @classmethod
    def load_json(cls, data, default_rule=None):
        """
        Allow loading of JSON rule data.
        """

        # Suck in the JSON data and parse the rules
        rules = dict((k, parse_rule(v)) for k, v in
                     jsonutils.loads(data).items())

        return cls(rules, default_rule)

    def __init__(self, rules=None, default_rule=None):
        """Initialize the Rules store."""

        super(Rules, self).__init__(rules or {})
        self.default_rule = default_rule

    def __missing__(self, key):
        """Implements the default rule handling."""

        # If the default rule isn't actually defined, do something
        # reasonably intelligent
        if not self.default_rule or self.default_rule not in self:
            raise KeyError(key)

        return self[self.default_rule]

    def __str__(self):
        """Dumps a string representation of the rules."""

        # Start by building the canonical strings for the rules
        out_rules = {}
        for key, value in self.items():
            # Use empty string for singleton TrueCheck instances
            if isinstance(value, TrueCheck):
                out_rules[key] = ''
            else:
                out_rules[key] = str(value)

        # Dump a pretty-printed JSON representation
        return jsonutils.dumps(out_rules, indent=4)


# Really have to figure out a way to deprecate this
def set_rules(rules):
    """Set the rules in use for policy checks."""

    global _rules

    _rules = rules


# Ditto
def reset():
    """Clear the rules used for policy checks."""

    global _rules

    _rules = None


def check(rule, target, creds, exc=None, *args, **kwargs):
    """
    Checks authorization of a rule against the target and credentials.

    :param rule: The rule to evaluate.
    :param target: As much information about the object being operated
                   on as possible, as a dictionary.
    :param creds: As much information about the user performing the
                  action as possible, as a dictionary.
    :param exc: Class of the exception to raise if the check fails.
                Any remaining arguments passed to check() (both
                positional and keyword arguments) will be passed to
                the exception class.  If exc is not provided, returns
                False.

    :return: Returns False if the policy does not allow the action and
             exc is not provided; otherwise, returns a value that
             evaluates to True.  Note: for rules using the "case"
             expression, this True value will be the specified string
             from the expression.
    """

    # Allow the rule to be a Check tree
    if isinstance(rule, BaseCheck):
        result = rule(target, creds)
    elif not _rules:
        # No rules to reference means we're going to fail closed
        result = False
    else:
        try:
            # Evaluate the rule
            result = _rules[rule](target, creds)
        except KeyError:
            # If the rule doesn't exist, fail closed
            result = False

    # If it is False, raise the exception if requested
    if exc and result is False:
        raise exc(*args, **kwargs)

    return result


class BaseCheck(object):
    """
    Abstract base class for Check classes.
    """

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def __str__(self):
        """
        Retrieve a string representation of the Check tree rooted at
        this node.
        """

        pass

    @abc.abstractmethod
    def __call__(self, target, cred):
        """
        Perform the check.  Returns False to reject the access or a
        true value (not necessary True) to accept the access.
        """

        pass


class FalseCheck(BaseCheck):
    """
    A policy check that always returns False (disallow).
    """

    def __str__(self):
        """Return a string representation of this check."""

        return "!"

    def __call__(self, target, cred):
        """Check the policy."""

        return False


class TrueCheck(BaseCheck):
    """
    A policy check that always returns True (allow).
    """

    def __str__(self):
        """Return a string representation of this check."""

        return "@"

    def __call__(self, target, cred):
        """Check the policy."""

        return True


class Check(BaseCheck):
    """
    A base class to allow for user-defined policy checks.
    """

    def __init__(self, kind, match):
        """
        :param kind: The kind of the check, i.e., the field before the
                     ':'.
        :param match: The match of the check, i.e., the field after
                      the ':'.
        """

        self.kind = kind
        self.match = match

    def __str__(self):
        """Return a string representation of this check."""

        return "%s:%s" % (self.kind, self.match)


class NotCheck(BaseCheck):
    """
    A policy check that inverts the result of another policy check.
    Implements the "not" operator.
    """

    def __init__(self, rule):
        """
        Initialize the 'not' check.

        :param rule: The rule to negate.  Must be a Check.
        """

        self.rule = rule

    def __str__(self):
        """Return a string representation of this check."""

        return "not %s" % self.rule

    def __call__(self, target, cred):
        """
        Check the policy.  Returns the logical inverse of the wrapped
        check.
        """

        return not self.rule(target, cred)


class AndCheck(BaseCheck):
    """
    A policy check that requires that a list of other checks all
    return True.  Implements the "and" operator.
    """

    def __init__(self, rules):
        """
        Initialize the 'and' check.

        :param rules: A list of rules that will be tested.
        """

        self.rules = rules

    def __str__(self):
        """Return a string representation of this check."""

        return "(%s)" % ' and '.join(str(r) for r in self.rules)

    def __call__(self, target, cred):
        """
        Check the policy.  Requires that all rules accept in order to
        return True.
        """

        for rule in self.rules:
            if not rule(target, cred):
                return False

        return True

    def add_check(self, rule):
        """
        Allows addition of another rule to the list of rules that will
        be tested.  Returns the AndCheck object for convenience.
        """

        self.rules.append(rule)
        return self


class OrCheck(BaseCheck):
    """
    A policy check that requires that at least one of a list of other
    checks returns True.  Implements the "or" operator.
    """

    def __init__(self, rules):
        """
        Initialize the 'or' check.

        :param rules: A list of rules that will be tested.
        """

        self.rules = rules

    def __str__(self):
        """Return a string representation of this check."""

        return "(%s)" % ' or '.join(str(r) for r in self.rules)

    def __call__(self, target, cred):
        """
        Check the policy.  Requires that at least one rule accept in
        order to return True.
        """

        for rule in self.rules:
            if rule(target, cred):
                return True

        return False

    def add_check(self, rule):
        """
        Allows addition of another rule to the list of rules that will
        be tested.  Returns the OrCheck object for convenience.
        """

        self.rules.append(rule)
        return self


def _parse_check(rule):
    """
    Parse a single base check rule into an appropriate Check object.
    """

    # Handle the special checks
    if rule == '!':
        return FalseCheck()
    elif rule == '@':
        return TrueCheck()

    try:
        kind, match = rule.split(':', 1)
    except Exception:
        LOG.exception(_("Failed to understand rule %(rule)s") % locals())
        # If the rule is invalid, we'll fail closed
        return FalseCheck()

    # Find what implements the check
    if kind in _checks:
        return _checks[kind](kind, match)
    elif None in _checks:
        return _checks[None](kind, match)
    else:
        LOG.error(_("No handler for matches of kind %s") % kind)
        return FalseCheck()


def _parse_list_rule(rule):
    """
    Provided for backwards compatibility.  Translates the old
    list-of-lists syntax into a tree of Check objects.
    """

    # Empty rule defaults to True
    if not rule:
        return TrueCheck()

    # Outer list is joined by "or"; inner list by "and"
    or_list = []
    for inner_rule in rule:
        # Elide empty inner lists
        if not inner_rule:
            continue

        # Handle bare strings
        if isinstance(inner_rule, basestring):
            inner_rule = [inner_rule]

        # Parse the inner rules into Check objects
        and_list = [_parse_check(r) for r in inner_rule]

        # Append the appropriate check to the or_list
        if len(and_list) == 1:
            or_list.append(and_list[0])
        else:
            or_list.append(AndCheck(and_list))

    # If we have only one check, omit the "or"
    if len(or_list) == 0:
        return FalseCheck()
    elif len(or_list) == 1:
        return or_list[0]

    return OrCheck(or_list)


# Used for tokenizing the policy language
_tokenize_re = re.compile(r'\s+')


def _parse_tokenize(rule):
    """
    Tokenizer for the policy language.

    Most of the single-character tokens are specified in the
    _tokenize_re; however, parentheses need to be handled specially,
    because they can appear inside a check string.  Thankfully, those
    parentheses that appear inside a check string can never occur at
    the very beginning or end ("%(variable)s" is the correct syntax).
    """

    for tok in _tokenize_re.split(rule):
        # Skip empty tokens
        if not tok or tok.isspace():
            continue

        # Handle leading parens on the token
        clean = tok.lstrip('(')
        for i in range(len(tok) - len(clean)):
            yield '(', '('

        # If it was only parentheses, continue
        if not clean:
            continue
        else:
            tok = clean

        # Handle trailing parens on the token
        clean = tok.rstrip(')')
        trail = len(tok) - len(clean)

        # Yield the cleaned token
        lowered = clean.lower()
        if lowered in ('and', 'or', 'not'):
            # Special tokens
            yield lowered, clean
        elif clean:
            # Not a special token, but not composed solely of ')'
            if len(tok) >= 2 and ((tok[0], tok[-1]) in
                                  [('"', '"'), ("'", "'")]):
                # It's a quoted string
                yield 'string', tok[1:-1]
            else:
                yield 'check', _parse_check(clean)

        # Yield the trailing parens
        for i in range(trail):
            yield ')', ')'


class ParseStateMeta(type):
    """
    Metaclass for the ParseState class.  Facilitates identifying
    reduction methods.
    """

    def __new__(mcs, name, bases, cls_dict):
        """
        Create the class.  Injects the 'reducers' list, a list of
        tuples matching token sequences to the names of the
        corresponding reduction methods.
        """

        reducers = []

        for key, value in cls_dict.items():
            if not hasattr(value, 'reducers'):
                continue
            for reduction in value.reducers:
                reducers.append((reduction, key))

        cls_dict['reducers'] = reducers

        return super(ParseStateMeta, mcs).__new__(mcs, name, bases, cls_dict)


def reducer(*tokens):
    """
    Decorator for reduction methods.  Arguments are a sequence of
    tokens, in order, which should trigger running this reduction
    method.
    """

    def decorator(func):
        # Make sure we have a list of reducer sequences
        if not hasattr(func, 'reducers'):
            func.reducers = []

        # Add the tokens to the list of reducer sequences
        func.reducers.append(list(tokens))

        return func

    return decorator


class ParseState(object):
    """
    Implement the core of parsing the policy language.  Uses a greedy
    reduction algorithm to reduce a sequence of tokens into a single
    terminal, the value of which will be the root of the Check tree.

    Note: error reporting is rather lacking.  The best we can get with
    this parser formulation is an overall "parse failed" error.
    Fortunately, the policy language is simple enough that this
    shouldn't be that big a problem.
    """

    __metaclass__ = ParseStateMeta

    def __init__(self):
        """Initialize the ParseState."""

        self.tokens = []
        self.values = []

    def reduce(self):
        """
        Perform a greedy reduction of the token stream.  If a reducer
        method matches, it will be executed, then the reduce() method
        will be called recursively to search for any more possible
        reductions.
        """

        for reduction, methname in self.reducers:
            if (len(self.tokens) >= len(reduction) and
                self.tokens[-len(reduction):] == reduction):
                    # Get the reduction method
                    meth = getattr(self, methname)

                    # Reduce the token stream
                    results = meth(*self.values[-len(reduction):])

                    # Update the tokens and values
                    self.tokens[-len(reduction):] = [r[0] for r in results]
                    self.values[-len(reduction):] = [r[1] for r in results]

                    # Check for any more reductions
                    return self.reduce()

    def shift(self, tok, value):
        """Adds one more token to the state.  Calls reduce()."""

        self.tokens.append(tok)
        self.values.append(value)

        # Do a greedy reduce...
        self.reduce()

    @property
    def result(self):
        """
        Obtain the final result of the parse.  Raises ValueError if
        the parse failed to reduce to a single result.
        """

        if len(self.values) != 1:
            raise ValueError("Could not parse rule")
        return self.values[0]

    @reducer('(', 'check', ')')
    @reducer('(', 'and_expr', ')')
    @reducer('(', 'or_expr', ')')
    def _wrap_check(self, _p1, check, _p2):
        """Turn parenthesized expressions into a 'check' token."""

        return [('check', check)]

    @reducer('check', 'and', 'check')
    def _make_and_expr(self, check1, _and, check2):
        """
        Create an 'and_expr' from two checks joined by the 'and'
        operator.
        """

        return [('and_expr', AndCheck([check1, check2]))]

    @reducer('and_expr', 'and', 'check')
    def _extend_and_expr(self, and_expr, _and, check):
        """
        Extend an 'and_expr' by adding one more check.
        """

        return [('and_expr', and_expr.add_check(check))]

    @reducer('check', 'or', 'check')
    def _make_or_expr(self, check1, _or, check2):
        """
        Create an 'or_expr' from two checks joined by the 'or'
        operator.
        """

        return [('or_expr', OrCheck([check1, check2]))]

    @reducer('or_expr', 'or', 'check')
    def _extend_or_expr(self, or_expr, _or, check):
        """
        Extend an 'or_expr' by adding one more check.
        """

        return [('or_expr', or_expr.add_check(check))]

    @reducer('not', 'check')
    def _make_not_expr(self, _not, check):
        """Invert the result of another check."""

        return [('check', NotCheck(check))]


def _parse_text_rule(rule):
    """
    Translates a policy written in the policy language into a tree of
    Check objects.
    """

    # Empty rule means always accept
    if not rule:
        return TrueCheck()

    # Parse the token stream
    state = ParseState()
    for tok, value in _parse_tokenize(rule):
        state.shift(tok, value)

    try:
        return state.result
    except ValueError:
        # Couldn't parse the rule
        LOG.exception(_("Failed to understand rule %(rule)r") % locals())

        # Fail closed
        return FalseCheck()


def parse_rule(rule):
    """
    Parses a policy rule into a tree of Check objects.
    """

    # If the rule is a string, it's in the policy language
    if isinstance(rule, basestring):
        return _parse_text_rule(rule)
    return _parse_list_rule(rule)


def register(name, func=None):
    """
    Register a function or Check class as a policy check.

    :param name: Gives the name of the check type, e.g., 'rule',
                 'role', etc.  If name is None, a default check type
                 will be registered.
    :param func: If given, provides the function or class to register.
                 If not given, returns a function taking one argument
                 to specify the function or class to register,
                 allowing use as a decorator.
    """

    # Perform the actual decoration by registering the function or
    # class.  Returns the function or class for compliance with the
    # decorator interface.
    def decorator(func):
        _checks[name] = func
        return func

    # If the function or class is given, do the registration
    if func:
        return decorator(func)

    return decorator


@register("rule")
class RuleCheck(Check):
    def __call__(self, target, creds):
        """
        Recursively checks credentials based on the defined rules.
        """

        try:
            return _rules[self.match](target, creds)
        except KeyError:
            # We don't have any matching rule; fail closed
            return False


@register("role")
class RoleCheck(Check):
    def __call__(self, target, creds):
        """Check that there is a matching role in the cred dict."""

        return self.match.lower() in [x.lower() for x in creds['roles']]


@register('http')
class HttpCheck(Check):
    def __call__(self, target, creds):
        """
        Check http: rules by calling to a remote server.

        This example implementation simply verifies that the response
        is exactly 'True'.
        """

        url = ('http:' + self.match) % target
        data = {'target': jsonutils.dumps(target),
                'credentials': jsonutils.dumps(creds)}
        post_data = urllib.urlencode(data)
        f = urllib2.urlopen(url, post_data)
        return f.read() == "True"


@register(None)
class GenericCheck(Check):
    def __call__(self, target, creds):
        """
        Check an individual match.

        Matches look like:

            tenant:%(tenant_id)s
            role:compute:admin
        """

        # TODO(termie): do dict inspection via dot syntax
        match = self.match % target
        if self.kind in creds:
            return match == unicode(creds[self.kind])
        return False
