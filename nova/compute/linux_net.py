# vim: tabstop=4 shiftwidth=4 softtabstop=4

import signal
import os
import nova.utils
import subprocess

# todo(ja): does the definition of network_path belong here?

from nova import flags
FLAGS=flags.FLAGS

def execute(cmd):
    if FLAGS.fake_network:
        print "FAKE NET: %s" % cmd
        return "fake", 0
    else:
        nova.utils.execute(cmd)

def runthis(desc, cmd):
    if FLAGS.fake_network:
        execute(cmd)
    else:
        nova.utils.runthis(desc,cmd)

def Popen(cmd):
    if FLAGS.fake_network:
        execute(' '.join(cmd))
    else:
        subprocess.Popen(cmd)


def device_exists(device):
    (out, err) = execute("ifconfig %s" % device)
    return not err

def confirm_rule(cmd):
    execute("sudo iptables --delete %s" % (cmd))
    execute("sudo iptables -I %s" % (cmd))

def remove_rule(cmd):
    execute("sudo iptables --delete %s" % (cmd))

def bind_public_ip(ip, interface):
    runthis("Binding IP to interface: %s", "sudo ip addr add %s dev %s" % (ip, interface))

def vlan_create(net):
    """ create a vlan on on a bridge device unless vlan already exists """
    if not device_exists("vlan%s" % net.vlan):
        execute("sudo vconfig set_name_type VLAN_PLUS_VID_NO_PAD")
        execute("sudo vconfig add %s %s" % (net.bridge_dev, net.vlan))
        execute("sudo ifconfig vlan%s up" % (net.vlan))

def bridge_create(net):
    """ create a bridge on a vlan unless it already exists """
    if not device_exists(net.bridge_name):
        execute("sudo brctl addbr %s" % (net.bridge_name))
        # execute("sudo brctl setfd %s 0" % (net.bridge_name))
        # execute("sudo brctl setageing %s 10" % (net.bridge_name))
        execute("sudo brctl stp %s off" % (net.bridge_name))
        execute("sudo brctl addif %s vlan%s" % (net.bridge_name, net.vlan))
        if net.bridge_gets_ip:
            execute("sudo ifconfig %s %s broadcast %s netmask %s up" % \
                (net.bridge_name, net.gateway, net.broadcast, net.netmask))
            confirm_rule("FORWARD --in-interface %s -j ACCEPT" % (net.bridge_name))
        else:
            execute("sudo ifconfig %s up" % net.bridge_name)

def dnsmasq_cmd(net):
    cmd = ['sudo dnsmasq',
        ' --strict-order',
        ' --bind-interfaces',
        ' --conf-file=',
        ' --pid-file=%s' % dhcp_file(net.vlan, 'pid'),
        ' --listen-address=%s' % net.dhcp_listen_address,
        ' --except-interface=lo',
        ' --dhcp-range=%s,%s,120s' % (net.dhcp_range_start, net.dhcp_range_end),
        ' --dhcp-lease-max=61',
        ' --dhcp-hostsfile=%s' % dhcp_file(net.vlan, 'conf'),
        ' --dhcp-leasefile=%s' % dhcp_file(net.vlan, 'leases')]
    return ''.join(cmd)

def hostDHCP(network, host):
    idx = host['address'].split(".")[-1] # Logically, the idx of instances they've launched in this net
    return "%s,%s-%s-%s.novalocal,%s" % \
        (host['mac'], host['user_id'], network.vlan, idx, host['address'])

# todo(ja): if the system has restarted or pid numbers have wrapped
#           then you cannot be certain that the pid refers to the
#           dnsmasq.  As well, sending a HUP only reloads the hostfile,
#           so any configuration options (like dchp-range, vlan, ...)
#           aren't reloaded
def start_dnsmasq(network):
    """ (re)starts a dnsmasq server for a given network

    if a dnsmasq instance is already running then send a HUP
    signal causing it to reload, otherwise spawn a new instance
    """
    with open(dhcp_file(network.vlan, 'conf'), 'w') as f:
        for host_name in network.hosts:
            f.write("%s\n" % hostDHCP(network, network.hosts[host_name]))

    pid = dnsmasq_pid_for(network)

    # if dnsmasq is already running, then tell it to reload
    if pid:
        # todo(ja): use "/proc/%d/cmdline" % (pid) to determine if pid refers
        #           correct dnsmasq process
        try:
            os.kill(pid, signal.SIGHUP)
            return
        except Exception, e:
            logging.debug("Killing dnsmasq threw %s", e)

    # otherwise delete the existing leases file and start dnsmasq
    lease_file = dhcp_file(network.vlan, 'leases')
    if os.path.exists(lease_file):
        os.unlink(lease_file)

    Popen(dnsmasq_cmd(network).split(" "))

def stop_dnsmasq(network):
    """ stops the dnsmasq instance for a given network """
    pid = dnsmasq_pid_for(network)

    if pid:
        os.kill(pid, signal.SIGTERM)

def dhcp_file(vlan, kind):
    """ return path to a pid, leases or conf file for a vlan """

    return os.path.abspath("%s/nova-%s.%s" % (FLAGS.networks_path, vlan, kind))

def dnsmasq_pid_for(network):
    """ the pid for prior dnsmasq instance for a vlan,
    returns None if no pid file exists

    if machine has rebooted pid might be incorrect (caller should check)
    """

    pid_file = dhcp_file(network.vlan, 'pid')

    if os.path.exists(pid_file):
        with open(pid_file, 'r') as f:
            return int(f.read())

