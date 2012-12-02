<?xml version='1.0' encoding='UTF-8'?>
<image xmlns:OS-DCF="http://docs.openstack.org/compute/ext/disk_config/api/v1.1" xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/compute/api/v1.1" status="ACTIVE" updated="2011-01-01T01:02:03Z" name="fakeimage7" created="2011-01-01T01:02:03Z" minDisk="0" progress="100" minRam="0" id="%(image_id)s" OS-DCF:diskConfig="AUTO">
  <metadata>
    <meta key="kernel_id">nokernel</meta>
    <meta key="auto_disk_config">True</meta>
    <meta key="ramdisk_id">nokernel</meta>
    <meta key="architecture">x86_64</meta>
  </metadata>
  <atom:link href="%(host)s/v2/openstack/images/%(image_id)s" rel="self"/>
  <atom:link href="%(host)s/openstack/images/%(image_id)s" rel="bookmark"/>
  <atom:link href="%(glance_host)s/openstack/images/%(image_id)s" type="application/vnd.openstack.image" rel="alternate"/>
</image>
