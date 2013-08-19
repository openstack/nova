<?xml version='1.0' encoding='UTF-8'?>
<hosts>
  <host host_name="%(host_name)s" service="compute" zone="nova"/>
  <host host_name="%(host_name)s" service="cert" zone="internal"/>
  <host host_name="%(host_name)s" service="network" zone="internal"/>
  <host host_name="%(host_name)s" service="scheduler" zone="internal"/>
  <host host_name="%(host_name)s" service="conductor" zone="internal"/>
  <host host_name="%(host_name)s" service="cells" zone="internal"/>
  <host host_name="%(host_name)s" service="consoleauth" zone="internal"/>
</hosts>
