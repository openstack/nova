# Copyright (c) 2013 OpenStack Foundation
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
Helpers for comparing version strings.
"""

import functools
import inspect
import logging

from oslo.config import cfg
import pkg_resources
import six

from nova.openstack.common._i18n import _


LOG = logging.getLogger(__name__)
CONF = cfg.CONF


opts = [
    cfg.BoolOpt('fatal_deprecations',
                default=False,
                help='Enables or disables fatal status of deprecations.'),
]


class deprecated(object):
    """A decorator to mark callables as deprecated.

    This decorator logs a deprecation message when the callable it decorates is
    used. The message will include the release where the callable was
    deprecated, the release where it may be removed and possibly an optional
    replacement.

    Examples:

    1. Specifying the required deprecated release

    >>> @deprecated(as_of=deprecated.ICEHOUSE)
    ... def a(): pass

    2. Specifying a replacement:

    >>> @deprecated(as_of=deprecated.ICEHOUSE, in_favor_of='f()')
    ... def b(): pass

    3. Specifying the release where the functionality may be removed:

    >>> @deprecated(as_of=deprecated.ICEHOUSE, remove_in=+1)
    ... def c(): pass

    4. Specifying the deprecated functionality will not be removed:
    >>> @deprecated(as_of=deprecated.ICEHOUSE, remove_in=0)
    ... def d(): pass

    5. Specifying a replacement, deprecated functionality will not be removed:
    >>> @deprecated(as_of=deprecated.ICEHOUSE, in_favor_of='f()', remove_in=0)
    ... def e(): pass

    """

    # NOTE(morganfainberg): Bexar is used for unit test purposes, it is
    # expected we maintain a gap between Bexar and Folsom in this list.
    BEXAR = 'B'
    FOLSOM = 'F'
    GRIZZLY = 'G'
    HAVANA = 'H'
    ICEHOUSE = 'I'
    JUNO = 'J'
    KILO = 'K'

    _RELEASES = {
        # NOTE(morganfainberg): Bexar is used for unit test purposes, it is
        # expected we maintain a gap between Bexar and Folsom in this list.
        'B': 'Bexar',
        'F': 'Folsom',
        'G': 'Grizzly',
        'H': 'Havana',
        'I': 'Icehouse',
        'J': 'Juno',
        'K': 'Kilo',
    }

    _deprecated_msg_with_alternative = _(
        '%(what)s is deprecated as of %(as_of)s in favor of '
        '%(in_favor_of)s and may be removed in %(remove_in)s.')

    _deprecated_msg_no_alternative = _(
        '%(what)s is deprecated as of %(as_of)s and may be '
        'removed in %(remove_in)s. It will not be superseded.')

    _deprecated_msg_with_alternative_no_removal = _(
        '%(what)s is deprecated as of %(as_of)s in favor of %(in_favor_of)s.')

    _deprecated_msg_with_no_alternative_no_removal = _(
        '%(what)s is deprecated as of %(as_of)s. It will not be superseded.')

    def __init__(self, as_of, in_favor_of=None, remove_in=2, what=None):
        """Initialize decorator

        :param as_of: the release deprecating the callable. Constants
            are define in this class for convenience.
        :param in_favor_of: the replacement for the callable (optional)
        :param remove_in: an integer specifying how many releases to wait
            before removing (default: 2)
        :param what: name of the thing being deprecated (default: the
            callable's name)

        """
        self.as_of = as_of
        self.in_favor_of = in_favor_of
        self.remove_in = remove_in
        self.what = what

    def __call__(self, func_or_cls):
        if not self.what:
            self.what = func_or_cls.__name__ + '()'
        msg, details = self._build_message()

        if inspect.isfunction(func_or_cls):

            @six.wraps(func_or_cls)
            def wrapped(*args, **kwargs):
                report_deprecated_feature(LOG, msg, details)
                return func_or_cls(*args, **kwargs)
            return wrapped
        elif inspect.isclass(func_or_cls):
            orig_init = func_or_cls.__init__

            # TODO(tsufiev): change `functools` module to `six` as
            # soon as six 1.7.4 (with fix for passing `assigned`
            # argument to underlying `functools.wraps`) is released
            # and added to the oslo-incubator requrements
            @functools.wraps(orig_init, assigned=('__name__', '__doc__'))
            def new_init(self, *args, **kwargs):
                report_deprecated_feature(LOG, msg, details)
                orig_init(self, *args, **kwargs)
            func_or_cls.__init__ = new_init
            return func_or_cls
        else:
            raise TypeError('deprecated can be used only with functions or '
                            'classes')

    def _get_safe_to_remove_release(self, release):
        # TODO(dstanek): this method will have to be reimplemented once
        #    when we get to the X release because once we get to the Y
        #    release, what is Y+2?
        new_release = chr(ord(release) + self.remove_in)
        if new_release in self._RELEASES:
            return self._RELEASES[new_release]
        else:
            return new_release

    def _build_message(self):
        details = dict(what=self.what,
                       as_of=self._RELEASES[self.as_of],
                       remove_in=self._get_safe_to_remove_release(self.as_of))

        if self.in_favor_of:
            details['in_favor_of'] = self.in_favor_of
            if self.remove_in > 0:
                msg = self._deprecated_msg_with_alternative
            else:
                # There are no plans to remove this function, but it is
                # now deprecated.
                msg = self._deprecated_msg_with_alternative_no_removal
        else:
            if self.remove_in > 0:
                msg = self._deprecated_msg_no_alternative
            else:
                # There are no plans to remove this function, but it is
                # now deprecated.
                msg = self._deprecated_msg_with_no_alternative_no_removal
        return msg, details


def is_compatible(requested_version, current_version, same_major=True):
    """Determine whether `requested_version` is satisfied by
    `current_version`; in other words, `current_version` is >=
    `requested_version`.

    :param requested_version: version to check for compatibility
    :param current_version: version to check against
    :param same_major: if True, the major version must be identical between
        `requested_version` and `current_version`. This is used when a
        major-version difference indicates incompatibility between the two
        versions. Since this is the common-case in practice, the default is
        True.
    :returns: True if compatible, False if not
    """
    requested_parts = pkg_resources.parse_version(requested_version)
    current_parts = pkg_resources.parse_version(current_version)

    if same_major and (requested_parts[0] != current_parts[0]):
        return False

    return current_parts >= requested_parts


# Track the messages we have sent already. See
# report_deprecated_feature().
_deprecated_messages_sent = {}


def report_deprecated_feature(logger, msg, *args, **kwargs):
    """Call this function when a deprecated feature is used.

    If the system is configured for fatal deprecations then the message
    is logged at the 'critical' level and :class:`DeprecatedConfig` will
    be raised.

    Otherwise, the message will be logged (once) at the 'warn' level.

    :raises: :class:`DeprecatedConfig` if the system is configured for
             fatal deprecations.
    """
    stdmsg = _("Deprecated: %s") % msg
    CONF.register_opts(opts)
    if CONF.fatal_deprecations:
        logger.critical(stdmsg, *args, **kwargs)
        raise DeprecatedConfig(msg=stdmsg)

    # Using a list because a tuple with dict can't be stored in a set.
    sent_args = _deprecated_messages_sent.setdefault(msg, list())

    if args in sent_args:
        # Already logged this message, so don't log it again.
        return

    sent_args.append(args)
    logger.warn(stdmsg, *args, **kwargs)


class DeprecatedConfig(Exception):
    message = _("Fatal call to deprecated config: %(msg)s")

    def __init__(self, msg):
        super(Exception, self).__init__(self.message % dict(msg=msg))
