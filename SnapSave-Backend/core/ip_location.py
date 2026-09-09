import requests


def get_user_location(ip=None):

    try:

        if ip:
            url = f"http://ip-api.com/json/{ip}"
        else:
            url = "http://ip-api.com/json"

        r = requests.get(url)

        data = r.json()

        lat = data.get("lat")
        lon = data.get("lon")
        city = data.get("city")

        return lat, lon, city

    except:
        return None, None, None