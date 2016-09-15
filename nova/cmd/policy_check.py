# Copyright 2016 Cloudbase Solutions Srl
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
  CLI interface for nova policy rule commands.
"""

import functools
import os
import sys

from oslo_config import cfg

from nova.cmd import common as cmd_common
import nova.conf
from nova import config
from nova import context as nova_context
from nova import db
from nova import exception
from nova.i18n import _
from nova import policies
from nova import version

CONF = nova.conf.CONF


cli_opts = [
    cfg.ListOpt(
        'os-roles',
        metavar='<auth-roles>',
        default=os.environ.get('OS_ROLES'),
        help=_('Defaults to env[OS_ROLES].')),
    cfg.StrOpt(
        'os-user-id',
        metavar='<auth-user-id>',
        default=os.environ.get('OS_USER_ID'),
        help=_('Defaults to env[OS_USER_ID].')),
    cfg.StrOpt(
        'os-tenant-id',
        metavar='<auth-tenant-id>',
        default=os.environ.get('OS_TENANT_ID'),
        help=_('Defaults to env[OS_TENANT_ID].')),
]


class PolicyCommands(object):
    """Commands for policy rules."""

    _ACCEPTABLE_TARGETS = [
        'project_id', 'user_id', 'quota_class', 'availability_zone',
        'instance_id']

    @cmd_common.args('--api-name', dest='api_name', metavar='<API name>',
                     help='Will return only passing policy rules containing '
                          'the given API name.')
    @cmd_common.args('--target', nargs='+', dest='target', metavar='<Target>',
                     help='Will return only passing policy rules for the '
                          'given target. The available targets are %s. When '
                          '"instance_id" is used, the other targets will be '
                          'overwritten.' % ','.join(_ACCEPTABLE_TARGETS))
    def check(self, api_name=None, target=None):
        """Prints all passing policy rules for the given user.

        :param api_name: If None, all passing policy rules will be printed,
                         otherwise, only passing policies that contain the
                         given api_name in their names.
        :param target: The target against which the policy rule authorization
                       will be tested. If None, the given user will be
                       considered as the target.
        """
        context = self._get_context()
        api_name = api_name or ''
        target = self._get_target(context, target)

        allowed_operations = self._filter_rules(context, api_name, target)

        if allowed_operations:
            print('\n'.join(allowed_operations))
            return 0
        else:
            print('No rules matched or allowed')
            return 1

    def _get_context(self):
        return nova_context.RequestContext(
            roles=CONF.os_roles,
            user_id=CONF.os_user_id,
            project_id=CONF.os_tenant_id)

    def _get_target(self, context, target):
        """Processes and validates the CLI given target and adapts it for
        policy authorization.

        :returns: None if the given target is None, otherwise returns a proper
                  authorization target.
        :raises nova.exception.InvalidAttribute: if a key in the given target
            is not an acceptable.
        :raises nova.exception.InstanceNotFound: if 'instance_id' is given, and
            there is no instance match the id.
        """
        if not target:
            return None

        new_target = {}
        for t in target:
            key, value = t.split('=')
            if key not in self._ACCEPTABLE_TARGETS:
                raise exception.InvalidAttribute(attr=key)
            new_target[key] = value

        # if the target is an instance_id, return an instance instead.
        instance_id = new_target.get('instance_id')
        if instance_id:
            admin_ctxt = nova_context.get_admin_context()
            instance = db.instance_get_by_uuid(admin_ctxt, instance_id)
            new_target = {'user_id': instance['user_id'],
                          'project_id': instance['project_id']}

        return new_target

    def _filter_rules(self, context, api_name, target):
        all_rules = policies.list_rules()
        return [rule.name for rule in all_rules if api_name in rule.name and
                context.can(rule.name, target, fatal=False)]


CATEGORIES = {
    'policy': PolicyCommands,
}


add_command_parsers = functools.partial(cmd_common.add_command_parsers,
                                        categories=CATEGORIES)


category_opt = cfg.SubCommandOpt('category',
                                 title='Command categories',
                                 help='Available categories',
                                 handler=add_command_parsers)


def main():
    """Parse options and call the appropriate class/method."""
    CONF.register_cli_opts(cli_opts)
    CONF.register_cli_opt(category_opt)
    config.parse_args(sys.argv)

    if CONF.category.name == "version":
        print(version.version_string_with_package())
        return 0

    if CONF.category.name == "bash-completion":
        cmd_common.print_bash_completion(CATEGORIES)
        return 0

    try:
        fn, fn_args, fn_kwargs = cmd_common.get_action_fn()
        ret = fn(*fn_args, **fn_kwargs)
        return ret
    except Exception as ex:
        print(_("error: %s") % ex)
        return 1
