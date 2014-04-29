{
    "servers": [
        {
            "OS-EXT-SRV-ATTR:host": "%(compute_host)s",
            "OS-EXT-SRV-ATTR:hypervisor_hostname": "%(hypervisor_hostname)s",
            "OS-EXT-SRV-ATTR:instance_name": "%(instance_name)s",
            "accessIPv4": "",
            "accessIPv6": "",
            "addresses": {
                "private": [
                    {
                        "addr": "%(ip)s",
                        "version": 4
                    }
                ]
            },
            "created": "%(isotime)s",
            "flavor": {
                "id": "1",
                "links": [
                    {
                        "href": "%(host)s/openstack/flavors/1",
                        "rel": "bookmark"
                    }
                ]
            },
            "hostId": "%(hostid)s",
            "id": "%(id)s",
            "image": {
                "id": "%(uuid)s",
                "links": [
                    {
                        "href": "%(host)s/openstack/images/%(uuid)s",
                        "rel": "bookmark"
                    }
                ]
            },
            "links": [
                {
                    "href": "%(host)s/v2/openstack/servers/%(id)s",
                    "rel": "self"
                },
                {
                    "href": "%(host)s/openstack/servers/%(id)s",
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
            "updated": "%(isotime)s",
            "user_id": "fake"
        }
    ]
}