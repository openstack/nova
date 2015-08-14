{
    "server": {
        "OS-DCF:diskConfig": "AUTO",
        "accessIPv4": "%(ip)s",
        "accessIPv6": "%(ip6)s",
        "addresses": {
            "private": [
                {
                    "addr": "%(ip)s",
                    "version": 4
                }
            ]
        },
        "adminPass": "%(password)s",
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
        "id": "%(uuid)s",
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
                "href": "%(host)s/v2/openstack/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(host)s/openstack/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "metadata": {
            "meta var": "meta val"
        },
        "name": "%(name)s",
        "progress": 0,
        "status": "ACTIVE",
        "tenant_id": "openstack",
        "updated": "%(isotime)s",
        "user_id": "fake"
    }
}
