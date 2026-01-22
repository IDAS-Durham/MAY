"""
Module just for calculating the distance between two longitude and latitudes on the earth's surface.

Not really important for small distances (distance << 1000 km), but might be important at larger distances. 
"""

#from geopy.distance import geodesic

def calculate_geo_distance(coord_1, coord_2):
    """
    Calculates the distance in km along the surface of the earth, accounting for the earth's ellispoidal shape. 
    """
    raise NotImplementedError("Not yet implemented more accurate version of geo distance")

    
