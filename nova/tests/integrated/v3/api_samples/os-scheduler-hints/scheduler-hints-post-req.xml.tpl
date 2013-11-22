<?xml version="1.0" encoding="UTF-8"?>
<server xmlns:os-scheduler-hints="http://docs.openstack.org/compute/ext/scheduler-hints/api/v3" xmlns="http://docs.openstack.org/compute/api/v1.1" image_ref="%(glance_host)s/openstack/images/%(image_id)s" flavor_ref="%(host)s/flavors/1" name="new-server-test">
  <os-scheduler-hints:scheduler_hints>
    <hypervisor>xen</hypervisor>
    <near>%(image_near)s</near>
  </os-scheduler-hints:scheduler_hints>
</server>
