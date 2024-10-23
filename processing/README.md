# S3 --> MongoDB Atlas Processing Lambda Function

This lambda function has been created for the processing of DTIS files when they get uploaded to S3.

The script parses the contents and creates target documents in 2 collections in MongoDB Atlas. As various assumptions are made, both with respect to the format of the uploaded text files (\_prot.txt, \_rerun.txt), as well as the location of images and videos, standard operating procedures need to be arranged (and followed) for the script to be able to do a good job. (Among other things it attempts to locate any videos and images that belong to an observation file and adds links to those external files in the MongoDB collection, which can only work if we know where data are being stored.)

It's also important to know that the script logic follows some strict rules for parsing the file contents, especially in regard to the setup of a header and the number of columns for individual observations.

## Configuration of Lambda Environment variables

The Lambda function requires several environment variables to be configured, including:

S3_BUCKET_NAME --> the source S3 bucket in AWS (where DTIS prot files are taken from, for processing into MongoDB)
MONGODB_URI --> the connection string (URI) for the target MongoDB Atlas instance
MONGODB_DATABASE --> database to use for uploading documents
MONGODB_COLLECTION --> the 'observations' collection (where we want to store the main data from DTIS observation protocol files)
INGRESS_COLLECTION_DTIS --> a second collection, which stores summary information for a Cruise/StationID combination.
