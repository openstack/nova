# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Nicira Networks, Inc
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

'''Implement Security Groups abstraction and API.

The nova security_group_handler flag specifies which class is to be used
to implement the security group calls.

The NullSecurityGroupHandler provides a "no-op" plugin that is loaded
by default and has no impact on current system behavior.  In the future,
special purposes classes that inherit from SecurityGroupHandlerBase
will provide enhanced functionality and will be loadable via the
security_group_handler flag.
'''

from nova import log as logging


LOG = logging.getLogger('nova.network.api.quantum.sg')


class SecurityGroupHandlerBase(object):

    def __init__(self):
        raise NotImplementedError()

    def trigger_security_group_create_refresh(self, context, group):
        '''Called when a rule is added to a security_group.

        :param context: the security context.
        :param group: the new group added. group is a dictionary that contains
            the following: user_id, project_id, name, description).'''
        raise NotImplementedError()

    def trigger_security_group_destroy_refresh(self, context,
                                               security_group_id):
        '''Called when a rule is added to a security_group.

        :param context: the security context.
        :param security_group_id: the security group identifier.'''
        raise NotImplementedError()

    def trigger_security_group_rule_create_refresh(self, context,
                                                   rule_ids):
        '''Called when a rule is added to a security_group.

        :param context: the security context.
        :param rule_ids: a list of rule ids that have been affected.'''
        raise NotImplementedError()

    def trigger_security_group_rule_destroy_refresh(self, context,
                                                     rule_ids):
        '''Called when a rule is removed from a security_group.

        :param context: the security context.
        :param rule_ids: a list of rule ids that have been affected.'''
        raise NotImplementedError()

    def trigger_instance_add_security_group_refresh(self, context, instance,
                                                    group_name):
        '''Called when a security group gains a new member.

        :param context: the security context.
        :param instance: the instance to be associated.
        :param group_name: the name of the security group to be associated.'''
        raise NotImplementedError()

    def trigger_instance_remove_security_group_refresh(self, context, instance,
                                                       group_name):
        '''Called when a security group loses a member.

        :param context: the security context.
        :param instance: the instance to be associated.
        :param group_name: the name of the security group to be associated.'''
        raise NotImplementedError()

    def trigger_security_group_members_refresh(self, context, group_ids):
        '''Called when a security group gains or loses a member.

        :param context: the security context.
        :param group_ids: a list of security group identifiers.'''
        raise NotImplementedError()


class NullSecurityGroupHandler(SecurityGroupHandlerBase):

    def __init__(self):
        pass

    def trigger_security_group_create_refresh(self, context, group):
        '''Called when a rule is added to a security_group.

        :param context: the security context.
        :param group: the new group added. group is a dictionary that contains
            the following: user_id, project_id, name, description).'''
        pass

    def trigger_security_group_destroy_refresh(self, context,
                                               security_group_id):
        '''Called when a rule is added to a security_group.

        :param context: the security context.
        :param security_group_id: the security group identifier.'''
        pass

    def trigger_security_group_rule_create_refresh(self, context,
                                                   rule_ids):
        '''Called when a rule is added to a security_group.

        :param context: the security context.
        :param rule_ids: a list of rule ids that have been affected.'''
        pass

    def trigger_security_group_rule_destroy_refresh(self, context,
                                                     rule_ids):
        '''Called when a rule is removed from a security_group.

        :param context: the security context.
        :param rule_ids: a list of rule ids that have been affected.'''
        pass

    def trigger_instance_add_security_group_refresh(self, context, instance,
                                                    group_name):
        '''Called when a security group gains a new member.

        :param context: the security context.
        :param instance: the instance to be associated.
        :param group_name: the name of the security group to be associated.'''
        pass

    def trigger_instance_remove_security_group_refresh(self, context, instance,
                                                       group_name):
        '''Called when a security group loses a member.

        :param context: the security context.
        :param instance: the instance to be associated.
        :param group_name: the name of the security group to be associated.'''
        pass

    def trigger_security_group_members_refresh(self, context, group_ids):
        '''Called when a security group gains or loses a member.

        :param context: the security context.
        :param group_ids: a list of security group identifiers.'''
        pass
