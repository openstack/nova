<?xml version='1.0' encoding='UTF-8'?>
<server xmlns:OS-SRV-USG="http://docs.openstack.org/compute/ext/server_usage/api/v1.1" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" status="ACTIVE" updated="%(isotime)s" hostId="%(hostid)s" name="new-server-test" created="%(isotime)s" userId="fake" tenantId="openstack" accessIPv4="" accessIPv6="" progress="0" id="%(id)s" OS-SRV-USG:terminated_at="None" OS-SRV-USG:launched_at="%(xmltime)s">
  <image id="%(uuid)s">
    <atom:link href="%(host)s/openstack/images/%(uuid)s" rel="bookmark"/>
  </image>
  <flavor id="1">
    <atom:link href="%(host)s/openstack/flavors/1" rel="bookmark"/>
  </flavor>
  <metadata>
    <meta key="My Server Name">Apache1</meta>
  </metadata>
  <addresses>
    <network id="private">
      <ip version="4" addr="%(ip)s"/>
    </network>
  </addresses>
  <atom:link href="%(host)s/v2/openstack/servers/%(uuid)s" rel="self"/>
  <atom:link href="%(host)s/openstack/servers/%(uuid)s" rel="bookmark"/>
</server>
