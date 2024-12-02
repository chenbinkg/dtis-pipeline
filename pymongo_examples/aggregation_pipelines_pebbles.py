import pymongo

LOCAL_SHELL = True

# These should be stored as environment variables
db_username = "database_user"
db_password = "database_user_password"

cluster_name = "ServerlessInstance0"
database_name = "dtistest"
collection_name = "DTISOFOP"

connection_string = f"mongodb+srv://{db_username}:{db_password}@serverlessinstance0.ta8golw.mongodb.net/?retryWrites=true&w=majority&appName=ServerlessInstance0"

# Connect to your MongoDB cluster:
try:
    cluster = pymongo.MongoClient(connection_string)
except exception as e:
    print(e)

# Get a reference to the "database_name" database.
db = cluster[database_name]

# Get a reference to the "collection_name" collection:
collection = db[collection_name]


# Match documents with field 'feature.observation2' = 'Pebbles'
stage_match_observations2_pebbles = {
    '$match': {
        'feature.observation2': 'Pebbles'
    }
}

# Match documents with field 'depth' less-than 5000.0:
stage_match_depth_less_than_5000 = {
    '$match': {
        'depth': { '$lt': 5000.0 }
    } 
}

# Match documents with field 'speed' greater-than 1.0:
stage_match_speed_greater_than_1 = {
    '$match': {
        'speed': { '$gt': 1.0 }
    }
}


# Match documents using $geoWithin and bounding $box longtitude and latitude coordinates
#
# If you use longitude and latitude, specify longitude first.
# https://www.mongodb.com/docs/manual/reference/operator/query/box/#mongodb-query-op.-box
# '$box': [
#     [ <bottom left coordinates> ],
#     [ <upper right coordinates> ]
# ]
#
longitude_bottom_left = -180.0
latitude_bottom_left = -180.0
coordinates_bottom_left = [longitude_bottom_left, latitude_bottom_left]

longitude_upper_right = 180
latitude_upper_right = 180
coordinates_upper_right = [longitude_upper_right, latitude_upper_right]

stage_ship_location_within_coordinates = {
    '$match': {
        'shipLocation.coordinates': {
            '$geoWithin': {
                '$box': [
                    coordinates_bottom_left,
                    coordinates_upper_right
                ]
            }
        }
    }
}

# TODO - Other types of Ag. Pipeline queries...

# Create Aggregation Pipeline from discrete stages.
pipeline = [
   stage_match_observations2_pebbles,
   stage_match_depth_less_than_5000,
   stage_match_speed_greater_than_1,
   stage_ship_location_within_coordinates,
]

# Execute the Aggregation Pipeline queries against the collection.
results = collection.aggregate(pipeline)


# Iterate through Aggregation Pipeline queries results...
number_of_records = 0
for record in results:
    print(f"New Record:\n{record}\n")
    number_of_records+=1

print(f"Number of records: {number_of_records}")
