# templates.pp

import "classes/*"

class baseclass {
#  include dns-client  # FIXME: missing resolv.conf.erb??
  include issue
}

node default {
  $nova_site = "undef"
  $nova_ns1 = "undef"
  $nova_ns2 = "undef"
#  include baseclass
}

# novanode handles the system-level requirements for Nova/Swift nodes
class novanode {
  include baseclass
  include lvmconf
}
