<?xml version='1.0' encoding='UTF-8'?>
<server xmlns:OS-DCF="http://docs.openstack.org/compute/ext/disk_config/api/v1.1" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" id="%(id)s" adminPass="%(password)s" OS-DCF:diskConfig="AUTO">
  <metadata/>
  <atom:link href="%(host)s/v2/openstack/servers/%(uuid)s" rel="self"/>
  <atom:link href="%(host)s/openstack/servers/%(uuid)s" rel="bookmark"/>
  <security_groups>
    <security_group name="default"/>
  </security_groups>
</server>
