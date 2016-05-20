# nova-rootwrap command filters for network nodes
# This file should be owned by (and only-writeable by) the root user

[Filters]
# nova/virt/libvirt/vif.py: 'ip', 'tuntap', 'add', dev, 'mode', 'tap'
# nova/virt/libvirt/vif.py: 'ip', 'link', 'set', dev, 'up'
# nova/virt/libvirt/vif.py: 'ip', 'link', 'delete', dev
# nova/network/linux_net.py: 'ip', 'addr', 'add', str(floating_ip)+'/32'i..
# nova/network/linux_net.py: 'ip', 'addr', 'del', str(floating_ip)+'/32'..
# nova/network/linux_net.py: 'ip', 'addr', 'add', '169.254.169.254/32',..
# nova/network/linux_net.py: 'ip', 'addr', 'show', 'dev', dev, 'scope',..
# nova/network/linux_net.py: 'ip', 'addr', 'del/add', ip_params, dev)
# nova/network/linux_net.py: 'ip', 'addr', 'del', params, fields[-1]
# nova/network/linux_net.py: 'ip', 'addr', 'add', params, bridge
# nova/network/linux_net.py: 'ip', '-f', 'inet6', 'addr', 'change', ..
# nova/network/linux_net.py: 'ip', 'link', 'set', 'dev', dev, 'promisc',..
# nova/network/linux_net.py: 'ip', 'link', 'add', 'link', bridge_if ...
# nova/network/linux_net.py: 'ip', 'link', 'set', interface, address,..
# nova/network/linux_net.py: 'ip', 'link', 'set', interface, 'up'
# nova/network/linux_net.py: 'ip', 'link', 'set', bridge, 'up'
# nova/network/linux_net.py: 'ip', 'addr', 'show', 'dev', interface, ..
# nova/network/linux_net.py: 'ip', 'link', 'set', dev, address, ..
# nova/network/linux_net.py: 'ip', 'link', 'set', dev, 'up'
# nova/network/linux_net.py: 'ip', 'route', 'add', ..
# nova/network/linux_net.py: 'ip', 'route', 'del', .
# nova/network/linux_net.py: 'ip', 'route', 'show', 'dev', dev
ip: CommandFilter, ip, root

# nova/virt/libvirt/vif.py: 'ovs-vsctl', ...
# nova/virt/libvirt/vif.py: 'ovs-vsctl', 'del-port', ...
# nova/network/linux_net.py: 'ovs-vsctl', ....
ovs-vsctl: CommandFilter, ovs-vsctl, root

# nova/network/linux_net.py: 'ovs-ofctl', ....
ovs-ofctl: CommandFilter, ovs-ofctl, root

# nova/virt/libvirt/vif.py: 'ivs-ctl', ...
# nova/virt/libvirt/vif.py: 'ivs-ctl', 'del-port', ...
# nova/network/linux_net.py: 'ivs-ctl', ....
ivs-ctl: CommandFilter, ivs-ctl, root

# nova/virt/libvirt/vif.py: 'ifc_ctl', ...
ifc_ctl: CommandFilter, /opt/pg/bin/ifc_ctl, root

# nova/network/linux_net.py: 'ebtables', '-D' ...
# nova/network/linux_net.py: 'ebtables', '-I' ...
ebtables: CommandFilter, ebtables, root
ebtables_usr: CommandFilter, ebtables, root

# nova/network/linux_net.py: 'ip[6]tables-save' % (cmd, '-t', ...
iptables-save: CommandFilter, iptables-save, root
ip6tables-save: CommandFilter, ip6tables-save, root

# nova/network/linux_net.py: 'ip[6]tables-restore' % (cmd,)
iptables-restore: CommandFilter, iptables-restore, root
ip6tables-restore: CommandFilter, ip6tables-restore, root

# nova/network/linux_net.py: 'arping', '-U', floating_ip, '-A', '-I', ...
# nova/network/linux_net.py: 'arping', '-U', network_ref['dhcp_server'],..
arping: CommandFilter, arping, root

# nova/network/linux_net.py: 'dhcp_release', dev, address, mac_address
dhcp_release: CommandFilter, dhcp_release, root

# nova/network/linux_net.py: 'kill', '-9', pid
# nova/network/linux_net.py: 'kill', '-HUP', pid
kill_dnsmasq: KillFilter, root, /usr/sbin/dnsmasq, -9, -HUP

# nova/network/linux_net.py: 'kill', pid
kill_radvd: KillFilter, root, /usr/sbin/radvd

# nova/network/linux_net.py: dnsmasq call
dnsmasq: EnvFilter, env, root, CONFIG_FILE=, NETWORK_ID=, dnsmasq

# nova/network/linux_net.py: 'radvd', '-C', '%s' % _ra_file(dev, 'conf'..
radvd: CommandFilter, radvd, root

# nova/network/linux_net.py: 'brctl', 'addbr', bridge
# nova/network/linux_net.py: 'brctl', 'setfd', bridge, 0
# nova/network/linux_net.py: 'brctl', 'stp', bridge, 'off'
# nova/network/linux_net.py: 'brctl', 'addif', bridge, interface
brctl: CommandFilter, brctl, root

# nova/network/linux_net.py: 'sysctl', ....
sysctl: CommandFilter, sysctl, root

# nova/network/linux_net.py: 'conntrack'
conntrack: CommandFilter, conntrack, root

# nova/network/linux_net.py: 'fp-vdev'
fp-vdev: CommandFilter, fp-vdev, root
