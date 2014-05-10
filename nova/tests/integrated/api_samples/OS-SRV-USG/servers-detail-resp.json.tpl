{
    "servers": [
    {
            "status": "ACTIVE",
            "updated": "%(isotime)s",
            "OS-SRV-USG:launched_at": "%(strtime)s",
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
                    "href": "%(host)s/v2/openstack/servers/%(uuid)s",
                    "rel": "self"
                },
                {
                    "href": "%(host)s/openstack/servers/%(uuid)s",
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
            "OS-SRV-USG:terminated_at": null,
            "tenant_id": "openstack",
            "progress": 0,
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
