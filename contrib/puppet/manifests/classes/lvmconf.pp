class lvmconf {
  file { "/etc/lvm/lvm.conf":
    owner => "root", group => "root", mode  => 644,
    source => "puppet://${puppet_server}/files/etc/lvm/lvm.conf",
    ensure => present
  }
}

