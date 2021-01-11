{
    "hypervisors": [
        {
            "id": "%(hypervisor_id)s",
            "status": "enabled",
            "state": "up",
            "host_ip": "%(ip)s",
            "hypervisor_hostname": "host2",
            "hypervisor_type": "fake",
            "hypervisor_version": 1000,
            "service": {
                "host": "%(host_name)s",
                "id": "%(service_id)s",
                "disabled_reason": null
            },
            "uptime": null
        }
    ],
    "hypervisors_links": [
        {
            "href": "http://openstack.example.com/v2.1/6f70656e737461636b20342065766572/os-hypervisors/detail?limit=1&marker=%(hypervisor_id)s",
            "rel": "next"
        }
    ]
}
