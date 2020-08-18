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

import netaddr
from neutronclient.common import exceptions as n_exc
from neutronclient.neutron import v2_0 as neutronv20
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import netutils
from oslo_utils import uuidutils
import six
from six.moves import urllib
from webob import exc

from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.network import neutron as neutronapi
from nova.objects import security_group as security_group_obj
from nova import utils


LOG = logging.getLogger(__name__)

# NOTE: Neutron client has a max URL length of 8192, so we have
# to limit the number of IDs we include in any single search.  Really
# doesn't seem to be any point in making this a config value.
MAX_SEARCH_IDS = 150


def validate_id(id):
    if not uuidutils.is_uuid_like(id):
        msg = _("Security group id should be uuid")
        raise exception.Invalid(msg)
    return id


def validate_name(
        context: nova_context.RequestContext,
        name: str):
    """Validate a security group name and return the corresponding UUID.

    :param context: The nova request context.
    :param name: The name of the security group.
    :raises NoUniqueMatch: If there is no unique match for the provided name.
    :raises SecurityGroupNotFound: If there's no match for the provided name.
    :raises NeutronClientException: For all other exceptions.
    """
    neutron = neutronapi.get_client(context)
    try:
        return neutronv20.find_resourceid_by_name_or_id(
            neutron, 'security_group', name, context.project_id)
    except n_exc.NeutronClientNoUniqueMatch as e:
        raise exception.NoUniqueMatch(six.text_type(e))
    except n_exc.NeutronClientException as e:
        if e.status_code == 404:
            LOG.debug('Neutron security group %s not found', name)
            raise exception.SecurityGroupNotFound(six.text_type(e))
        else:
            LOG.error('Neutron Error: %s', e)
            raise e


def parse_cidr(cidr):
    if not cidr:
        return '0.0.0.0/0'

    try:
        cidr = encodeutils.safe_decode(urllib.parse.unquote(cidr))
    except Exception:
        raise exception.InvalidCidr(cidr=cidr)

    if not netutils.is_valid_cidr(cidr):
        raise exception.InvalidCidr(cidr=cidr)

    return cidr


def new_group_ingress_rule(grantee_group_id, protocol, from_port,
                           to_port):
    return _new_ingress_rule(
        protocol, from_port, to_port, group_id=grantee_group_id)


def new_cidr_ingress_rule(grantee_cidr, protocol, from_port, to_port):
    return _new_ingress_rule(
        protocol, from_port, to_port, cidr=grantee_cidr)


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
        elif (ip_proto_upper in ['TCP', 'UDP'] and from_port is None and
              to_port is None):
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


def create_security_group_rule(context, security_group, new_rule):
    if _rule_exists(security_group, new_rule):
        msg = (_('This rule already exists in group %s') %
               new_rule['parent_group_id'])
        raise exception.Invalid(msg)

    return add_rules(context, new_rule['parent_group_id'],
                     security_group['name'],
                     [new_rule])[0]


def _rule_exists(security_group, new_rule):
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


def validate_property(value, property, allowed):
    """Validate given security group property.

    :param value:    the value to validate, as a string or unicode
    :param property: the property, either 'name' or 'description'
    :param allowed:  the range of characters allowed, but not used because
                     Neutron is allowing any characters.
    """
    utils.check_string_length(value, name=property, min_length=0,
                              max_length=255)


def populate_security_groups(security_groups):
    """Build and return a SecurityGroupList.

    :param security_groups: list of requested security group names or uuids
    :type security_groups: list
    :returns: nova.objects.security_group.SecurityGroupList
    """
    if not security_groups:
        # Make sure it's an empty SecurityGroupList and not None
        return security_group_obj.SecurityGroupList()
    return security_group_obj.make_secgroup_list(security_groups)


def create_security_group(context, name, description):
    neutron = neutronapi.get_client(context)
    body = _make_neutron_security_group_dict(name, description)
    try:
        security_group = neutron.create_security_group(
            body).get('security_group')
    except n_exc.BadRequest as e:
        raise exception.Invalid(six.text_type(e))
    except n_exc.NeutronClientException as e:
        LOG.exception("Neutron Error creating security group %s", name)
        if e.status_code == 401:
            # TODO(arosen) Cannot raise generic response from neutron here
            # as this error code could be related to bad input or over
            # quota
            raise exc.HTTPBadRequest()
        elif e.status_code == 409:
            raise exception.SecurityGroupLimitExceeded(six.text_type(e))
        raise e
    return _convert_to_nova_security_group_format(security_group)


def update_security_group(context, security_group, name, description):
    neutron = neutronapi.get_client(context)
    body = _make_neutron_security_group_dict(name, description)
    try:
        security_group = neutron.update_security_group(
            security_group['id'], body).get('security_group')
    except n_exc.NeutronClientException as e:
        LOG.exception("Neutron Error updating security group %s", name)
        if e.status_code == 401:
            # TODO(arosen) Cannot raise generic response from neutron here
            # as this error code could be related to bad input or over
            # quota
            raise exc.HTTPBadRequest()
        raise e
    return _convert_to_nova_security_group_format(security_group)


def _convert_to_nova_security_group_format(security_group):
    nova_group = {}
    nova_group['id'] = security_group['id']
    nova_group['description'] = security_group['description']
    nova_group['name'] = security_group['name']
    nova_group['project_id'] = security_group['tenant_id']
    nova_group['rules'] = []
    for rule in security_group.get('security_group_rules', []):
        if rule['direction'] == 'ingress':
            nova_group['rules'].append(
                _convert_to_nova_security_group_rule_format(rule))

    return nova_group


def _convert_to_nova_security_group_rule_format(rule):
    nova_rule = {}
    nova_rule['id'] = rule['id']
    nova_rule['parent_group_id'] = rule['security_group_id']
    nova_rule['protocol'] = rule['protocol']
    if (nova_rule['protocol'] and rule.get('port_range_min') is None and
            rule.get('port_range_max') is None):
        if rule['protocol'].upper() in ['TCP', 'UDP']:
            nova_rule['from_port'] = 1
            nova_rule['to_port'] = 65535
        else:
            nova_rule['from_port'] = -1
            nova_rule['to_port'] = -1
    else:
        nova_rule['from_port'] = rule.get('port_range_min')
        nova_rule['to_port'] = rule.get('port_range_max')
    nova_rule['group_id'] = rule['remote_group_id']
    nova_rule['cidr'] = parse_cidr(rule.get('remote_ip_prefix'))
    return nova_rule


def get(context, id):
    neutron = neutronapi.get_client(context)
    try:
        group = neutron.show_security_group(id).get('security_group')
        return _convert_to_nova_security_group_format(group)
    except n_exc.NeutronClientException as e:
        if e.status_code == 404:
            LOG.debug('Neutron security group %s not found', id)
            raise exception.SecurityGroupNotFound(six.text_type(e))
        else:
            LOG.error("Neutron Error: %s", e)
            raise e


def list(context, project, search_opts=None):
    """Returns list of security group rules owned by tenant."""
    neutron = neutronapi.get_client(context)
    params = {}
    search_opts = search_opts if search_opts else {}

    # NOTE(jeffrey4l): list all the security groups when following
    # conditions are met
    #   * names and ids don't exist.
    #   * it is admin context and all_tenants exist in search_opts.
    #   * project is not specified.
    list_all_tenants = (context.is_admin and
                        'all_tenants' in search_opts)
    # NOTE(jeffrey4l): neutron doesn't have `all-tenants` concept.
    # All the security group will be returned if the project/tenant
    # id is not passed.
    if not list_all_tenants:
        params['tenant_id'] = project

    try:
        security_groups = neutron.list_security_groups(**params).get(
            'security_groups')
    except n_exc.NeutronClientException:
        with excutils.save_and_reraise_exception():
            LOG.exception("Neutron Error getting security groups")

    converted_rules = []
    for security_group in security_groups:
        converted_rules.append(
            _convert_to_nova_security_group_format(security_group))

    return converted_rules


def destroy(context, security_group):
    """This function deletes a security group."""

    neutron = neutronapi.get_client(context)
    try:
        neutron.delete_security_group(security_group['id'])
    except n_exc.NeutronClientException as e:
        if e.status_code == 404:
            raise exception.SecurityGroupNotFound(six.text_type(e))
        elif e.status_code == 409:
            raise exception.Invalid(six.text_type(e))
        else:
            LOG.error("Neutron Error: %s", e)
            raise e


def add_rules(context, id, name, vals):
    """Add security group rule(s) to security group.

    Note: the Nova security group API doesn't support adding multiple
    security group rules at once but the EC2 one does. Therefore,
    this function is written to support both. Multiple rules are
    installed to a security group in neutron using bulk support.
    """

    neutron = neutronapi.get_client(context)
    body = _make_neutron_security_group_rules_list(vals)
    try:
        rules = neutron.create_security_group_rule(
            body).get('security_group_rules')
    except n_exc.NeutronClientException as e:
        if e.status_code == 404:
            LOG.exception("Neutron Error getting security group %s", name)
            raise exception.SecurityGroupNotFound(six.text_type(e))
        elif e.status_code == 409:
            LOG.exception("Neutron Error adding rules to security "
                          "group %s", name)
            raise exception.SecurityGroupLimitExceeded(six.text_type(e))
        elif e.status_code == 400:
            LOG.exception("Neutron Error: %s", e)
            raise exception.Invalid(six.text_type(e))
        else:
            raise e
    converted_rules = []
    for rule in rules:
        converted_rules.append(
            _convert_to_nova_security_group_rule_format(rule))
    return converted_rules


def _make_neutron_security_group_dict(name, description):
    return {'security_group': {'name': name,
                               'description': description}}


def _make_neutron_security_group_rules_list(rules):
    new_rules = []
    for rule in rules:
        new_rule = {}
        # nova only supports ingress rules so all rules are ingress.
        new_rule['direction'] = "ingress"
        new_rule['protocol'] = rule.get('protocol')

        # FIXME(arosen) Nova does not expose ethertype on security group
        # rules. Therefore, in the case of self referential rules we
        # should probably assume they want to allow both IPv4 and IPv6.
        # Unfortunately, this would require adding two rules in neutron.
        # The reason we do not do this is because when the user using the
        # nova api wants to remove the rule we'd have to have some way to
        # know that we should delete both of these rules in neutron.
        # For now, self referential rules only support IPv4.
        if not rule.get('cidr'):
            new_rule['ethertype'] = 'IPv4'
        else:
            version = netaddr.IPNetwork(rule.get('cidr')).version
            new_rule['ethertype'] = 'IPv6' if version == 6 else 'IPv4'
        new_rule['remote_ip_prefix'] = rule.get('cidr')
        new_rule['security_group_id'] = rule.get('parent_group_id')
        new_rule['remote_group_id'] = rule.get('group_id')
        if 'from_port' in rule and rule['from_port'] != -1:
            new_rule['port_range_min'] = rule['from_port']
        if 'to_port' in rule and rule['to_port'] != -1:
            new_rule['port_range_max'] = rule['to_port']
        new_rules.append(new_rule)
    return {'security_group_rules': new_rules}


def remove_rules(context, security_group, rule_ids):
    neutron = neutronapi.get_client(context)
    rule_ids = set(rule_ids)
    try:
        # The ec2 api allows one to delete multiple security group rules
        # at once. Since there is no bulk delete for neutron the best
        # thing we can do is delete the rules one by one and hope this
        # works.... :/
        for rule_id in range(0, len(rule_ids)):
            neutron.delete_security_group_rule(rule_ids.pop())
    except n_exc.NeutronClientException:
        with excutils.save_and_reraise_exception():
            LOG.exception("Neutron Error unable to delete %s", rule_ids)


def get_rule(context, id):
    neutron = neutronapi.get_client(context)
    try:
        rule = neutron.show_security_group_rule(
            id).get('security_group_rule')
    except n_exc.NeutronClientException as e:
        if e.status_code == 404:
            LOG.debug("Neutron security group rule %s not found", id)
            raise exception.SecurityGroupNotFound(six.text_type(e))
        else:
            LOG.error("Neutron Error: %s", e)
            raise e
    return _convert_to_nova_security_group_rule_format(rule)


def _get_ports_from_server_list(servers, neutron):
    """Returns a list of ports used by the servers."""

    def _chunk_by_ids(servers, limit):
        ids = []
        for server in servers:
            ids.append(server['id'])
            if len(ids) >= limit:
                yield ids
                ids = []
        if ids:
            yield ids

    # Note: Have to split the query up as the search criteria
    # form part of the URL, which has a fixed max size
    ports = []
    for ids in _chunk_by_ids(servers, MAX_SEARCH_IDS):
        search_opts = {'device_id': ids}
        try:
            ports.extend(neutron.list_ports(**search_opts).get('ports'))
        except n_exc.PortNotFoundClient:
            # There could be a race between deleting an instance and
            # retrieving its port groups from Neutron. In this case
            # PortNotFoundClient is raised and it can be safely ignored
            LOG.debug("Port not found for device with id %s", ids)

    return ports


def _get_secgroups_from_port_list(ports, neutron, fields=None):
    """Returns a dict of security groups keyed by their ids."""

    def _chunk_by_ids(sg_ids, limit):
        sg_id_list = []
        for sg_id in sg_ids:
            sg_id_list.append(sg_id)
            if len(sg_id_list) >= limit:
                yield sg_id_list
                sg_id_list = []
        if sg_id_list:
            yield sg_id_list

    # Find the set of unique SecGroup IDs to search for
    sg_ids = set()
    for port in ports:
        sg_ids.update(port.get('security_groups', []))

    # Note: Have to split the query up as the search criteria
    # form part of the URL, which has a fixed max size
    security_groups = {}
    for sg_id_list in _chunk_by_ids(sg_ids, MAX_SEARCH_IDS):
        sg_search_opts = {'id': sg_id_list}
        if fields:
            sg_search_opts['fields'] = fields
        search_results = neutron.list_security_groups(**sg_search_opts)
        for sg in search_results.get('security_groups'):
            security_groups[sg['id']] = sg

    return security_groups


def get_instances_security_groups_bindings(context, servers,
                                           detailed=False):
    """Returns a dict(instance_id, [security_groups]) to allow obtaining
    all of the instances and their security groups in one shot.
    If detailed is False only the security group name is returned.
    """

    neutron = neutronapi.get_client(context)

    ports = _get_ports_from_server_list(servers, neutron)

    # If detailed is True, we want all fields from the security groups
    # including the potentially slow-to-join security_group_rules field.
    # But if detailed is False, only get the id and name fields since
    # that's all we'll use below.
    fields = None if detailed else ['id', 'name']
    security_groups = _get_secgroups_from_port_list(
        ports, neutron, fields=fields)

    instances_security_group_bindings = {}
    for port in ports:
        for port_sg_id in port.get('security_groups', []):

            # Note:  have to check we found port_sg as its possible
            # the port has an SG that this user doesn't have access to
            port_sg = security_groups.get(port_sg_id)
            if port_sg:
                if detailed:
                    sg_entry = _convert_to_nova_security_group_format(
                        port_sg)
                    instances_security_group_bindings.setdefault(
                        port['device_id'], []).append(sg_entry)
                else:
                    # name is optional in neutron so if not specified
                    # return id
                    name = port_sg.get('name')
                    if not name:
                        name = port_sg.get('id')
                    sg_entry = {'name': name}
                    instances_security_group_bindings.setdefault(
                        port['device_id'], []).append(sg_entry)

    return instances_security_group_bindings


def get_instance_security_groups(context, instance, detailed=False):
    """Returns the security groups that are associated with an instance.
    If detailed is True then it also returns the full details of the
    security groups associated with an instance, otherwise just the
    security group name.
    """
    servers = [{'id': instance.uuid}]
    sg_bindings = get_instances_security_groups_bindings(
                              context, servers, detailed)
    return sg_bindings.get(instance.uuid, [])


def _has_security_group_requirements(port):
    port_security_enabled = port.get('port_security_enabled', True)
    has_ip = port.get('fixed_ips')
    deferred_ip = port.get('ip_allocation') == 'deferred'
    if has_ip or deferred_ip:
        return port_security_enabled
    return False


def add_to_instance(context, instance, security_group_name):
    """Add security group to the instance."""

    neutron = neutronapi.get_client(context)
    try:
        security_group_id = neutronv20.find_resourceid_by_name_or_id(
            neutron, 'security_group',
            security_group_name,
            context.project_id)
    except n_exc.NeutronClientNoUniqueMatch as e:
        raise exception.NoUniqueMatch(six.text_type(e))
    except n_exc.NeutronClientException as e:
        if e.status_code == 404:
            msg = (_("Security group %(name)s is not found for "
                     "project %(project)s") %
                   {'name': security_group_name,
                    'project': context.project_id})
            raise exception.SecurityGroupNotFound(msg)
        else:
            raise e
    params = {'device_id': instance.uuid}
    try:
        ports = neutron.list_ports(**params).get('ports')
    except n_exc.NeutronClientException:
        with excutils.save_and_reraise_exception():
            LOG.exception("Neutron Error:")

    if not ports:
        msg = (_("instance_id %s could not be found as device id on"
               " any ports") % instance.uuid)
        raise exception.SecurityGroupNotFound(msg)

    for port in ports:
        if not _has_security_group_requirements(port):
            LOG.warning("Cannot add security group %(name)s to "
                        "%(instance)s since the port %(port_id)s "
                        "does not meet security requirements",
                        {'name': security_group_name,
                         'instance': instance.uuid,
                         'port_id': port['id']})
            raise exception.SecurityGroupCannotBeApplied()
        if 'security_groups' not in port:
            port['security_groups'] = []
        port['security_groups'].append(security_group_id)
        updated_port = {'security_groups': port['security_groups']}
        try:
            LOG.info("Adding security group %(security_group_id)s to "
                     "port %(port_id)s",
                     {'security_group_id': security_group_id,
                      'port_id': port['id']})
            neutron.update_port(port['id'], {'port': updated_port})
        except n_exc.NeutronClientException as e:
            if e.status_code == 400:
                raise exception.SecurityGroupCannotBeApplied(
                    six.text_type(e))
            else:
                raise e
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Neutron Error:")


def remove_from_instance(context, instance, security_group_name):
    """Remove the security group associated with the instance."""
    neutron = neutronapi.get_client(context)
    try:
        security_group_id = neutronv20.find_resourceid_by_name_or_id(
            neutron, 'security_group',
            security_group_name,
            context.project_id)
    except n_exc.NeutronClientException as e:
        if e.status_code == 404:
            msg = (_("Security group %(name)s is not found for "
                     "project %(project)s") %
                   {'name': security_group_name,
                    'project': context.project_id})
            raise exception.SecurityGroupNotFound(msg)
        else:
            raise e
    params = {'device_id': instance.uuid}
    try:
        ports = neutron.list_ports(**params).get('ports')
    except n_exc.NeutronClientException:
        with excutils.save_and_reraise_exception():
            LOG.exception("Neutron Error:")

    if not ports:
        msg = (_("instance_id %s could not be found as device id on"
               " any ports") % instance.uuid)
        raise exception.SecurityGroupNotFound(msg)

    found_security_group = False
    for port in ports:
        try:
            port.get('security_groups', []).remove(security_group_id)
        except ValueError:
            # When removing a security group from an instance the security
            # group should be on both ports since it was added this way if
            # done through the nova api. In case it is not a 404 is only
            # raised if the security group is not found on any of the
            # ports on the instance.
            continue

        updated_port = {'security_groups': port['security_groups']}
        try:
            LOG.info("Removing security group %(security_group_id)s from "
                     "port %(port_id)s",
                     {'security_group_id': security_group_id,
                      'port_id': port['id']})
            neutron.update_port(port['id'], {'port': updated_port})
            found_security_group = True
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Neutron Error:")
    if not found_security_group:
        msg = (_("Security group %(security_group_name)s not associated "
                 "with the instance %(instance)s") %
               {'security_group_name': security_group_name,
                'instance': instance.uuid})
        raise exception.SecurityGroupNotFound(msg)
