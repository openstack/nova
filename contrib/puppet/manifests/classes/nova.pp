import "kern_module"
import "apt"
import "loopback"

#$head_node_ip = "undef"
#$rabbit_ip = "undef"
#$vpn_ip = "undef"
#$public_interface = "undef"
#$vlan_start = "5000"
#$vlan_end = "6000"
#$private_range = "10.0.0.0/16"
#$public_range = "192.168.177.0/24"

define nova_iptables($services, $ip="", $private_range="", $mgmt_ip="", $dmz_ip="") {
  file { "/etc/init.d/nova-iptables":
    owner => "root", mode => 755,
    source => "puppet://${puppet_server}/files/production/nova-iptables",
  }

  file { "/etc/default/nova-iptables":
    owner => "root", mode => 644,
    content => template("nova-iptables.erb")
  }
}

define nova_conf_pointer($name) {
  file { "/etc/nova/nova-${name}.conf":
    owner => "nova", mode => 400,
    content => "--flagfile=/etc/nova/nova.conf"
  }
}

class novaconf {
  file { "/etc/nova/nova.conf":
    owner => "nova", mode => 400,
    content => template("production/nova-common.conf.erb", "production/nova-${cluster_name}.conf.erb")
  }
  nova_conf_pointer{'manage': name => 'manage'}
}

class novadata {
  package { "rabbitmq-server": ensure => present }

  file { "/etc/rabbitmq/rabbitmq.conf":
    owner => "root", mode => 644,
    content => "NODENAME=rabbit@localhost",
  }

  service { "rabbitmq-server":
    ensure => running,
    enable => true,
    hasstatus => true,
    require => [
      File["/etc/rabbitmq/rabbitmq.conf"],
      Package["rabbitmq-server"]
    ]
  }

  package { "mysql-server": ensure => present }

  file { "/etc/mysql/my.cnf":
    owner => "root", mode => 644,
    source => "puppet://${puppet_server}/files/production/my.cnf",
  }

  service { "mysql":
    ensure => running,
    enable => true,
    hasstatus => true,
    require => [
      File["/etc/mysql/my.cnf"],
      Package["mysql-server"]
    ]
  }

  file { "/root/slap.sh":
    owner => "root", mode => 755,
    source => "puppet://${puppet_server}/files/production/slap.sh",
  }

  file { "/root/setup_data.sh":
    owner => "root", mode => 755,
    source => "puppet://${puppet_server}/files/production/setup_data.sh",
  }

  # setup compute data
  exec { "setup_data":
    command => "/root/setup_data.sh",
    path => "/usr/bin:/bin",
    unless => "test -f /root/installed",
    require => [
      Service["mysql"],
      File["/root/slap.sh"],
      File["/root/setup_data.sh"]
    ]
  }
}

define nscheduler($version) {
  package { "nova-scheduler": ensure => $version, require => Exec["update-apt"] }
  nova_conf_pointer{'scheduler': name => 'scheduler'}
  exec { "update-rc.d -f nova-scheduler remove; update-rc.d nova-scheduler defaults 50":
    path => "/usr/bin:/usr/sbin:/bin",
    onlyif => "test -f /etc/init.d/nova-scheduler",
    unless => "test -f /etc/rc2.d/S50nova-scheduler"
  }
  service { "nova-scheduler":
    ensure => running,
    hasstatus => true,
    subscribe => [
      Package["nova-scheduler"],
      File["/etc/nova/nova.conf"],
      File["/etc/nova/nova-scheduler.conf"]
    ]
  }

}

define napi($version, $api_servers, $api_base_port) {
  file { "/etc/boto.cfg":
    owner => "root", mode => 644,
    source => "puppet://${puppet_server}/files/production/boto.cfg",
  }

  file { "/var/lib/nova/CA/genvpn.sh":
    owner => "nova", mode => 755,
    source => "puppet://${puppet_server}/files/production/genvpn.sh",
  }

  package { "python-greenlet": ensure => present }
  package { "nova-api": ensure => $version, require => [Exec["update-apt"], Package["python-greenlet"]] }
  nova_conf_pointer{'api': name => 'api'}

  exec { "update-rc.d -f nova-api remove; update-rc.d nova-api defaults 50":
    path => "/usr/bin:/usr/sbin:/bin",
    onlyif => "test -f /etc/init.d/nova-api",
    unless => "test -f /etc/rc2.d/S50nova-api"
  }

  service { "nova-netsync":
    start => "/usr/bin/nova-netsync --pidfile=/var/run/nova/nova-netsync.pid --lockfile=/var/run/nova/nova-netsync.pid.lock start",
    stop => "/usr/bin/nova-netsync --pidfile=/var/run/nova/nova-netsync.pid --lockfile=/var/run/nova/nova-netsync.pid.lock stop",
    ensure => running,
    hasstatus => false,
    pattern => "nova-netsync",
    require => Service["nova-api"],
    subscribe => File["/etc/nova/nova.conf"]
  }
  service { "nova-api":
    start => "monit start all -g nova_api",
    stop => "monit stop all -g nova_api",
    restart => "monit restart all -g nova_api",
    # ensure => running,
    # hasstatus => true,
    require => Service["monit"],
    subscribe => [
      Package["nova-objectstore"],
      File["/etc/boto.cfg"],
      File["/etc/nova/nova.conf"],
      File["/etc/nova/nova-objectstore.conf"]
    ]
  }

  # the haproxy & monit's template use $api_servers and $api_base_port

  package { "haproxy": ensure => present }
  file { "/etc/default/haproxy":
    owner => "root", mode => 644,
    content => "ENABLED=1",
    require => Package['haproxy']
  }
  file { "/etc/haproxy/haproxy.cfg":
    owner => "root", mode => 644,
    content => template("/srv/cloud/puppet/templates/haproxy.cfg.erb"),
    require => Package['haproxy']
  }
  service { "haproxy":
    ensure => true,
    enable => true,
    hasstatus => true,
    subscribe => [
      Package["haproxy"],
      File["/etc/default/haproxy"],
      File["/etc/haproxy/haproxy.cfg"],
    ]
  }

  package { "socat": ensure => present }

  file { "/usr/local/bin/gmetric_haproxy.sh":
    owner => "root", mode => 755,
    source => "puppet://${puppet_server}/files/production/ganglia/gmetric_scripts/gmetric_haproxy.sh",
  }

  cron { "gmetric_haproxy":
    command => "/usr/local/bin/gmetric_haproxy.sh",
    user    => root,
    minute  => "*/3",
  }

  package { "monit": ensure => present }

  file { "/etc/default/monit":
    owner => "root", mode => 644,
    content => "startup=1",
    require => Package['monit']
  }
  file { "/etc/monit/monitrc":
    owner => "root", mode => 600,
    content => template("/srv/cloud/puppet/templates/monitrc-nova-api.erb"),
    require => Package['monit']
  }
  service { "monit":
    ensure => true,
    pattern => "sbin/monit",
    subscribe => [
      Package["monit"],
      File["/etc/default/monit"],
      File["/etc/monit/monitrc"],
    ]
  }

}


define nnetwork($version) {
  # kill the default network added by the package
  exec { "kill-libvirt-default-net":
    command => "virsh net-destroy default; rm /etc/libvirt/qemu/networks/autostart/default.xml",
    path => "/usr/bin:/bin",
    onlyif => "test -f /etc/libvirt/qemu/networks/autostart/default.xml"
  }

  # EVIL HACK: custom binary because dnsmasq 2.52 segfaulted accessing dereferenced object
  file { "/usr/sbin/dnsmasq":
    owner => "root", group => "root",
    source => "puppet://${puppet_server}/files/production/dnsmasq",
  }

  package { "nova-network": ensure => $version, require => Exec["update-apt"] }
  nova_conf_pointer{'dhcpbridge': name => 'dhcpbridge'}
  nova_conf_pointer{'network': name => "network" }

  exec { "update-rc.d -f nova-network remove; update-rc.d nova-network defaults 50":
    path => "/usr/bin:/usr/sbin:/bin",
    onlyif => "test -f /etc/init.d/nova-network",
    unless => "test -f /etc/rc2.d/S50nova-network"
  }
  service { "nova-network":
    ensure => running,
    hasstatus => true,
    subscribe => [
      Package["nova-network"],
      File["/etc/nova/nova.conf"],
      File["/etc/nova/nova-network.conf"]
    ]
  }
}

define nobjectstore($version) {
  package { "nova-objectstore": ensure => $version, require => Exec["update-apt"] }
  nova_conf_pointer{'objectstore': name => 'objectstore'}
  exec { "update-rc.d -f nova-objectstore remove; update-rc.d nova-objectstore defaults 50":
    path => "/usr/bin:/usr/sbin:/bin",
    onlyif => "test -f /etc/init.d/nova-objectstore",
    unless => "test -f /etc/rc2.d/S50nova-objectstore"
  }
  service { "nova-objectstore":
    ensure => running,
    hasstatus => true,
    subscribe => [
      Package["nova-objectstore"],
      File["/etc/nova/nova.conf"],
      File["/etc/nova/nova-objectstore.conf"]
    ]
  }
}

define ncompute($version) {
  include ganglia-python
  include ganglia-compute

  # kill the default network added by the package
  exec { "kill-libvirt-default-net":
    command => "virsh net-destroy default; rm /etc/libvirt/qemu/networks/autostart/default.xml",
    path => "/usr/bin:/bin",
    onlyif => "test -f /etc/libvirt/qemu/networks/autostart/default.xml"
  }


  # LIBVIRT has to be restarted when ebtables / gawk is installed
  service { "libvirt-bin":
    ensure => running,
    pattern => "sbin/libvirtd",
    subscribe => [
      Package["ebtables"],
      Kern_module["kvm_intel"]
    ],
    require => [
      Package["libvirt-bin"],
      Package["ebtables"],
      Package["gawk"],
      Kern_module["kvm_intel"],
      File["/dev/kvm"]
    ]
  }

  package { "libvirt-bin": ensure => "0.8.3-1ubuntu14~ppalucid2" }
  package { "ebtables": ensure => present }
  package { "gawk": ensure => present }

  # ensure proper permissions on /dev/kvm
  file { "/dev/kvm":
    owner => "root",
    group => "kvm",
    mode => 660
  }

  # require hardware virt
  kern_module { "kvm_intel":
    ensure => present,
  }

  # increase loopback devices
  file { "/etc/modprobe.d/loop.conf":
    owner => "root", mode => 644,
    content => "options loop max_loop=40"
  }

  nova_conf_pointer{'compute': name => 'compute'}

  loopback{loop0: num => 0}
  loopback{loop1: num => 1}
  loopback{loop2: num => 2}
  loopback{loop3: num => 3}
  loopback{loop4: num => 4}
  loopback{loop5: num => 5}
  loopback{loop6: num => 6}
  loopback{loop7: num => 7}
  loopback{loop8: num => 8}
  loopback{loop9: num => 9}
  loopback{loop10: num => 10}
  loopback{loop11: num => 11}
  loopback{loop12: num => 12}
  loopback{loop13: num => 13}
  loopback{loop14: num => 14}
  loopback{loop15: num => 15}
  loopback{loop16: num => 16}
  loopback{loop17: num => 17}
  loopback{loop18: num => 18}
  loopback{loop19: num => 19}
  loopback{loop20: num => 20}
  loopback{loop21: num => 21}
  loopback{loop22: num => 22}
  loopback{loop23: num => 23}
  loopback{loop24: num => 24}
  loopback{loop25: num => 25}
  loopback{loop26: num => 26}
  loopback{loop27: num => 27}
  loopback{loop28: num => 28}
  loopback{loop29: num => 29}
  loopback{loop30: num => 30}
  loopback{loop31: num => 31}
  loopback{loop32: num => 32}
  loopback{loop33: num => 33}
  loopback{loop34: num => 34}
  loopback{loop35: num => 35}
  loopback{loop36: num => 36}
  loopback{loop37: num => 37}
  loopback{loop38: num => 38}
  loopback{loop39: num => 39}

  package { "python-libvirt": ensure => "0.8.3-1ubuntu14~ppalucid2" }

  package { "nova-compute":
      ensure => "$version",
      require => Package["python-libvirt"]
  }

  #file { "/usr/share/nova/libvirt.qemu.xml.template":
  #  owner => "nova", mode => 400,
  #  source => "puppet://${puppet_server}/files/production/libvirt.qemu.xml.template",
  #}

  # fix runlevels: using enable => true adds it as 20, which is too early
  exec { "update-rc.d -f nova-compute remove":
    path => "/usr/bin:/usr/sbin:/bin",
    onlyif => "test -f /etc/rc2.d/S??nova-compute"
  }
  service { "nova-compute":
    ensure => running,
    hasstatus => true,
    subscribe => [
      Package["nova-compute"],
      File["/etc/nova/nova.conf"],
      File["/etc/nova/nova-compute.conf"],
      #File["/usr/share/nova/libvirt.qemu.xml.template"],
      Service["libvirt-bin"],
      Kern_module["kvm_intel"]
    ]
  }
}

define nvolume($version) {

  package { "nova-volume": ensure => $version, require => Exec["update-apt"] }

  nova_conf_pointer{'volume': name => 'volume'}

  # fix runlevels: using enable => true adds it as 20, which is too early
  exec { "update-rc.d -f nova-volume remove":
    path => "/usr/bin:/usr/sbin:/bin",
    onlyif => "test -f /etc/rc2.d/S??nova-volume"
  }

  file { "/etc/default/iscsitarget":
    owner => "root", mode => 644,
    content => "ISCSITARGET_ENABLE=true"
  }

  package { "iscsitarget": ensure => present }

  file { "/dev/iscsi": ensure => directory } # FIXME(vish): owner / mode?
  file { "/usr/sbin/nova-iscsi-dev.sh":
    owner => "root", mode => 755,
    source => "puppet://${puppet_server}/files/production/nova-iscsi-dev.sh"
  }
  file { "/etc/udev/rules.d/55-openiscsi.rules":
    owner => "root", mode => 644,
    content => 'KERNEL=="sd*", BUS=="scsi", PROGRAM="/usr/sbin/nova-iscsi-dev.sh %b",SYMLINK+="iscsi/%c%n"'
  }

  service { "iscsitarget":
    ensure => running,
    enable => true,
    hasstatus => true,
    require => [
      File["/etc/default/iscsitarget"],
      Package["iscsitarget"]
    ]
  }

  service { "nova-volume":
    ensure => running,
    hasstatus => true,
    subscribe => [
      Package["nova-volume"],
      File["/etc/nova/nova.conf"],
      File["/etc/nova/nova-volume.conf"]
    ]
  }
}

class novaspool {
    # This isn't in release yet
  #cron { logspool:
  #  command => "/usr/bin/nova-logspool /var/log/nova.log /var/lib/nova/spool",
  #  user => "nova"
  #}
  #cron { spoolsentry:
  #  command => "/usr/bin/nova-spoolsentry ${sentry_url} ${sentry_key} /var/lib/nova/spool",
  #  user => "nova"
  #}
}
