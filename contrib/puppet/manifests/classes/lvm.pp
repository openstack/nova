class lvm {
  file { "/etc/lvm/lvm.conf":
    owner => "root",
    group => "root",
    mode => 444,
    source => "puppet://${puppet_server}/files/etc/lvm.conf",
  }
}
