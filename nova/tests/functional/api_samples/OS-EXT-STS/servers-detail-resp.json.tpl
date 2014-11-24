{
    "servers": [
    {
            "status": "ACTIVE",
            "updated": "%(isotime)s",
            "OS-EXT-STS:task_state": null,
            "user_id": "fake",
            "addresses": {
                "private": [
                    {
                        "addr": "%(ip)s",
                        "version": 4
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
            "created": "%(isotime)s",
            "name": "new-server-test",
            "image": {
                "id": "%(uuid)s",
                "links": [
                    {
                        "href": "%(host)s/openstack/images/%(uuid)s",
                        "rel": "bookmark"
                    }
                ]
            },
            "id": "%(uuid)s",
            "accessIPv4": "",
            "accessIPv6": "",
            "OS-EXT-STS:vm_state": "active",
            "tenant_id": "openstack",
            "progress": 0,
            "OS-EXT-STS:power_state": 1,
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
            "metadata": {
                "My Server Name": "Apache1"
            }
    }]
}
