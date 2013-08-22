<?xml version='1.0' encoding='UTF-8'?>
<server xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" status="%(status)s" updated="%(timestamp)s" host_id="%(hostid)s" name="new-server-test" created="%(timestamp)s" user_id="fake" tenant_id="openstack" progress="0" id="%(id)s" key_name="None">
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
  <atom:link href="%(host)s/v3/servers/%(id)s" rel="self"/>
  <atom:link href="%(host)s/servers/%(id)s" rel="bookmark"/>
</server>