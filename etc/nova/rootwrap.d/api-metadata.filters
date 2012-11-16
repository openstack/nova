# nova-rootwrap command filters for api-metadata nodes
# This is needed on nova-api hosts running with "metadata" in enabled_apis
# or when running nova-api-metadata
# This file should be owned by (and only-writeable by) the root user

[Filters]
# nova/network/linux_net.py: 'ip[6]tables-save' % (cmd, '-t', ...
iptables-save: CommandFilter, iptables-save, root
ip6tables-save: CommandFilter, ip6tables-save, root

# nova/network/linux_net.py: 'ip[6]tables-restore' % (cmd,)
iptables-restore: CommandFilter, iptables-restore, root
ip6tables-restore: CommandFilter, ip6tables-restore, root
