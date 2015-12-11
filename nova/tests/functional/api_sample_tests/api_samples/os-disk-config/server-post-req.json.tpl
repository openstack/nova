{
    "server" : {
        "OS-DCF:diskConfig": "AUTO",
        "name" : "new-server-test",
        "imageRef" : "%(compute_endpoint)s/images/%(image_id)s",
        "flavorRef" : "%(compute_endpoint)s/flavors/1",
        "metadata" : {
            "My Server Name" : "Apache1"
        }
    }
}
