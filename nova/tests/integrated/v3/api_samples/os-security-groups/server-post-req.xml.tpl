<?xml version="1.0" encoding="UTF-8"?>
<server xmlns:os-security-groups="http://docs.openstack.org/compute/ext/securitygroups/api/v3" xmlns="http://docs.openstack.org/compute/api/v1.1" image_ref="%(glance_host)s/openstack/images/%(image_id)s" flavor_ref="%(host)s/openstack/flavors/1" name="new-server-test">
  <metadata>
    <meta key="My Server Name">Apache1</meta>
  </metadata>
  <os-security-groups:security_groups>
    <security_group name="test" />
  </os-security-groups:security_groups>
</server>
