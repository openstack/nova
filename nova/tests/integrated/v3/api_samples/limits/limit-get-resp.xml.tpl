<?xml version='1.0' encoding='UTF-8'?>
<limits xmlns:atom="http://www.w3.org/2005/Atom" xmlns="http://docs.openstack.org/common/api/v1.0">
  <rates>
    <rate regex=".*" uri="*">
      <limit next-available="%(timestamp)s" unit="MINUTE" verb="POST" remaining="10" value="10"/>
      <limit next-available="%(timestamp)s" unit="MINUTE" verb="PUT" remaining="10" value="10"/>
      <limit next-available="%(timestamp)s" unit="MINUTE" verb="DELETE" remaining="100" value="100"/>
    </rate>
    <rate regex="^/servers" uri="*/servers">
      <limit next-available="%(timestamp)s" unit="DAY" verb="POST" remaining="50" value="50"/>
    </rate>
    <rate regex=".*changes_since.*" uri="*changes_since*">
      <limit next-available="%(timestamp)s" unit="MINUTE" verb="GET" remaining="3" value="3"/>
    </rate>
  </rates>
</limits>
