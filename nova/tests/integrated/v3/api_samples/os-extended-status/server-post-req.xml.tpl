<?xml version="1.0" encoding="UTF-8"?>
<server xmlns="http://docs.openstack.org/compute/api/v1.1" image_ref="%(glance_host)s/images/%(image_id)s" flavor_ref="%(host)s/flavors/1" name="new-server-test">
  <metadata>
    <meta key="My Server Name">Apache1</meta>
  </metadata>
</server>
