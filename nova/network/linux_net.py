# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Implements vlans, bridges, and iptables rules using linux utilities.
"""

import os

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils


LOG = logging.getLogger("nova.linux_net")


def _bin_file(script):
    """Return the absolute path to scipt in the bin directory"""
    return os.path.abspath(os.path.join(__file__, "../../../bin", script))


FLAGS = flags.FLAGS
flags.DEFINE_string('dhcpbridge_flagfile',
                    '/etc/nova/nova-dhcpbridge.conf',
                    'location of flagfile for dhcpbridge')
flags.DEFINE_string('dhcp_domain',
                    'novalocal',
                    'domain to use for building the hostnames')

flags.DEFINE_string('networks_path', '$state_path/networks',
                    'Location to keep network config files')
flags.DEFINE_string('public_interface', 'eth0',
                    'Interface for public IP addresses')
flags.DEFINE_string('vlan_interface', 'eth0',
                    'network device for vlans')
flags.DEFINE_string('dhcpbridge', _bin_file('nova-dhcpbridge'),
                        'location of nova-dhcpbridge')
flags.DEFINE_string('routing_source_ip', '$my_ip',
                    'Public IP of network host')
flags.DEFINE_bool('use_nova_chains', False,
                  'use the nova_ routing chains instead of default')
flags.DEFINE_string('input_chain', 'INPUT',
                    'chain to add nova_input to')

flags.DEFINE_string('dns_server', None,
                    'if set, uses specific dns server for dnsmasq')
flags.DEFINE_string('dmz_cidr', '10.128.0.0/24',
                    'dmz range that should be accepted')


def metadata_forward():
    """Create forwarding rule for metadata"""
    _confirm_rule("PREROUTING", '-t', 'nat', '-s', '0.0.0.0/0',
             '-d', '169.254.169.254/32', '-p', 'tcp', '-m', 'tcp',
             '--dport', '80', '-j', 'DNAT',
             '--to-destination',
             '%s:%s' % (FLAGS.ec2_dmz_host, FLAGS.ec2_port))


def init_host():
    """Basic networking setup goes here"""

    if FLAGS.use_nova_chains:
        _execute('sudo', 'iptables', '-N', 'nova_input', check_exit_code=False)
        _execute('sudo', 'iptables', '-D', FLAGS.input_chain,
                 '-j', 'nova_input',
                 check_exit_code=False)
        _execute('sudo', 'iptables', '-A', FLAGS.input_chain,
                 '-j', 'nova_input')
        _execute('sudo', 'iptables', '-N', 'nova_forward',
                 check_exit_code=False)
        _execute('sudo', 'iptables', '-D', 'FORWARD', '-j', 'nova_forward',
                 check_exit_code=False)
        _execute('sudo', 'iptables', '-A', 'FORWARD', '-j', 'nova_forward')
        _execute('sudo', 'iptables', '-N', 'nova_output',
                 check_exit_code=False)
        _execute('sudo', 'iptables', '-D', 'OUTPUT', '-j', 'nova_output',
                 check_exit_code=False)
        _execute('sudo', 'iptables', '-A', 'OUTPUT', '-j', 'nova_output')
        _execute('sudo', 'iptables', '-t', 'nat', '-N', 'nova_prerouting',
                 check_exit_code=False)
        _execute('sudo', 'iptables', '-t', 'nat', '-D', 'PREROUTING',
                 '-j', 'nova_prerouting', check_exit_code=False)
        _execute('sudo', 'iptables', '-t', 'nat', '-A', 'PREROUTING',
                 '-j', 'nova_prerouting')
        _execute('sudo', 'iptables', '-t', 'nat', '-N', 'nova_postrouting',
                 check_exit_code=False)
        _execute('sudo', 'iptables', '-t', 'nat', '-D', 'POSTROUTING',
                 '-j', 'nova_postrouting', check_exit_code=False)
        _execute('sudo', 'iptables', '-t', 'nat', '-A', 'POSTROUTING',
                 '-j', 'nova_postrouting')
        _execute('sudo', 'iptables', '-t', 'nat', '-N', 'nova_snatting',
                 check_exit_code=False)
        _execute('sudo', 'iptables', '-t', 'nat', '-D', 'POSTROUTING',
                 '-j nova_snatting', check_exit_code=False)
        _execute('sudo', 'iptables', '-t', 'nat', '-A', 'POSTROUTING',
                 '-j', 'nova_snatting')
        _execute('sudo', 'iptables', '-t', 'nat', '-N', 'nova_output',
                 check_exit_code=False)
        _execute('sudo', 'iptables', '-t', 'nat', '-D', 'OUTPUT',
                 '-j nova_output', check_exit_code=False)
        _execute('sudo', 'iptables', '-t', 'nat', '-A', 'OUTPUT',
                 '-j', 'nova_output')
    else:
        # NOTE(vish): This makes it easy to ensure snatting rules always
        #             come after the accept rules in the postrouting chain
        _execute('sudo', 'iptables', '-t', 'nat', '-N', 'SNATTING',
                 check_exit_code=False)
        _execute('sudo', 'iptables', '-t', 'nat', '-D', 'POSTROUTING',
                 '-j', 'SNATTING', check_exit_code=False)
        _execute('sudo', 'iptables', '-t', 'nat', '-A', 'POSTROUTING',
                 '-j', 'SNATTING')

    # NOTE(devcamcar): Cloud public SNAT entries and the default
    # SNAT rule for outbound traffic.
    _confirm_rule("SNATTING", '-t', 'nat', '-s', FLAGS.fixed_range,
             '-j', 'SNAT', '--to-source', FLAGS.routing_source_ip,
             append=True)

    _confirm_rule("POSTROUTING", '-t', 'nat', '-s', FLAGS.fixed_range,
                  '-d', FLAGS.dmz_cidr, '-j', 'ACCEPT')
    _confirm_rule("POSTROUTING", '-t', 'nat', '-s', FLAGS.fixed_range,
                  '-d', FLAGS.fixed_range, '-j', 'ACCEPT')


def bind_floating_ip(floating_ip, check_exit_code=True):
    """Bind ip to public interface"""
    _execute('sudo', 'ip', 'addr', 'add', floating_ip,
             'dev', FLAGS.public_interface,
             check_exit_code=check_exit_code)


def unbind_floating_ip(floating_ip):
    """Unbind a public ip from public interface"""
    _execute('sudo', 'ip', 'addr', 'del', floating_ip,
             'dev', FLAGS.public_interface)


def ensure_vlan_forward(public_ip, port, private_ip):
    """Sets up forwarding rules for vlan"""
    _confirm_rule("FORWARD", '-d', private_ip, '-p', 'udp',
                  '--dport', '1194', '-j', 'ACCEPT')
    _confirm_rule("PREROUTING", '-t', 'nat', '-d', public_ip, '-p', 'udp',
                  '--dport', port, '-j', 'DNAT', '--to', '%s:1194'
                  % private_ip)


def ensure_floating_forward(floating_ip, fixed_ip):
    """Ensure floating ip forwarding rule"""
    _confirm_rule("PREROUTING", '-t', 'nat', '-d', floating_ip, '-j', 'DNAT',
                  '--to', fixed_ip)
    _confirm_rule("OUTPUT", '-t', 'nat', '-d', floating_ip, '-j', 'DNAT',
                  '--to', fixed_ip)
    _confirm_rule("SNATTING", '-t', 'nat', '-s', fixed_ip, '-j', 'SNAT',
                  '--to', floating_ip)


def remove_floating_forward(floating_ip, fixed_ip):
    """Remove forwarding for floating ip"""
    _remove_rule("PREROUTING", '-t', 'nat', '-d', floating_ip, '-j', 'DNAT',
                 '--to', fixed_ip)
    _remove_rule("OUTPUT", '-t', 'nat', '-d', floating_ip, '-j', 'DNAT',
                 '--to', fixed_ip)
    _remove_rule("SNATTING", '-t', 'nat', '-s', fixed_ip, '-j', 'SNAT',
                 '--to', floating_ip)


def ensure_vlan_bridge(vlan_num, bridge, net_attrs=None):
    """Create a vlan and bridge unless they already exist"""
    interface = ensure_vlan(vlan_num)
    ensure_bridge(bridge, interface, net_attrs)


def ensure_vlan(vlan_num):
    """Create a vlan unless it already exists"""
    interface = "vlan%s" % vlan_num
    if not _device_exists(interface):
        LOG.debug(_("Starting VLAN inteface %s"), interface)
        _execute('sudo', 'vconfig', 'set_name_type', 'VLAN_PLUS_VID_NO_PAD')
        _execute('sudo', 'vconfig', 'add', FLAGS.vlan_interface, vlan_num)
        _execute('sudo', 'ip', 'link', 'set', interface, 'up')
    return interface


def ensure_bridge(bridge, interface, net_attrs=None):
    """Create a bridge unless it already exists.

    :param interface: the interface to create the bridge on.
    :param net_attrs: dictionary with  attributes used to create the bridge.

    If net_attrs is set, it will add the net_attrs['gateway'] to the bridge
    using net_attrs['broadcast'] and net_attrs['cidr'].  It will also add
    the ip_v6 address specified in net_attrs['cidr_v6'] if use_ipv6 is set.

    The code will attempt to move any ips that already exist on the interface
    onto the bridge and reset the default gateway if necessary.
    """
    if not _device_exists(bridge):
        LOG.debug(_("Starting Bridge interface for %s"), interface)
        _execute('sudo', 'brctl', 'addbr', bridge)
        _execute('sudo', 'brctl', 'setfd', bridge, 0)
        # _execute("sudo brctl setageing %s 10" % bridge)
        _execute('sudo', 'brctl', 'stp', bridge, 'off')
        _execute('sudo', 'ip', 'link', 'set', bridge, up)
    if net_attrs:
        # NOTE(vish): The ip for dnsmasq has to be the first address on the
        #             bridge for it to respond to reqests properly
        suffix = net_attrs['cidr'].rpartition('/')[2]
        out, err = _execute('sudo', 'ip', 'addr', 'add',
                            "%s/%s" %
                            (net_attrs['gateway'], suffix),
                            'brd',
                            net_attrs['broadcast'],
                            'dev',
                            bridge,
                            check_exit_code=False)
        if err and err != "RTNETLINK answers: File exists\n":
            raise exception.Error("Failed to add ip: %s" % err)
        if(FLAGS.use_ipv6):
            _execute('sudo', 'ip', '-f', 'inet6', 'addr',
                     'change', net_attrs['cidr_v6'],
                     'dev', bridge)
        # NOTE(vish): If the public interface is the same as the
        #             bridge, then the bridge has to be in promiscuous
        #             to forward packets properly.
        if(FLAGS.public_interface == bridge):
            _execute('sudo', 'ip', 'link', 'set',
                     'dev', bridge, 'promisc', 'on')
    if interface:
        # NOTE(vish): This will break if there is already an ip on the
        #             interface, so we move any ips to the bridge
        gateway = None
        out, err = _execute('sudo', 'route', '-n')
        for line in out.split("\n"):
            fields = line.split()
            if fields and fields[0] == "0.0.0.0" and fields[-1] == interface:
                gateway = fields[1]
        out, err = _execute('sudo', 'ip', 'addr', 'show', 'dev', interface,
                            'scope', 'global')
        for line in out.split("\n"):
            fields = line.split()
            if fields and fields[0] == "inet":
                params = ' '.join(fields[1:-1])
                _execute('sudo', 'ip', 'addr',
                         'del', params, 'dev', fields[-1])
                _execute('sudo', 'ip', 'addr',
                         'add', params, 'dev', bridge)
        if gateway:
            _execute('sudo', 'route', 'add', '0.0.0.0', 'gw', gateway)
        out, err = _execute('sudo', 'brctl', 'addif', bridge, interface,
                            check_exit_code=False)

        if (err and err != "device %s is already a member of a bridge; can't "
                           "enslave it to bridge %s.\n" % (interface, bridge)):
            raise exception.Error("Failed to add interface: %s" % err)

    if FLAGS.use_nova_chains:
        (out, err) = _execute('sudo', 'iptables', '-N', 'nova_forward',
                              check_exit_code=False)
        if err != 'iptables: Chain already exists.\n':
            # NOTE(vish): chain didn't exist link chain
            _execute('sudo', 'iptables', '-D', 'FORWARD', '-j', 'nova_forward',
                     check_exit_code=False)
            _execute('sudo', 'iptables', '-A', 'FORWARD', '-j', 'nova_forward')

    _confirm_rule("FORWARD", '--in-interface', bridge, '-j', 'ACCEPT')
    _confirm_rule("FORWARD", '--out-interface', bridge, '-j', 'ACCEPT')
    _execute('sudo', 'iptables', '-N', 'nova-local', check_exit_code=False)
    _confirm_rule("FORWARD", '-j', 'nova-local')


def get_dhcp_hosts(context, network_id):
    """Get a string containing a network's hosts config in dnsmasq format"""
    hosts = []
    for fixed_ip_ref in db.network_get_associated_fixed_ips(context,
                                                            network_id):
        hosts.append(_host_dhcp(fixed_ip_ref))
    return '\n'.join(hosts)


# NOTE(ja): Sending a HUP only reloads the hostfile, so any
#           configuration options (like dchp-range, vlan, ...)
#           aren't reloaded.
def update_dhcp(context, network_id):
    """(Re)starts a dnsmasq server for a given network

    if a dnsmasq instance is already running then send a HUP
    signal causing it to reload, otherwise spawn a new instance
    """
    network_ref = db.network_get(context, network_id)

    conffile = _dhcp_file(network_ref['bridge'], 'conf')
    with open(conffile, 'w') as f:
        f.write(get_dhcp_hosts(context, network_id))

    # Make sure dnsmasq can actually read it (it setuid()s to "nobody")
    os.chmod(conffile, 0644)

    pid = _dnsmasq_pid_for(network_ref['bridge'])

    # if dnsmasq is already running, then tell it to reload
    if pid:
        out, _err = _execute('cat', "/proc/%d/cmdline" % pid,
                             check_exit_code=False)
        if conffile in out:
            try:
                _execute('sudo', 'kill', '-HUP', pid)
                return
            except Exception as exc:  # pylint: disable-msg=W0703
                LOG.debug(_("Hupping dnsmasq threw %s"), exc)
        else:
            LOG.debug(_("Pid %d is stale, relaunching dnsmasq"), pid)

    # FLAGFILE and DNSMASQ_INTERFACE in env
    env = {'FLAGFILE': FLAGS.dhcpbridge_flagfile,
           'DNSMASQ_INTERFACE': network_ref['bridge']}
    command = _dnsmasq_cmd(network_ref)
    _execute(command, addl_env=env)


def update_ra(context, network_id):
    network_ref = db.network_get(context, network_id)

    conffile = _ra_file(network_ref['bridge'], 'conf')
    with open(conffile, 'w') as f:
        conf_str = """
interface %s
{
   AdvSendAdvert on;
   MinRtrAdvInterval 3;
   MaxRtrAdvInterval 10;
   prefix %s
   {
        AdvOnLink on;
        AdvAutonomous on;
   };
};
""" % (network_ref['bridge'], network_ref['cidr_v6'])
        f.write(conf_str)

    # Make sure radvd can actually read it (it setuid()s to "nobody")
    os.chmod(conffile, 0644)

    pid = _ra_pid_for(network_ref['bridge'])

    # if radvd is already running, then tell it to reload
    if pid:
        out, _err = _execute('cat', '/proc/%d/cmdline'
                             % pid, check_exit_code=False)
        if conffile in out:
            try:
                _execute('sudo', 'kill', pid)
            except Exception as exc:  # pylint: disable-msg=W0703
                LOG.debug(_("killing radvd threw %s"), exc)
        else:
            LOG.debug(_("Pid %d is stale, relaunching radvd"), pid)
    command = _ra_cmd(network_ref)
    _execute(command)
    db.network_update(context, network_id,
                      {"ra_server":
                       utils.get_my_linklocal(network_ref['bridge'])})


def _host_dhcp(fixed_ip_ref):
    """Return a host string for an address"""
    instance_ref = fixed_ip_ref['instance']
    return "%s,%s.%s,%s" % (instance_ref['mac_address'],
                                   instance_ref['hostname'],
                                   FLAGS.dhcp_domain,
                                   fixed_ip_ref['address'])


def _execute(*cmd, **kwargs):
    """Wrapper around utils._execute for fake_network"""
    if FLAGS.fake_network:
        LOG.debug("FAKE NET: %s", " ".join(map(str, cmd)))
        return "fake", 0
    else:
        return utils.execute(*cmd, **kwargs)


def _device_exists(device):
    """Check if ethernet device exists"""
    (_out, err) = _execute('ip', 'link', 'show', 'dev', device,
                           check_exit_code=False)
    return not err


def _confirm_rule(chain, *cmd, **kwargs):
    append = kwargs.get('append', False)
    """Delete and re-add iptables rule"""
    if FLAGS.use_nova_chains:
        chain = "nova_%s" % chain.lower()
    if append:
        loc = "-A"
    else:
        loc = "-I"
    _execute('sudo', 'iptables', '--delete', chain, *cmd,
             check_exit_code=False)
    _execute('sudo', 'iptables', loc, chain, *cmd)


def _remove_rule(chain, *cmd):
    """Remove iptables rule"""
    if FLAGS.use_nova_chains:
        chain = "%s" % chain.lower()
    _execute('sudo', 'iptables', '--delete', chain, *cmd)


def _dnsmasq_cmd(net):
    """Builds dnsmasq command"""
    cmd = ['sudo -E dnsmasq',
           ' --strict-order',
           ' --bind-interfaces',
           ' --conf-file=',
           ' --domain=%s' % FLAGS.dhcp_domain,
           ' --pid-file=%s' % _dhcp_file(net['bridge'], 'pid'),
           ' --listen-address=%s' % net['gateway'],
           ' --except-interface=lo',
           ' --dhcp-range=%s,static,120s' % net['dhcp_start'],
           ' --dhcp-hostsfile=%s' % _dhcp_file(net['bridge'], 'conf'),
           ' --dhcp-script=%s' % FLAGS.dhcpbridge,
           ' --leasefile-ro']
    if FLAGS.dns_server:
        cmd.append(' -h -R --server=%s' % FLAGS.dns_server)
    return ''.join(cmd)


def _ra_cmd(net):
    """Builds radvd command"""
    cmd = ['sudo -E radvd',
#           ' -u nobody',
           ' -C %s' % _ra_file(net['bridge'], 'conf'),
           ' -p %s' % _ra_file(net['bridge'], 'pid')]
    return ''.join(cmd)


def _stop_dnsmasq(network):
    """Stops the dnsmasq instance for a given network"""
    pid = _dnsmasq_pid_for(network)

    if pid:
        try:
            _execute('sudo', 'kill', '-TERM', pid)
        except Exception as exc:  # pylint: disable-msg=W0703
            LOG.debug(_("Killing dnsmasq threw %s"), exc)


def _dhcp_file(bridge, kind):
    """Return path to a pid, leases or conf file for a bridge"""

    if not os.path.exists(FLAGS.networks_path):
        os.makedirs(FLAGS.networks_path)
    return os.path.abspath("%s/nova-%s.%s" % (FLAGS.networks_path,
                                              bridge,
                                              kind))


def _ra_file(bridge, kind):
    """Return path to a pid or conf file for a bridge"""

    if not os.path.exists(FLAGS.networks_path):
        os.makedirs(FLAGS.networks_path)
    return os.path.abspath("%s/nova-ra-%s.%s" % (FLAGS.networks_path,
                                              bridge,
                                              kind))


def _dnsmasq_pid_for(bridge):
    """Returns the pid for prior dnsmasq instance for a bridge

    Returns None if no pid file exists

    If machine has rebooted pid might be incorrect (caller should check)
    """

    pid_file = _dhcp_file(bridge, 'pid')

    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            return int(f.read())


def _ra_pid_for(bridge):
    """Returns the pid for prior radvd instance for a bridge

    Returns None if no pid file exists

    If machine has rebooted pid might be incorrect (caller should check)
    """

    pid_file = _ra_file(bridge, 'pid')

    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            return int(f.read())
