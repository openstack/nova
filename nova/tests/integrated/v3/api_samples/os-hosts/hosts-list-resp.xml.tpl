<?xml version='1.0' encoding='UTF-8'?>
<hosts>
  <host zone="internal" host_name="%(host_name)s" service="conductor"/>
  <host zone="nova" host_name="%(host_name)s" service="compute"/>
  <host zone="internal" host_name="%(host_name)s" service="cert"/>
  <host zone="internal" host_name="%(host_name)s" service="consoleauth"/>
  <host zone="internal" host_name="%(host_name)s" service="network"/>
  <host zone="internal" host_name="%(host_name)s" service="scheduler"/>
  <host zone="internal" host_name="%(host_name)s" service="cells"/>
</hosts>
