"""
Module just for calculating the distance between two longitude and latitudes on the earth's surface.

Not really important for small distances (distance << 1000 km), but might be important at larger distances. 
"""

#from geopy.distance import geodesic

def calculate_geo_distance(lat_1, lon_1, lat_2, lon_2):
    """
    Calculates the distance in km along the surface of the earth, accounting for the earth's ellispoidal shape. 
    """
    R = 6371.0  # Earth radius in km                                                               

    dlat = np.radians(lat_2 - lat_1)
    dlon = np.radians(lon_2 - lon_1)

    # Haversine formula. Assumes earth is a sphere of radius R. 
    a = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2

    return 2 * R * np.arcsin(np.sqrt(a))


