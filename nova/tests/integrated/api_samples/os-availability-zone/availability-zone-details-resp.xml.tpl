<?xml version='1.0' encoding='UTF-8'?>
<availabilityZones
    xmlns:os-availability-zone="http://docs.openstack.org/compute/ext/availabilityzone/api/v1.1">
    <availabilityZone name="zone-1">
        <zoneState available="True" />
        <hosts>
            <host name="fake_host-1">
                <services>
                    <service name="nova-compute">
                        <serviceState available="True" active="True"
                            updated_at="2012-12-26 14:45:25" />
                    </service>
                </services>
            </host>
        </hosts>
        <metadata />
    </availabilityZone>
    <availabilityZone name="internal">
        <zoneState available="True" />
        <hosts>
            <host name="fake_host-1">
                <services>
                    <service name="nova-sched">
                        <serviceState available="True" active="True"
                            updated_at="2012-12-26 14:45:25" />
                    </service>
                </services>
            </host>
            <host name="fake_host-2">
                <services>
                    <service name="nova-network">
                        <serviceState available="False" active="True"
                            updated_at="2012-12-26 14:45:24" />
                    </service>
                </services>
            </host>
        </hosts>
        <metadata />
    </availabilityZone>
    <availabilityZone name="zone-2">
        <zoneState available="False" />
        <metadata />
    </availabilityZone>
</availabilityZones>