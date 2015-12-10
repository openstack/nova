{
    "servers": [
    {
            "OS-EXT-STS:task_state": null,
            "OS-EXT-STS:vm_state": "active",
            "OS-EXT-STS:power_state": 1,
            "accessIPv4": "%(access_ip_v4)s",
            "accessIPv6": "%(access_ip_v6)s",
            "updated": "%(isotime)s",
            "created": "%(isotime)s",
            "addresses": {
                "private": [
                    {
                        "addr": "%(ip)s",
                        "version": 4,
                        "OS-EXT-IPS-MAC:mac_addr": "aa:bb:cc:dd:ee:ff",
                        "OS-EXT-IPS:type": "fixed"
                    }
                ]
            },
            "flavor": {
                "id": "1",
                "links": [
                    {
                        "href": "%(compute_endpoint)s/flavors/1",
                        "rel": "bookmark"
                    }
                ]
            },
            "hostId": "%(hostid)s",
            "id": "%(uuid)s",
            "image": {
                "id": "%(uuid)s",
                "links": [
                    {
                        "href": "%(compute_endpoint)s/images/%(uuid)s",
                        "rel": "bookmark"
                    }
                ]
            },
            "links": [
                {
                    "href": "%(versioned_compute_endpoint)s/servers/%(id)s",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/servers/%(id)s",
                    "rel": "bookmark"
                }
            ],
            "metadata": {
                "My Server Name": "Apache1"
            },
            "name": "new-server-test",
            "progress": 0,
            "status": "ACTIVE",
            "tenant_id": "openstack",
            "user_id": "fake",
            "key_name": null
    }]
}
