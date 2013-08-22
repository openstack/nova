<?xml version='1.0' encoding='UTF-8'?>
<servers xmlns:os-extended-volumes="http://docs.openstack.org/compute/ext/extended_volumes/api/v3" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1">
  <server status="ACTIVE" updated="%(timestamp)s" host_id="%(hostid)s" name="new-server-test" created="%(timestamp)s" user_id="fake" tenant_id="openstack" progress="0" id="%(id)s" key_name="None">
    <image id="%(uuid)s">
      <atom:link href="%(glance_host)s/images/%(uuid)s" rel="bookmark"/>
    </image>
    <flavor id="1">
      <atom:link href="%(host)s/flavors/1" rel="bookmark"/>
    </flavor>
    <metadata>
      <meta key="My Server Name">Apache1</meta>
    </metadata>
    <addresses>
      <network id="private">
        <ip version="4" addr="%(ip)s" type="fixed" mac_addr="aa:bb:cc:dd:ee:ff"/>
      </network>
    </addresses>
    <atom:link href="%(host)s/v3/servers/%(uuid)s" rel="self"/>
    <atom:link href="%(host)s/servers/%(uuid)s" rel="bookmark"/>
    <os-extended-volumes:volume_attached id="volume_id1"/>
    <os-extended-volumes:volume_attached id="volume_id2"/>
  </server>
</servers>
