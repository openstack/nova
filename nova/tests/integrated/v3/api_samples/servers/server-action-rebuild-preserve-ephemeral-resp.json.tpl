{
    "server": {
        "addresses": {
            "private": [
                {
                    "addr": "%(ip)s",
                    "version": 4,
                    "mac_addr": "aa:bb:cc:dd:ee:ff",
                    "type": "fixed"
                }
            ]
        },
        "admin_password": "%(password)s",
        "created": "%(timestamp)s",
        "flavor": {
            "id": "1",
            "links": [
                {
                    "href": "%(host)s/flavors/1",
                    "rel": "bookmark"
                }
            ]
        },
        "host_id": "%(hostid)s",
        "id": "%(uuid)s",
        "image": {
            "id": "%(uuid)s",
            "links": [
                {
                    "href": "%(glance_host)s/images/%(uuid)s",
                    "rel": "bookmark"
                }
            ]
        },
        "links": [
            {
                "href": "%(host)s/v3/servers/%(uuid)s",
                "rel": "self"
            },
            {
                "href": "%(host)s/servers/%(uuid)s",
                "rel": "bookmark"
            }
        ],
        "metadata": {
            "meta_var": "meta_val"
        },
        "name": "%(name)s",
        "progress": 0,
        "status": "ACTIVE",
        "tenant_id": "openstack",
        "updated": "%(timestamp)s",
        "user_id": "fake"
    }
}
