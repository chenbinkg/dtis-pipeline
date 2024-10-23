# Configuration of Lambda Environment variables

The Lambda function requires several environment variables to be configured, including:

S3_BUCKET_NAME --> the source S3 bucket in AWS (where DTIS prot files are taken from, for processing into MongoDB)
MONGODB_URI --> the connection string (URI) for the target MongoDB Atlas instance
MONGODB_DATABASE --> database to use for uploading documents
MONGODB_COLLECTION --> the 'observations' collection (where we want to store the main data from DTIS observation protocol files)
INGRESS_COLLECTION_DTIS --> a second collection, which stores summary information for a Cruise/StationID combination.
