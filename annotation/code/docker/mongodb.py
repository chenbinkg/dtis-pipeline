from pymongo.mongo_client import MongoClient
import logging
import pandas as pd
import boto3
import sys

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger()

class MongoDBOps:

    def __init__(self, ssm_param="/dtis/mongodb/uri", region_name="ap-southeast-2"):
        """Initialize MongoDBOps with connection string from AWS SSM Parameter Store.
        Args:
            ssm_param (str): The SSM parameter name for the MongoDB connection string.
            This should be the full path to the parameter, e.g., '/dtis/mongodb/uri'.
            The connection string should be in the format:
            'mongodb+srv://username:password@cluster0.mongodb.net/test?retryWrites=true&w=majority'
        """
        ssm = boto3.client('ssm', region_name=region_name)
        parameter_name = ssm_param
        # Get parameter (with decryption if it's a SecureString)
        response = ssm.get_parameter(
            Name=parameter_name,
            WithDecryption=True
        )
        
        # Extract the MongoDB URI
        self.conn_string = response['Parameter']['Value']
        # self.client = MongoClient(self.conn_string)

    def read_to_df(self, db_name, collection_name, query_filter, column_filter):
        client = MongoClient(self.conn_string)
        coll = client[db_name][collection_name]
        mydoc = coll.find(query_filter, column_filter)
        df =  pd.DataFrame(list(mydoc))
        # df['obs_date'] = pd.to_datetime(df["obs_date"])  
        # df.set_index('obs_date')
        if "_id" in df.columns:
            df = df.drop('_id', axis=1)
        client.close()
        return df
    
    def gen_query_filter(self, columns, values):
        '''Generate query filter conditions'''
        query_filter = {}
        for col, val in zip(columns, values):
            query_filter[col] = val
        _logger.info(f"query_filter: {query_filter}")
        return query_filter

    def gen_column_filter(self, columns):
        '''Generate column filter in the following format:
        {col1: 1, col2: 1, col3: 1, col3: 1, col4: 1}
        '''
        column_filter = {}
        for col in columns:
            column_filter[col] = 1
        _logger.info(f"column_filter: {column_filter}")
        return column_filter
    
    def write_to_mongodb(self, db_name, collection_name, data):
        client = MongoClient(self.conn_string)
        coll = client[db_name][collection_name]
        coll.insert_one(data)
        client.close()
        _logger.info(f"written 1 record to MongoDB {db_name}:{collection_name}")