{
    "server": {
        "updated": "%(isotime)s",
        "created": "%(isotime)s",
        "OS-EXT-AZ:availability_zone": "nova",
        "accessIPv4": "%(access_ip_v4)s",
        "accessIPv6": "%(access_ip_v6)s",
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
            "My Server Name": "Apache1"
        },
        "name": "new-server-test",
        "progress": 0,
        "status": "ACTIVE",
        "tenant_id": "openstack",
        "user_id": "fake",
        "key_name": null
    }
}
