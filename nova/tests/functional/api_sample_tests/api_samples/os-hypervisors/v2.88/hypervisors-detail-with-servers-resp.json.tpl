{
    "hypervisors": [
        {
            "id": "%(hypervisor_id)s",
            "status": "enabled",
            "state": "up",
            "host_ip": "%(ip)s",
            "hypervisor_hostname": "fake-mini",
            "hypervisor_type": "fake",
            "hypervisor_version": 1000,
            "servers": [
                {
                    "name": "test_server1",
                    "uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
                },
                {
                    "name": "test_server2",
                    "uuid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
                }
            ],
            "service": {
                "host": "%(host_name)s",
                "id": "%(service_id)s",
                "disabled_reason": null
            },
            "uptime": null
        }
    ]
}
