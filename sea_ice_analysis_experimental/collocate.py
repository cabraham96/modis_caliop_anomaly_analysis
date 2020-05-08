# https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.haversine_distances.html

# Third party imports.
import netCDF4 as nc
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from tqdm import tqdm

# Local application imports.
from nsidc_amsr import get_geodetic_crs

# Constant definitions.
#   - Planet radii values in meters.
EQUATORIAL_RADIUS = 6_378_137.0
POLAR_RADIUS      = 6_356_752.3142
MEAN_RADIUS       = (2 * EQUATORIAL_RADIUS + POLAR_RADIUS) / 3
NEIGHBORS_CHECKED = 4


def haversine(point_1, point_2):
    
    latitude_1, longitude_1 = point_1
    latitude_2, longitude_2 = point_2
    
    # Aliasing for brevity.
    R     = MEAN_RADIUS
    lat_1 = latitude_1
    lon_1 = longitude_1
    lat_2 = latitude_2
    lon_2 = longitude_2
    
    lon_1, lat_1, lon_2, lat_2 = map(np.radians, [lon_1, lat_1, lon_2, lat_2])
    
    dlon = lon_2 - lon_1
    dlat = lat_2 - lat_1
    
    d = 2 * R * np.arcsin(np.sqrt(np.sin(dlat / 2) ** 2 +
                                  np.sin(dlon / 2) ** 2 *
                                  np.cos(lat_1) *
                                  np.cos(lat_2)))
    
    return d
    

def lambert(point_1, point_2):
    
    latitude_1, longitude_1 = point_1
    latitude_2, longitude_2 = point_2
    
    # Aliasing for brevity.
    a     = EQUATORIAL_RADIUS
    b     = POLAR_RADIUS
    R     = MEAN_RADIUS
    lat_1 = latitude_1
    lon_1 = longitude_1
    lat_2 = latitude_2
    lon_2 = longitude_2
    
    lon_1, lat_1, lon_2, lat_2 = map(np.radians, [lon_1, lat_1, lon_2, lat_2])
    
    # Flattening.
    f = (a - b) / a
    
    # Reduced latitudes.
    beta_1 = np.arctan((1 - f) * np.tan(lat_1))
    beta_2 = np.arctan((1 - f) * np.tan(lat_2))
    
    P = (beta_2 + beta_1) / 2
    Q = (beta_2 - beta_1) / 2
    
    D = haversine(point_1, point_2)
        
    sigma = D / R
    
    X = (sigma - np.sin(sigma)) * (np.sin(P) ** 2 * np.cos(Q) ** 2) / np.cos(sigma / 2) ** 2
    Y = (sigma + np.sin(sigma)) * (np.cos(P) ** 2 * np.sin(Q) ** 2) / np.sin(sigma / 2) ** 2
    
    d = a * (sigma - f / 2 * (X + Y))
    
    return d


def nearest_model(latitudes, longitudes):
    
    if latitudes.ndim == longitudes.ndim == 1:
        
        latitudes, longitudes = np.meshgrid(latitudes, longitudes)
    
    coordinates = np.array([latitudes.ravel(), longitudes.ravel()]).T
    
    neighbors = NearestNeighbors(n_neighbors = NEIGHBORS_CHECKED,
                                 metric      = haversine)
    neighbors = neighbors.fit(coordinates)
    
    return coordinates, neighbors


def nearest(latitude, longitude, coordinates, neighbors):
    
    point = np.array([(latitude, longitude)])
    
    haversine_distances, indices = neighbors.kneighbors(point)
    lambert_distances = np.empty(NEIGHBORS_CHECKED)
    
    neighboring_coordinates = coordinates[indices[0]]
    
    for index, coordinate in enumerate(neighboring_coordinates):

        lambert_distances[index] = lambert(point[0], coordinate)
        
    nearness_mask     = np.where(lambert_distances == lambert_distances.min())
    closest_index     = indices[0][nearness_mask]
    closest_neighbor  = coordinates[closest_index]
    shortest_distance = lambert_distances[nearness_mask]
        
    return closest_index, closest_neighbor, shortest_distance


def collocate(anomaly_latitudes,
              anomaly_longitudes,
              data_latitudes,
              data_longitudes,
              anomaly_resolution = 1000,
              data_resolution    = 25000):
    
    anomalies = np.array([anomaly_latitudes, anomaly_longitudes]).T
    size      = anomalies.shape[0]
    
    print("Building model...")
    coordinates, model = nearest_model(data_latitudes, data_longitudes)
    
    closest_indices    = np.empty(size).astype(np.int32)
    closest_neighbors  = np.empty((size, 2))
    shortest_distances = np.empty(size)
    
    print("Beginning iteration...")
    
    for index, anomaly in tqdm(enumerate(anomalies), total = size):
        
        closest_index, closest_neighbor, shortest_distance = nearest(*anomaly, coordinates, model)

        closest_indices[index]    = closest_index[0]
        closest_neighbors[index]  = closest_neighbor[0]
        shortest_distances[index] = shortest_distance[0]
    
    return closest_indices, closest_neighbors, shortest_distances
    

if __name__ == "__main__":
    
    print("Reading files...")
    
    anomaly_df = pd.read_csv(r"C:\Users\Erick Shepherd\OneDrive\Filebank\Code\modis_caliop_anomaly_analysis\anomaly_mapping\2007-01_water_worldview_anomalies.csv")
    anomaly_df["sea_ice_concentration"] = pd.Series(dtype = np.uint8)
    
    dataset = nc.Dataset("AMSR_E_L3_SeaIce12km_V15_20070101.hdf")
    
    nh_shape = (896, 608)  # "nh" represents "northern hemisphere".
    sh_shape = (664, 632)  # "sh" represents "southern hemisphere".
    
    nh_ice_concentration = dataset["SI_12km_NH_ICECON_ASC"][:].data.astype(np.float).ravel()
    sh_ice_concentration = dataset["SI_12km_SH_ICECON_ASC"][:].data.astype(np.float).ravel()
    
    coordinates = get_geodetic_crs()
    
    anomaly_latitudes  = anomaly_df.latitude
    anomaly_longitudes = anomaly_df.longitude
    
    nh_latitudes  = coordinates["northern_hemisphere"]["latitudes"]
    nh_longitudes = coordinates["northern_hemisphere"]["longitudes"]
    sh_latitudes  = coordinates["southern_hemisphere"]["latitudes"]
    sh_longitudes = coordinates["southern_hemisphere"]["longitudes"]
    
    print("Beginning northern hemisphere collocation...")
    nh_r = collocate(anomaly_latitudes,
                     anomaly_longitudes,
                     nh_latitudes,
                     nh_longitudes)
    
    nh_closest_indices, nh_closest_neighbors, nh_shortest_distances = nh_r
    
    nh_ice_mask       = (0 <= nh_ice_concentration) & (nh_ice_concentration <= 100)
    nh_ice_mask       = nh_ice_mask[nh_closest_indices]
    nh_distance_mask  = nh_shortest_distances <= (25000 / 2) - (1000 / 2)
    nh_mask           = nh_ice_mask & nh_distance_mask
    nh_masked_indices = nh_closest_indices[nh_mask]
    nh_sea_ice        = nh_ice_concentration[nh_masked_indices]
    
    anomaly_df.loc[nh_mask, "sea_ice_concentration"] = nh_sea_ice
    
    print("Beginning southern hemisphere collocation...")
    sh_r = collocate(anomaly_latitudes,
                     anomaly_longitudes,
                     sh_latitudes,
                     sh_longitudes)
    
    sh_closest_indices, sh_closest_neighbors, sh_shortest_distances = sh_r
    
    sh_ice_mask       = (0 <= sh_ice_concentration) & (sh_ice_concentration <= 100)
    sh_ice_mask       = sh_ice_mask[sh_closest_indices]
    sh_distance_mask  = sh_shortest_distances <= (25000 / 2) - (1000 / 2)
    sh_mask           = sh_ice_mask & sh_distance_mask
    sh_masked_indices = sh_closest_indices[sh_mask]
    sh_sea_ice        = sh_ice_concentration[sh_masked_indices]
    
    anomaly_df.loc[sh_mask, "sea_ice_concentration"] = sh_sea_ice
    
    print("Saving results...")
    anomaly_df.to_csv("2007-01_water_worldview_anomalies_with_sea_ice.csv")
    print("Task completed successfully.")

    # TODO: PICKLE MODELS
    