### Using AWS Rekognition Custom Labels for training a species detection model for DTIS data

This folder contains the python pipeline used in experimenting development of a AI object detection model for identifying and classifying fish from DTIS video data. The `aws_` prefix pipeline python files leverage AWS Rekognition Custom Label service for training the said detection model. 

Before running the `aws_` prefix pipeline python codes for your own data/start new project, please ensure you read through the `Custom Labels` documentation [here](https://docs.aws.amazon.com/rekognition/latest/customlabels-dg/creating-model.html). Ensure that you have created and setup the `project` and `datasets` you will be using with the pipelines here.