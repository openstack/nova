class swift {
  package { "memcached": ensure => present }
  service { "memcached": require => Package['memcached'] }

  package { "swift-proxy": ensure => present }
}

