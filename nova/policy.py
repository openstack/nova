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

"""Policy Engine For Nova"""

import os.path

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import policy
from nova import utils


policy_opts = [
    cfg.StrOpt('policy_file',
               default='policy.json',
               help=_('JSON file representing policy')),
    cfg.StrOpt('policy_default_rule',
               default='default',
               help=_('Rule checked when requested rule is not found')),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(policy_opts)

_POLICY_PATH = None
_POLICY_CACHE = {}


def reset():
    global _POLICY_PATH
    global _POLICY_CACHE
    _POLICY_PATH = None
    _POLICY_CACHE = {}
    policy.reset()


def init():
    global _POLICY_PATH
    global _POLICY_CACHE
    if not _POLICY_PATH:
        _POLICY_PATH = FLAGS.policy_file
        if not os.path.exists(_POLICY_PATH):
            _POLICY_PATH = FLAGS.find_file(_POLICY_PATH)
        if not _POLICY_PATH:
            raise exception.ConfigNotFound(path=FLAGS.policy_file)
    utils.read_cached_file(_POLICY_PATH, _POLICY_CACHE,
                           reload_func=_set_brain)


def _set_brain(data):
    default_rule = FLAGS.policy_default_rule
    policy.set_brain(policy.Brain.load_json(data, default_rule))


def enforce(context, action, target):
    """Verifies that the action is valid on the target in this context.

       :param context: nova context
       :param action: string representing the action to be checked
           this should be colon separated for clarity.
           i.e. ``compute:create_instance``,
           ``compute:attach_volume``,
           ``volume:attach_volume``

       :param object: dictionary representing the object of the action
           for object creation this should be a dictionary representing the
           location of the object e.g. ``{'project_id': context.project_id}``

       :raises nova.exception.PolicyNotAllowed: if verification fails.

    """
    init()

    match_list = ('rule:%s' % action,)
    credentials = context.to_dict()

    # NOTE(vish): This is to work around the following launchpad bug:
    #             https://bugs.launchpad.net/openstack-common/+bug/1039132
    #             It can be removed when that bug is fixed.
    credentials['is_admin'] = unicode(credentials['is_admin'])

    policy.enforce(match_list, target, credentials,
                   exception.PolicyNotAuthorized, action=action)


def check_is_admin(roles):
    """Whether or not roles contains 'admin' role according to policy setting.

    """
    init()

    action = 'context_is_admin'
    match_list = ('rule:%s' % action,)
    target = {}
    credentials = {'roles': roles}

    try:
        policy.enforce(match_list, target, credentials,
                       exception.PolicyNotAuthorized, action=action)
    except exception.PolicyNotAuthorized:
        return False

    return True
