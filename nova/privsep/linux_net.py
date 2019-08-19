# Copyright 2016 Red Hat, Inc
# Copyright 2017 Rackspace Australia
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
Linux network specific helpers.
"""


import os
import six

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils

from nova import exception
import nova.privsep.linux_net


LOG = logging.getLogger(__name__)


@nova.privsep.sys_admin_pctxt.entrypoint
def add_bridge(bridge):
    """Add a bridge.

    :param bridge: the name of the bridge
    """
    processutils.execute('brctl', 'addbr', bridge)


@nova.privsep.sys_admin_pctxt.entrypoint
def delete_bridge(bridge):
    """Delete a bridge.

    :param bridge: the name of the bridge
    """
    processutils.execute('brctl', 'delbr', bridge)


@nova.privsep.sys_admin_pctxt.entrypoint
def bridge_setfd(bridge):
    processutils.execute('brctl', 'setfd', bridge, 0)


@nova.privsep.sys_admin_pctxt.entrypoint
def bridge_disable_stp(bridge):
    processutils.execute('brctl', 'stp', bridge, 'off')


@nova.privsep.sys_admin_pctxt.entrypoint
def bridge_add_interface(bridge, interface):
    return processutils.execute('brctl', 'addif', bridge, interface,
                                check_exit_code=False)


def device_exists(device):
    """Check if ethernet device exists."""
    return os.path.exists('/sys/class/net/%s' % device)


def delete_net_dev(dev):
    """Delete a network device only if it exists."""
    if device_exists(dev):
        try:
            delete_net_dev_escalated(dev)
            LOG.debug("Net device removed: '%s'", dev)
        except processutils.ProcessExecutionError:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed removing net device: '%s'", dev)


@nova.privsep.sys_admin_pctxt.entrypoint
def delete_net_dev_escalated(dev):
    processutils.execute('ip', 'link', 'delete', dev,
                         check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_mtu(dev, mtu):
    if mtu:
        processutils.execute('ip', 'link', 'set', dev, 'mtu',
                             mtu, check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_enabled(dev):
    _set_device_enabled_inner(dev)


def _set_device_enabled_inner(dev):
    processutils.execute('ip', 'link', 'set', dev, 'up',
                         check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_trust(dev, vf_num, trusted):
    _set_device_trust_inner(dev, vf_num, trusted)


def _set_device_trust_inner(dev, vf_num, trusted):
    processutils.execute('ip', 'link', 'set', dev,
                         'vf', vf_num,
                         'trust', bool(trusted) and 'on' or 'off',
                         check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_disabled(dev):
    processutils.execute('ip', 'link', 'set', dev, 'down')


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_macaddr(dev, mac_addr, port_state=None):
    _set_device_macaddr_inner(dev, mac_addr, port_state=port_state)


def _set_device_macaddr_inner(dev, mac_addr, port_state=None):
    if port_state:
        processutils.execute('ip', 'link', 'set', dev, 'address', mac_addr,
                             port_state, check_exit_code=[0, 2, 254])
    else:
        processutils.execute('ip', 'link', 'set', dev, 'address', mac_addr,
                             check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def set_device_macaddr_and_vlan(dev, vf_num, mac_addr, vlan):
    processutils.execute('ip', 'link', 'set', dev,
                         'vf', vf_num,
                         'mac', mac_addr,
                         'vlan', vlan,
                         run_as_root=True,
                         check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def bind_ip(device, ip, scope_is_link=False):
    if not scope_is_link:
        processutils.execute('ip', 'addr', 'add', str(ip) + '/32',
                             'dev', device, check_exit_code=[0, 2, 254])
    else:
        processutils.execute('ip', 'addr', 'add', str(ip) + '/32',
                             'scope', 'link', 'dev', device,
                             check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def unbind_ip(device, ip):
    processutils.execute('ip', 'addr', 'del', str(ip) + '/32',
                         'dev', device, check_exit_code=[0, 2, 254])


def lookup_ip(device):
    return processutils.execute('ip', 'addr', 'show', 'dev', device,
                                'scope', 'global')


@nova.privsep.sys_admin_pctxt.entrypoint
def change_ip(device, ip):
    processutils.execute('ip', '-f', 'inet6', 'addr', 'change', ip,
                         'dev', device)


# TODO(mikal): this is horrid. The calling code takes arguments from an
# interface list and just regurgitates them here. This isn't good enough,
# but is outside the scope of the privsep transition. Mark it as bonkers and
# hope we clean it up later.
@nova.privsep.sys_admin_pctxt.entrypoint
def address_command_deprecated(device, action, params):
    cmd = ['ip', 'addr', action]
    cmd.extend(params)
    cmd.extend(['dev', device])
    processutils.execute(*cmd, check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def dhcp_release(dev, address, mac_address):
    processutils.execute('dhcp_release', dev, address, mac_address)


def routes_show(dev):
    # Format of output is:
    #     192.168.1.0/24  proto kernel  scope link  src 192.168.1.6
    return processutils.execute('ip', 'route', 'show', 'dev', dev)


# TODO(mikal): this is horrid. The calling code takes arguments from a route
# list and just regurgitates them into new routes. This isn't good enough,
# but is outside the scope of the privsep transition. Mark it as bonkers and
# hope we clean it up later.
@nova.privsep.sys_admin_pctxt.entrypoint
def route_add_deprecated(routes):
    processutils.execute('ip', 'route', 'add', *routes)


@nova.privsep.sys_admin_pctxt.entrypoint
def route_delete(dev, route):
    processutils.execute('ip', 'route', 'del', route, 'dev', dev)


# TODO(mikal): this is horrid. The calling code takes arguments from a route
# list and just regurgitates them into new routes. This isn't good enough,
# but is outside the scope of the privsep transition. Mark it as bonkers and
# hope we clean it up later.
@nova.privsep.sys_admin_pctxt.entrypoint
def route_delete_deprecated(dev, routes):
    processutils.execute('ip', 'route', 'del', *routes)


@nova.privsep.sys_admin_pctxt.entrypoint
def create_tap_dev(dev, mac_address=None, multiqueue=False):
    if not device_exists(dev):
        try:
            # First, try with 'ip'
            cmd = ('ip', 'tuntap', 'add', dev, 'mode', 'tap')
            if multiqueue:
                cmd = cmd + ('multi_queue', )
            processutils.execute(*cmd, check_exit_code=[0, 2, 254])
        except processutils.ProcessExecutionError:
            if multiqueue:
                LOG.warning(
                    'Failed to create a tap device with ip tuntap. '
                    'tunctl does not support creation of multi-queue '
                    'enabled devices, skipping fallback.')
                raise

            # Second option: tunctl
            processutils.execute('tunctl', '-b', '-t', dev)

        if mac_address:
            _set_device_macaddr_inner(dev, mac_address)
        _set_device_enabled_inner(dev)


@nova.privsep.sys_admin_pctxt.entrypoint
def send_arp_for_ip(ip, device, count):
    out, err = processutils.execute(
        'arping', '-U', ip, '-A', '-I', device, '-c', str(count),
        check_exit_code=False)

    if err:
        LOG.debug('arping error for IP %s', ip)


@nova.privsep.sys_admin_pctxt.entrypoint
def clean_conntrack(fixed_ip):
    try:
        processutils.execute('conntrack', '-D', '-r', fixed_ip,
                             check_exit_code=[0, 1])
    except processutils.ProcessExecutionError:
        LOG.exception('Error deleting conntrack entries for %s', fixed_ip)


def enable_ipv4_forwarding():
    if not ipv4_forwarding_check():
        _enable_ipv4_forwarding_inner()


def ipv4_forwarding_check():
    with open('/proc/sys/net/ipv4/ip_forward', 'r') as f:
        return f.readline().strip() == '1'


@nova.privsep.sys_admin_pctxt.entrypoint
def _enable_ipv4_forwarding_inner():
    processutils.execute('sysctl', '-w', 'net.ipv4.ip_forward=1')


@nova.privsep.sys_admin_pctxt.entrypoint
def modify_ebtables(table, rule, insert_rule=True):
    cmd = ['ebtables', '--concurrent', '-t', table]
    if insert_rule:
        cmd.append('-I')
    else:
        cmd.append('-D')
    cmd.extend(rule)

    processutils.execute(*cmd, check_exit_code=[0])


@nova.privsep.sys_admin_pctxt.entrypoint
def add_vlan(bridge_interface, interface, vlan_num):
    processutils.execute('ip', 'link', 'add', 'link', bridge_interface,
                         'name', interface, 'type', 'vlan',
                         'id', vlan_num, check_exit_code=[0, 2, 254])


@nova.privsep.sys_admin_pctxt.entrypoint
def iptables_get_rules(ipv4=True):
    if ipv4:
        cmd = 'iptables'
    else:
        cmd = 'ip6tables'

    return processutils.execute('%s-save' % cmd, '-c', attempts=5)


@nova.privsep.sys_admin_pctxt.entrypoint
def iptables_set_rules(rules, ipv4=True):
    if ipv4:
        cmd = 'iptables'
    else:
        cmd = 'ip6tables'

    processutils.execute('%s-restore' % cmd, '-c',
                         process_input=six.b('\n'.join(rules)),
                         attempts=5)


@nova.privsep.sys_admin_pctxt.entrypoint
def restart_dnsmasq(flag_file, network_ref, config_file, pid_path, opts_path,
                    dhcp_lease_time, lease_max, conf_path, dhcp_bridge,
                    dhcp_domain, dns_servers, hosts_path):
    _restart_dnsmasq_inner(flag_file, network_ref, config_file, pid_path,
                           opts_path, dhcp_lease_time, lease_max, conf_path,
                           dhcp_bridge, dhcp_domain, dns_servers, hosts_path)


# NOTE(mikal): this is done like this to enable unit testing
def _restart_dnsmasq_inner(flag_file, network_ref, config_file, pid_path,
                           opts_path, dhcp_lease_time, lease_max, conf_path,
                           dhcp_bridge, dhcp_domain, dns_servers, hosts_path):
    cmd = ['env',
           'CONFIG_FILE=%s' % flag_file,
           'NETWORK_ID=%s' % str(network_ref['id']),
           'dnsmasq',
           '--strict-order',
           '--bind-interfaces',
           '--conf-file=%s' % config_file,
           '--pid-file=%s' % pid_path,
           '--dhcp-optsfile=%s' % opts_path,
           '--listen-address=%s' % network_ref['dhcp_server'],
           '--except-interface=lo',
           '--dhcp-range=set:%s,%s,static,%s,%ss' %
                         (network_ref['label'],
                          network_ref['dhcp_start'],
                          network_ref['netmask'],
                          dhcp_lease_time),
           '--dhcp-lease-max=%s' % lease_max,
           '--dhcp-hostsfile=%s' % conf_path,
           '--dhcp-script=%s' % dhcp_bridge,
           '--no-hosts',
           '--leasefile-ro']

    # dnsmasq currently gives an error for an empty domain,
    # rather than ignoring.  So only specify it if defined.
    if dhcp_domain:
        cmd.append('--domain=%s' % dhcp_domain)

    if dns_servers:
        cmd.append('--no-resolv')
    for dns_server in dns_servers:
        cmd.append('--server=%s' % dns_server)

    if network_ref['multi_host']:
        cmd.append('--addn-hosts=%s' % hosts_path)

    processutils.execute(*cmd)


@nova.privsep.sys_admin_pctxt.entrypoint
def start_ra(conf_path, pid_path):
    cmd = ['radvd',
           '-C', '%s' % conf_path,
           '-p', '%s' % pid_path]
    processutils.execute(*cmd)


@nova.privsep.sys_admin_pctxt.entrypoint
def ovs_plug(timeout, bridge, dev, mac_address):
    cmd = ['ovs-vsctl', '--timeout=%s' % timeout,
           '--', '--may-exist', 'add-port', bridge, dev,
           '--', 'set', 'Interface', dev, 'type=internal',
           '--', 'set', 'Interface', dev,
           'external-ids:iface-id=%s' % dev,
           '--', 'set', 'Interface', dev,
           'external-ids:iface-status=active',
           '--', 'set', 'Interface', dev,
           'external-ids:attached-mac=%s' % mac_address]
    try:
        processutils.execute(*cmd)
    except Exception as e:
        LOG.error('Unable to execute %(cmd)s. Exception: %(exception)s',
                  {'cmd': cmd, 'exception': e})
        raise exception.OVSConfigurationFailure(inner_exception=e)


@nova.privsep.sys_admin_pctxt.entrypoint
def ovs_drop_nondhcp(bridge, mac_address):
    processutils.execute(
        'ovs-ofctl', 'add-flow', bridge, 'priority=1,actions=drop')
    processutils.execute(
        'ovs-ofctl', 'add-flow', bridge,
        'udp,tp_dst=67,dl_dst=%s,priority=2,actions=normal' % mac_address)


@nova.privsep.sys_admin_pctxt.entrypoint
def ovs_unplug(timeout, bridge, dev):
    cmd = ['ovs-vsctl', '--timeout=%s' % timeout,
           '--', '--if-exists', 'del-port', bridge, dev]
    try:
        processutils.execute(*cmd)
    except Exception as e:
        LOG.error('Unable to execute %(cmd)s. Exception: %(exception)s',
                  {'cmd': cmd, 'exception': e})
        raise exception.OVSConfigurationFailure(inner_exception=e)
