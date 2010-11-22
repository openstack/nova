class issue {
  file { "/etc/issue":
    owner => "root",
    group => "root",
    mode => 444,
    source => "puppet://${puppet_server}/files/etc/issue",
  }
  file { "/etc/issue.net":
    owner => "root",
    group => "root",
    mode => 444,
    source => "puppet://${puppet_server}/files/etc/issue",
  }
}
