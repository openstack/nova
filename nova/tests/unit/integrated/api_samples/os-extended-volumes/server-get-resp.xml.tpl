<?xml version='1.0' encoding='UTF-8'?>
<server xmlns:os-extended-volumes="http://docs.openstack.org/compute/ext/extended_volumes/api/v1.1" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" status="ACTIVE" updated="%(isotime)s" hostId="%(hostid)s" name="new-server-test" created="%(isotime)s" userId="fake" tenantId="openstack" accessIPv4="" accessIPv6="" progress="0" id="%(id)s">
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
  <os-extended-volumes:volume_attached id="volume_id1"/>
  <os-extended-volumes:volume_attached id="volume_id2"/>
  <atom:link href="%(host)s/v2/openstack/servers/%(id)s" rel="self"/>
  <atom:link href="%(host)s/openstack/servers/%(id)s" rel="bookmark"/>
</server>
