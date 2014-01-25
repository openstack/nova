<?xml version="1.0" encoding="UTF-8"?>
<server xmlns="http://docs.openstack.org/compute/api/v1.1"
        xmlns:atom="http://www.w3.org/2005/Atom"
        id="%(uuid)s"
        tenantId="openstack" userId="fake"
        name="%(name)s"
        hostId="%(hostid)s" progress="0"
        status="ACTIVE" adminPass="%(password)s"
        created="%(timestamp)s"
        updated="%(timestamp)s"
        accessIPv4="%(ip)s"
        accessIPv6="%(ip6)s">
  <image id="%(uuid)s">
      <atom:link
          rel="bookmark"
          href="%(host)s/openstack/images/%(uuid)s"/>
  </image>
  <flavor id="1">
      <atom:link
          rel="bookmark"
          href="%(host)s/openstack/flavors/1"/>
  </flavor>
  <metadata>
    <meta key="My Server Name">Apache1</meta>
  </metadata>
  <addresses>
    <network id="private">
      <ip version="4" addr="%(ip)s"/>
    </network>
  </addresses>
  <atom:link
      rel="self"
      href="%(host)s/v2/openstack/servers/%(uuid)s"/>
  <atom:link
      rel="bookmark"
      href="%(host)s/openstack/servers/%(uuid)s"/>
</server>
