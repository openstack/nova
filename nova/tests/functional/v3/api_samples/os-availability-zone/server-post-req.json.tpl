{
    "server" : {
        "name" : "new-server-test",
        "imageRef" : "%(host)s/openstack/images/%(image_id)s",
        "flavorRef" : "%(host)s/openstack/flavors/1",
        "availability_zone": "nova",
        "metadata" : {
            "My Server Name" : "Apache1"
        }
    }
}
