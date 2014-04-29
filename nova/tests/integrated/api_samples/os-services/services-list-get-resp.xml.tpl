<services>
    <service status="disabled" binary="nova-scheduler" zone="internal" state="up" host="host1" updated_at="%(xmltime)s"/>
    <service status="disabled" binary="nova-compute" zone="nova" state="up" host="host1" updated_at="%(xmltime)s" />
    <service status="enabled" binary="nova-scheduler" zone="internal" state="down" host="host2" updated_at="%(xmltime)s"/>
    <service status="disabled" binary="nova-compute" zone="nova" state="down" host="host2" updated_at="%(xmltime)s"/>
</services>
