import logging
import copy
import os
import requests
import sys
from requests.auth import HTTPBasicAuth
from typing import Literal, Union, List, Dict, Any

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
_logger = logging.getLogger()

class Api(object):
    def __init__(self, email='', token='', base_url='https://biigle.de/api/v1', headers={}):
        """Create a new instance.

        Args:
            email (str): The email address of the user.
            token (str): The API token of the user.

        Kwargs:
            base_url (str): Base URL to use for the API URL. Default: `'https://biigle.de/api/v1'`.
            headers (dict): Default headers to use for each request. Default: `{'Accept': 'application/json'}`.
        """
        email = email if email else os.getenv('BIIGLE_API_EMAIL')
        token = token if token else os.getenv('BIIGLE_API_TOKEN')
        if email is None or token is None:
            raise ValueError("No API credentials were provided!")
        self.auth = HTTPBasicAuth(email, token)
        self.base_url = base_url
        self.headers = {'Accept': 'application/json'}
        self.headers.update(headers)

    def call(self, method, url, raise_for_status = True, *args, **kwargs):
        """Perform an API call

        In addition to the method and URL, any args or kwargs of the requests method are
        accepted.

        Args:
            method: The requests method to use for the api call.
            url: The API endpoint to call.
            raise_for_status: Raise an exception if the response code is not ok.
        """
        if 'headers' in kwargs:
            headers = copy.deepcopy(self.headers)
            headers.update(kwargs['headers'])
        else:
            headers = self.headers
        kwargs['headers'] = headers
        kwargs['auth'] = self.auth

        response = method('{}/{}'.format(self.base_url, url), *args, **kwargs)

        if raise_for_status:
            if response.status_code == 422:
                body = response.json()
                raise Exception(body['message'], body['errors'])
            else:
                response.raise_for_status()

        return response

    def get(self, url, *args, **kwargs):
        """Perform a GET request to the API

        See the `call` method for available arguments.
        """
        return self.call(requests.get, url, *args, **kwargs)

    def post(self, url, *args, **kwargs):
        """Perform a POST request to the API

        See the `call` method for available arguments.
        """
        return self.call(requests.post, url, *args, **kwargs)

    def put(self, url, *args, **kwargs):
        """Perform a PUT request to the API

        See the `call` method for available arguments.
        """
        return self.call(requests.put, url, *args, **kwargs)

    def delete(self, url, *args, **kwargs):
        """Perform a DELETE request to the API

        See the `call` method for available arguments.
        """
        return self.call(requests.delete, url, *args, **kwargs)

    def create_user_disk(self, type: Literal['s3', 'aos'], name: str, **kwargs: Any):
        """User-Disks - Create a new user disk

        Depending on the storage disk type, different additional arguments are required.

        Args:
            type (Literal['s3', 'aos']): The storage disk type. One of 's3' or 'aos'.
            name (str): The name of the storage disk.
            **kwargs: Additional arguments specific to the storage disk type.
                For 's3' type:
                    key (str): The S3 access key.
                    secret (str): The S3 secret key.
                    bucket (str): The S3 bucket name.
                    region (str): The S3 region. Example: 'us-east-1'.
                    endpoint (str): The S3 endpoint URL. Example 'https://s3.example.com'.
                For 'aos' type: (Assuming similar pattern, but not specified in API)

        Returns:
            requests.Response: The response object from the API call.
        """
        endpoint = "user-disks"
        payload = {
            "type": type,
            "name": name,
        }

        if type == 's3':
            required_s3_args = ['key', 'secret', 'bucket', 'region', 'endpoint']
            for arg in required_s3_args:
                if arg not in kwargs:
                    raise ValueError(f"S3 disk type requires '{arg}' argument.")
                payload[arg] = kwargs[arg]
        elif type == 'aos':
            # Add AOS specific required arguments here if available in documentation
            # For now, assuming it might also have specific requirements
            pass # Currently no specific AOS arguments are listed in your prompt.
        else:
            raise ValueError(f"Unknown storage disk type: {type}")

        return self.post(endpoint, json=payload)

    def create_project(self, name: str, description: str):
        """Projects - Create a new project

        The user creating a new project will automatically become project admin.

        Args:
            name (str): Name of the new project.
            description (str): Description of the new project.

        Returns:
            requests.Response: The response object from the API call,
                               containing the details of the newly created project.
        """
        endpoint = "projects"
        payload = {
            "name": name,
            "description": description
        }
        return self.post(endpoint, json=payload)

    def add_label_tree_to_project(self, project_id: int, label_tree_id: int):
        """Projects - Add a label tree

        The label tree must be either public or have the project authorized to use it.

        Args:
            project_id (int): The ID of the project to add the label tree to.
            label_tree_id (int): The ID of the label tree to add.

        Returns:
            requests.Response: The response object from the API call.
        """
        endpoint = f"projects/{project_id}/label-trees"
        payload = {
            "id": label_tree_id
        }
        return self.post(endpoint, json=payload)

    def authorize_project_on_label_tree(self, label_tree_id: int, project_id_to_authorize: int):
        """Label_Trees - Add authorized project
        Authorizes a project to use a specific label tree. The label tree must be
        either public or the user must be a labelTreeAdmin.

        Args:
            label_tree_id (int): The ID of the label tree to authorize the project for.
            project_id_to_authorize (int): The ID of the project to authorize.

        Returns:
            requests.Response: The response object from the API call.
        """
        endpoint = f"label-trees/{label_tree_id}/authorized-projects"
        payload = {
            "id": project_id_to_authorize
        }
        return self.post(endpoint, json=payload)

    def add_member_to_project(self, project_id: int, user_id: int, project_role_id: int):
        """Projects - Add a new member

        Args:
            project_id (int): The project ID.
            user_id (int): The user ID of the new member.
            project_role_id (int): The project role ID to assign to the member.

        Returns:
            requests.Response: The response object from the API call.
        """
        endpoint = f"projects/{project_id}/users/{user_id}"
        payload = {
            "project_role_id": project_role_id
        }
        return self.post(endpoint, json=payload)

    def find_user(self, pattern: str):
        """Users - Find a user
        Searches for a user with firstname or lastname like 'pattern' and returns the first 10 matches.

        Args:
            pattern (str): Part of the firstname or lastname of the user to search for.

        Returns:
            requests.Response: The response object from the API call, containing a list of matching users.
        """
        endpoint = f"users/find/{pattern}"
        return self.get(endpoint)

    def create_pending_volume(self, project_id: int, media_type: Literal['image', 'video'], metadata_file_path: str = None, metadata_parser: str = None):
        """Volumes - Create a new pending volume

        Args:
            project_id (int): The project ID.
            media_type (Literal['image', 'video']): The media type of the new volume (image or video).
            metadata_file_path (str, optional): A file with volume and image/video metadata (e.g., CSV).
                                                This attribute is required if metadata_parser is specified.
            metadata_parser (str, optional): The class namespace of the metadata parser to use.
                                             This attribute is required if metadata_file is specified.

        Returns:
            requests.Response: The response object from the API call,
                               containing the new pending volume ID.
        """
        endpoint = f"projects/{project_id}/pending-volumes"

        payload = {
            "media_type": media_type
        }

        files = {}
        if metadata_file_path:
            if not os.path.exists(metadata_file_path):
                raise FileNotFoundError(f"Metadata file not found at: {metadata_file_path}")
            if metadata_parser is None:
                raise ValueError("metadata_parser must be specified if metadata_file_path is provided.")

            files['metadata_file'] = open(metadata_file_path, 'rb')
            payload['metadata_parser'] = metadata_parser

        try:
            if files:
                response = self.post(endpoint, data=payload, files=files)
            else:
                response = self.post(endpoint, json=payload)
        finally:
            if 'metadata_file' in files:
                files['metadata_file'].close()

        return response


    def create_volume(self, pending_volume_id: int, name: str, url: str, files: Union[List[str], str], handle: str = None, import_annotations: bool = False, import_file_labels: bool = False):
        """Volumes - Create a new volume (v2)

        When this endpoint is called, the new volume is already created.
        Then there are two ways forward:
        1) The user wants to import annotations and/or file labels. Then the pending volume is kept and used for the next steps (see the import_* attributes).
           Continue with (#Volumes:UpdatePendingVolumeAnnotationLabels) in this case.
        2) Otherwise the pending volume will be deleted here.
        In both cases the endpoint returns the pending volume (even if it was deleted) which was updated with the new volume ID.

        Args:
            pending_volume_id (int): The pending volume ID.
            name (str): The name of the new volume.
            url (str): The base URL of the image/video files. Can be a path to a storage disk like local://volumes/1 or a remote path like https://example.com/volumes/1.
            files (Union[List[str], str]): Array of file names of the images/videos that can be found at the base URL. Example: With the base URL local://volumes/1 and the image 1.jpg, the file volumes/1/1.jpg of the local storage disk will be used. This can also be a plain string of comma-separated filenames.
            handle (str, optional): Handle or DOI of the dataset that is represented by the new volume. Defaults to None.
            import_annotations (bool, optional): Set to true to keep the pending volume for annotation import. Otherwise the pending volume will be deleted after this request. Defaults to False.
            import_file_labels (bool): Set to true to keep the pending volume for file label import. Otherwise the pending volume will be deleted after this request. Defaults to False.

        Returns:
            requests.Response: The response object from the API call.
        """
        endpoint = f"pending-volumes/{pending_volume_id}"

        payload = {
            "name": name,
            "url": url,
            "files": files,
        }

        if handle is not None:
            payload["handle"] = handle
        if import_annotations:
            payload["import_annotations"] = True
        if import_file_labels:
            payload["import_file_labels"] = True

        return self.put(endpoint, json=payload)

    def fetch_image_data_from_api(self, volume_id: int):
        try:
            # API call to fetch the filenames from the volume
            response = self.get(f'volumes/{volume_id}/filenames')  # Adjust endpoint
            response.raise_for_status()
            data = response.json()
    
            # Print API response to check if it's returning anything
            # print(f"API response: {data}")
    
            # Ensure the response is a dictionary
            if isinstance(data, dict):
                return data 
            else:
                _logger.error("Unexpected API response format.")
                return {}
        except requests.RequestException as e:
            _logger.error(f"Error fetching image data from API: {e}")
            return {}