<?xml version='1.0' encoding='UTF-8'?>
<services>
  <service status="disabled" binary="nova-scheduler" zone="internal" state="up" updated_at="%(timestamp)s" host="host1" disabled_reason="test1"/>
  <service status="disabled" binary="nova-compute" zone="nova" state="up" updated_at="%(timestamp)s" host="host1" disabled_reason="test2"/>
  <service status="enabled" binary="nova-scheduler" zone="internal" state="down" updated_at="%(timestamp)s" host="host2" disabled_reason=""/>
  <service status="disabled" binary="nova-compute" zone="nova" state="down" updated_at="%(timestamp)s" host="host2" disabled_reason="test4"/>
</services>
