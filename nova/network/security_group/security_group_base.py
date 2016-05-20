# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
# Copyright 2012 Red Hat, Inc.
# Copyright 2013 Nicira, Inc.
# All Rights Reserved
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

import urllib

from nova import exception
from nova.i18n import _
from nova import utils


class SecurityGroupBase(object):

    def __init__(self, skip_policy_check=False):
        self.skip_policy_check = skip_policy_check

    def parse_cidr(self, cidr):
        if cidr:
            try:
                cidr = urllib.unquote(cidr).decode()
            except Exception as e:
                self.raise_invalid_cidr(cidr, e)

            if not utils.is_valid_cidr(cidr):
                self.raise_invalid_cidr(cidr)

            return cidr
        else:
            return '0.0.0.0/0'

    @staticmethod
    def new_group_ingress_rule(grantee_group_id, protocol, from_port,
                               to_port):
        return SecurityGroupBase._new_ingress_rule(
            protocol, from_port, to_port, group_id=grantee_group_id)

    @staticmethod
    def new_cidr_ingress_rule(grantee_cidr, protocol, from_port, to_port):
        return SecurityGroupBase._new_ingress_rule(
            protocol, from_port, to_port, cidr=grantee_cidr)

    @staticmethod
    def _new_ingress_rule(ip_protocol, from_port, to_port,
                          group_id=None, cidr=None):
        values = {}

        if group_id:
            values['group_id'] = group_id
            # Open everything if an explicit port range or type/code are not
            # specified, but only if a source group was specified.
            ip_proto_upper = ip_protocol.upper() if ip_protocol else ''
            if (ip_proto_upper == 'ICMP' and
                    from_port is None and to_port is None):
                from_port = -1
                to_port = -1
            elif (ip_proto_upper in ['TCP', 'UDP'] and from_port is None
                  and to_port is None):
                from_port = 1
                to_port = 65535

        elif cidr:
            values['cidr'] = cidr

        if ip_protocol and from_port is not None and to_port is not None:

            ip_protocol = str(ip_protocol)
            try:
                # Verify integer conversions
                from_port = int(from_port)
                to_port = int(to_port)
            except ValueError:
                if ip_protocol.upper() == 'ICMP':
                    raise exception.InvalidInput(reason=_("Type and"
                         " Code must be integers for ICMP protocol type"))
                else:
                    raise exception.InvalidInput(reason=_("To and From ports "
                          "must be integers"))

            if ip_protocol.upper() not in ['TCP', 'UDP', 'ICMP']:
                raise exception.InvalidIpProtocol(protocol=ip_protocol)

            # Verify that from_port must always be less than
            # or equal to to_port
            if (ip_protocol.upper() in ['TCP', 'UDP'] and
                    (from_port > to_port)):
                raise exception.InvalidPortRange(from_port=from_port,
                      to_port=to_port, msg="Former value cannot"
                                            " be greater than the later")

            # Verify valid TCP, UDP port ranges
            if (ip_protocol.upper() in ['TCP', 'UDP'] and
                    (from_port < 1 or to_port > 65535)):
                raise exception.InvalidPortRange(from_port=from_port,
                      to_port=to_port, msg="Valid %s ports should"
                                           " be between 1-65535"
                                           % ip_protocol.upper())

            # Verify ICMP type and code
            if (ip_protocol.upper() == "ICMP" and
                (from_port < -1 or from_port > 255 or
                 to_port < -1 or to_port > 255)):
                raise exception.InvalidPortRange(from_port=from_port,
                      to_port=to_port, msg="For ICMP, the"
                                           " type:code must be valid")

            values['protocol'] = ip_protocol
            values['from_port'] = from_port
            values['to_port'] = to_port

        else:
            # If cidr based filtering, protocol and ports are mandatory
            if cidr:
                return None

        return values

    def create_security_group_rule(self, context, security_group, new_rule):
        if self.rule_exists(security_group, new_rule):
            msg = (_('This rule already exists in group %s') %
                   new_rule['parent_group_id'])
            self.raise_group_already_exists(msg)
        return self.add_rules(context, new_rule['parent_group_id'],
                             security_group['name'],
                             [new_rule])[0]

    def rule_exists(self, security_group, new_rule):
        """Indicates whether the specified rule is already
           defined in the given security group.
        """
        for rule in security_group['rules']:
            keys = ('group_id', 'cidr', 'from_port', 'to_port', 'protocol')
            for key in keys:
                if rule.get(key) != new_rule.get(key):
                    break
            else:
                return rule.get('id') or True
        return False

    def validate_property(self, value, property, allowed):
        pass

    def ensure_default(self, context):
        pass

    def trigger_rules_refresh(self, context, id):
        """Called when a rule is added to or removed from a security_group."""
        pass

    def trigger_members_refresh(self, context, group_ids):
        """Called when a security group gains a new or loses a member.

        Sends an update request to each compute node for each instance for
        which this is relevant.
        """
        pass

    def populate_security_groups(self, security_groups):
        """Called when populating the database for an instances
        security groups.
        """
        raise NotImplementedError()

    def create_security_group(self, context, name, description):
        raise NotImplementedError()

    def update_security_group(self, context, security_group,
                              name, description):
        raise NotImplementedError()

    def get(self, context, name=None, id=None, map_exception=False):
        raise NotImplementedError()

    def list(self, context, names=None, ids=None, project=None,
             search_opts=None):
        raise NotImplementedError()

    def destroy(self, context, security_group):
        raise NotImplementedError()

    def add_rules(self, context, id, name, vals):
        raise NotImplementedError()

    def remove_rules(self, context, security_group, rule_ids):
        raise NotImplementedError()

    def get_rule(self, context, id):
        raise NotImplementedError()

    def get_instance_security_groups(self, context, instance, detailed=False):
        raise NotImplementedError()

    def add_to_instance(self, context, instance, security_group_name):
        """Add security group to the instance.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param security_group_name: security group name to add
        """
        raise NotImplementedError()

    def remove_from_instance(self, context, instance, security_group_name):
        """Remove the security group associated with the instance.

        :param context: The request context.
        :param instance: nova.objects.instance.Instance object.
        :param security_group_name: security group name to remove
        """
        raise NotImplementedError()

    @staticmethod
    def raise_invalid_property(msg):
        raise exception.Invalid(msg)

    @staticmethod
    def raise_group_already_exists(msg):
        raise exception.Invalid(msg)

    @staticmethod
    def raise_invalid_group(msg):
        raise exception.Invalid(msg)

    @staticmethod
    def raise_invalid_cidr(cidr, decoding_exception=None):
        raise exception.InvalidCidr(cidr=cidr)

    @staticmethod
    def raise_over_quota(msg):
        raise exception.SecurityGroupLimitExceeded(msg)

    @staticmethod
    def raise_not_found(msg):
        raise exception.SecurityGroupNotFound(msg)
