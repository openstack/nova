<?xml version='1.0' encoding='UTF-8'?>
<services>
  <service status="disabled" binary="nova-scheduler" zone="internal" state="up" updated_at="%(timestamp)s" host="host1" id="1"/>
  <service status="disabled" binary="nova-compute" zone="nova" state="up" updated_at="%(timestamp)s" host="host1" id="2"/>
  <service status="enabled" binary="nova-scheduler" zone="internal" state="down" updated_at="%(timestamp)s" host="host2" id="3"/>
  <service status="disabled" binary="nova-compute" zone="nova" state="down" updated_at="%(timestamp)s" host="host2" id="4"/>
</services>
