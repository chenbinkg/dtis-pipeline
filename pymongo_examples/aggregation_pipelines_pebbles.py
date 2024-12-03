import os
import pymongo

def flatten_json(y):
    out = {}

    def flatten(x, name=''):
        if type(x) is dict:
            for a in x:
                flatten(x[a], name + a + '_')
        elif type(x) is list:
            i = 0
            for a in x:
                flatten(a, name + str(i) + '_')
                i += 1
        else:
            out[name[:-1]] = x

    flatten(y)
    return out




if __name__ == '__main__':

    # TODO: For Bryce/ Tilmann - Add this in your SOP 
    #   - "Don't hardcode your authentication credentials here. Set them as environment."
    # These secrets should always be stored as environment variables and sourced from within application code.
    # This can be achieved by setting by hardcoding them in `auth_env_vars` and loaded by executing "source auth_env_vars".
    db_username = os.environ.get("MONGODB_CLUSTER_USERNAME")
    db_password = os.environ.get("MONGODB_CLUSTER_PASSWORD")

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


    # TODO: Wildcard for capital/lowercase letters.
    # TODO: Show examples of MQL -> python
    #       - 
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
            'speed': { '$gt': 0.0 }
        }
    }

    # TODO: greater-than-or-equal-to stage


    # Match documents using $geoWithin and bounding $box longtitude and latitude coordinates.
    #
    # If you use longitude and latitude, specify longitude first.
    #  - Valid longitude values are between -180 and 180, both inclusive.
    #  - Valid latitude values are between -90 and 90, both inclusive.
    # https://www.mongodb.com/docs/manual/reference/operator/query/box/#mongodb-query-op.-box
    # '$box': [
    #     [ <bottom left coordinates> ],
    #     [ <upper right coordinates> ]
    # ]
    #
    longitude_bottom_left = -180.0
    latitude_bottom_left = -90.0
    coordinates_bottom_left = [longitude_bottom_left, latitude_bottom_left]

    longitude_upper_right = 180.0
    latitude_upper_right = 90.0
    coordinates_upper_right = [longitude_upper_right, latitude_upper_right]

    stage_ship_location_within_bounding_box = {
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

    # Match documents using $geoWithin and bounding $centerSphere with longtitude and latitude coordinates center.
    #
    # When you specify longitude and latitude coordinates, list the longitude first, and then latitude.
    #  - Valid longitude values are between -180 and 180, both inclusive.
    #  - Valid latitude values are between -90 and 90, both inclusive.
    # In the $centerSphere operator, specify the circle's radius in radians.
    #  - To convert kilometers to radians, divide the kilometer value by 6378.1.
    # https://www.mongodb.com/docs/manual/core/indexes/index-types/geospatial/2dsphere/query/points-within-circle-on-sphere/
    # '$centerSphere': [
    #     [ <longitude>, <latitude> ],
    #     <radius>
    # ]
    #
    longitude_center = 0.0
    latitude_center = 0.0
    coordinates_center = [longitude_center, latitude_center]

    def convert_kilometers_to_radians (kilometers: float) -> float:
        return kilometers / 6378.1

    radius_kilometers = 50000
    radius_radians = convert_kilometers_to_radians(radius_kilometers)

    stage_ship_location_within_bounding_circle = {
        '$match': {
            'shipLocation.coordinates': {
                '$geoWithin': {
                    '$centerSphere': [
                        coordinates_center,
                        radius_radians
                    ]
                }
            }
        }
    }

    # Create Aggregation Pipeline from discrete stages.
    pipeline = [
       stage_match_observations2_pebbles,
       stage_match_depth_less_than_5000,
       stage_match_speed_greater_than_1,
       stage_ship_location_within_bounding_box,
       stage_ship_location_within_bounding_circle,
    ]

    # TODO - Other types of Ag. Pipeline queries...

    # Execute the Aggregation Pipeline queries against the collection.
    records = collection.aggregate(pipeline)

    # Iterate through Aggregation Pipeline queries results...
    number_of_records = 0
    for record in records:
        print(f"New Record:\n{record}\n")
        
        number_of_records+=1
    
    print(f"Number of records: {number_of_records}\n\n")


    # The following code allow uploading the code to a new staging collection.
    UPLOAD_TO_NEW_COLLECTION = False
    
    if UPLOAD_TO_NEW_COLLECTION:
    
        aggregated_operations = []
        records = collection.aggregate(pipeline)

        # Iterate through Aggregation Pipeline queries results...
        for record in records:
            # Flatten JSON record.
            flattened_record = flatten_json(record)
            print(f"Flattened Record:\n{flattened_record}\n")

            # Create a list of record insert operations to apply to the collection.
            aggregated_operations.append(pymongo.InsertOne(flattened_record))
    
        # Get a reference to the "collection_name" collection:
        aggregated_collection_name = "staging_aggregated_and_flattened"
        aggregated_collection = db[aggregated_collection_name]

        # Bulk-write the non-zero list of record insert operations to the collection.
        # See the following link for docs on bulk-write operations using pymongo.
        # https://www.mongodb.com/docs/languages/python/pymongo-driver/current/write/bulk-write/#bulk-write-operations
        if ( len(aggregated_operations) > 0 ):
            aggregated_collection.bulk_write(aggregated_operations)