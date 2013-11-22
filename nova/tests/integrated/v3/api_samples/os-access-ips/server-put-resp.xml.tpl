<?xml version='1.0' encoding='UTF-8'?>
<server xmlns:os-access-ips="http://docs.openstack.org/compute/ext/os-access-ips/api/v3" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" status="ACTIVE" updated="%(timestamp)s" user_id="fake" name="new-server-test" created="%(timestamp)s" tenant_id="openstack" progress="0" host_id="%(hostid)s" id="%(id)s" os-access-ips:access_ip_v4="%(access_ip_v4)s" os-access-ips:access_ip_v6="%(access_ip_v6)s">
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
      <ip version="4" type="fixed" addr="%(ip)s" mac_addr="aa:bb:cc:dd:ee:ff"/>
    </network>
  </addresses>
  <atom:link href="%(host)s/v3/servers/%(uuid)s" rel="self"/>
  <atom:link href="%(host)s/servers/%(uuid)s" rel="bookmark"/>
</server>
