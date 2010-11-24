# site.pp

import "templates"
import "classes/*"

node novabase inherits default {
#  $puppet_server = "192.168.0.10"
  $cluster_name = "openstack001"
  $ganglia_udp_send_channel = "openstack001.example.com"
  $syslog = "192.168.0.10"

  # THIS STUFF ISN'T IN RELEASE YET
  #$sentry_url = "http://192.168.0.19/sentry/store/"
  #$sentry_key = "TODO:SENTRYPASS"

  $local_network = "192.168.0.0/16"
  $vpn_ip = "192.168.0.2"
  $public_interface = "eth0"
  include novanode
#  include nova-common
  include opsmetrics

# non-nova stuff such as nova-dash inherit from novanode
# novaspool needs a better home
#  include novaspool
}

# Builder
node "nova000.example.com" inherits novabase {
  $syslog = "server"
  include ntp
  include syslog-server
}

# Non-Nova nodes

node
     "blog.example.com",
     "wiki.example.com"
inherits novabase {
  include ganglia-python
  include ganglia-apache
  include ganglia-mysql
}


node "nova001.example.com"
inherits novabase {
  include novabase

  nova_iptables { nova:
      services => [
        "ganglia",
        "mysql",
        "rabbitmq",
        "ldap",
        "api",
        "objectstore",
        "nrpe",
      ],
      ip => "192.168.0.10",
   }

  nobjectstore { nova: version => "0.9.0" }
  nscheduler   { nova: version => "0.9.0" }
  napi { nova:
    version => "0.9.0",
    api_servers => 10,
    api_base_port => 8000
  }
}

node "nova002.example.com"
inherits novabase {
  include novaconf

  nova_iptables { nova:
      services => [
        "ganglia",
        "dnsmasq",
        "nrpe"
      ],
      ip => "192.168.4.2",
      private_range => "192.168.0.0/16",
   }

  nnetwork { nova: version => "0.9.0" }
}

node
     "nova003.example.com",
     "nova004.example.com",
     "nova005.example.com",
     "nova006.example.com",
     "nova007.example.com",
     "nova008.example.com",
     "nova009.example.com",
     "nova010.example.com",
     "nova011.example.com",
     "nova012.example.com",
     "nova013.example.com",
     "nova014.example.com",
     "nova015.example.com",
     "nova016.example.com",
     "nova017.example.com",
     "nova018.example.com",
     "nova019.example.com",
inherits novabase {
  include novaconf
  ncompute { nova: version => "0.9.0" }
  nvolume  { nova: version => "0.9.0" }
}

#node
#     "nova020.example.com"
#     "nova021.example.com"
#inherits novanode {
#  include novaconf
  #ncompute { nova: version => "0.9.0" }
#}
