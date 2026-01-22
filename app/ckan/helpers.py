# app/ckan/helpers.py
import ipaddress
import json
import re
import socket
from urllib.parse import urlparse

import requests
from flask import current_app


def sanitize_ckan_name(name):
    """Sanitizes a string to be a valid CKAN dataset name."""
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'[\s/\\_.,;:]+', '-', name)
    name = re.sub(r'[^a-z0-9-]', '', name)
    name = name.strip('-')
    name = re.sub(r'-+', '-', name)
    return name

def validate_external_url(url):
    """
    Validates that a URL does not point to a private, reserved, or loopback IP address.
    Returns the resolved IP address if valid.
    Raises a ValueError if the URL is invalid or points to an internal resource.
    """
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        if not hostname:
            raise ValueError("URL must have a valid hostname.")

        # Prevent requests to localhost or other common loopback names
        if hostname.lower() in ['localhost', 'host.docker.internal']:
             raise ValueError("Hostname resolves to a loopback address.")

        ip_address_str = socket.gethostbyname(hostname)
        ip_obj = ipaddress.ip_address(ip_address_str)

        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved:
            raise ValueError(f"URL resolves to a non-public IP address: {ip_address_str}")
        
        return ip_address_str

    except socket.gaierror:
        raise ValueError(f"Could not resolve hostname: {hostname}")
    except Exception as e:
        # Re-raise with a more generic message to avoid leaking internal details
        if isinstance(e, ValueError):
            raise e
        raise ValueError(f"URL validation failed.")


def ckan_request(method, url, api_key, **kwargs):
    """Helper function to make requests to the CKAN API with SSRF protection."""
    headers = {
        'Authorization': api_key,
        'Content-Type': 'application/json'
    }
    try:
        # SECURITY FIX: Validate the URL and resolve IP once to prevent DNS Rebinding
        resolved_ip = validate_external_url(url)
        
        # Rewrite URL to use IP address but satisfy server with Host header
        parsed_url = urlparse(url)
        headers['Host'] = parsed_url.hostname
        target_url = url.replace(parsed_url.hostname, resolved_ip, 1)

        # SECURITY FIX: Disable redirects to prevent SSRF bypass via internal redirects
        if method.upper() == 'GET':
            response = requests.get(target_url, headers=headers, params=kwargs.get('params', {}), timeout=20, allow_redirects=False)
        elif method.upper() == 'POST':
            response = requests.post(target_url, headers=headers, data=json.dumps(kwargs.get('json_data')), files=kwargs.get('files'), timeout=60, allow_redirects=False)
        else:
            raise ValueError("Unsupported HTTP method")

        if response.status_code >= 400:
            error_message = f"CKAN request failed with status {response.status_code}."
            try:
                error_json = response.json()
                error_details = error_json.get('error', {})
                specific_message = error_details.get('message', 'No specific message in JSON.')
                if isinstance(error_details, dict):
                    for key, value in error_details.items():
                        if key != '__type' and key != 'message' and isinstance(value, list) and len(value) > 0:
                            specific_message = f"{key.capitalize()}: {value}"
                            break
                error_message += f" Details: {specific_message}"
            except json.JSONDecodeError:
                error_text = response.text
                current_app.logger.error(f"CKAN returned a non-JSON error response (likely a traceback):\n{error_text}")
                error_message += f" Server returned non-JSON response. See application logs for the full traceback from CKAN."
            
            raise requests.exceptions.HTTPError(error_message, response=response)

        if response.text:
            return response.json().get('result')
        return None

    except (requests.exceptions.RequestException, ValueError) as e:
        current_app.logger.error(f"CKAN request failed with a network, HTTP, or validation error: {e}", exc_info=True)
        raise

def get_user_organizations(api_key, ckan_url):
    """Fetches the organizations a user is a member of."""
    api_url = f"{ckan_url.rstrip('/')}/api/3/action/organization_list_for_user"
    return ckan_request('GET', api_url, api_key)

def package_show(api_key, ckan_url, dataset_name_or_id):
    """Fetches details of a dataset (project), returns None if not found."""
    api_url = f"{ckan_url.rstrip('/')}/api/3/action/package_show"
    headers = {'Authorization': api_key}
    params = {'id': dataset_name_or_id}
    
    try:
        # SECURITY FIX: Validate the URL and resolve IP once to prevent DNS Rebinding
        resolved_ip = validate_external_url(api_url)
        
        # Rewrite URL to use IP address but satisfy server with Host header
        parsed_url = urlparse(api_url)
        headers['Host'] = parsed_url.hostname
        target_url = api_url.replace(parsed_url.hostname, resolved_ip, 1)

        response = requests.get(target_url, headers=headers, params=params, timeout=20, allow_redirects=False)
        
        if response.status_code == 404:
            return None

        response.raise_for_status()
        
        json_response = response.json()
        if json_response.get('success'):
            return json_response.get('result')
        else:
            error_details = json_response.get('error', {})
            error_message = error_details.get('message', 'Unknown CKAN API error in package_show')
            current_app.logger.error(f"CKAN API Error (package_show): {error_message} - Details: {error_details}")
            raise requests.exceptions.HTTPError(f"CKAN API Error: {error_message}")

    except (requests.exceptions.RequestException, ValueError) as e:
        current_app.logger.error(f"CKAN package_show request failed: {e}", exc_info=True)
        raise

def package_create(api_key, ckan_url, name, title, owner_org, private, notes):
    """Creates a new dataset (project)."""
    api_url = f"{ckan_url.rstrip('/')}/api/3/action/package_create"
    data = {
        'name': name,
        'title': title,
        'owner_org': owner_org,
        'private': private,
        'notes': notes
    }
    return ckan_request('POST', api_url, api_key, json_data=data)

def resource_create(api_key, ckan_url, package_id, name, description, file_content):
    """Uploads a file as a new resource."""
    api_url = f"{ckan_url.rstrip('/')}/api/3/action/resource_create"
    data = {
        'package_id': package_id,
        'name': name,
        'description': description
    }
    files = {'upload': (name, file_content)}
    headers = {'Authorization': api_key, 'Host': urlparse(api_url).hostname}
    try:
        # SECURITY FIX: Validate the URL and resolve IP once to prevent DNS Rebinding
        resolved_ip = validate_external_url(api_url)
        target_url = api_url.replace(urlparse(api_url).hostname, resolved_ip, 1)

        response = requests.post(target_url, data=data, files=files, headers=headers, timeout=300, allow_redirects=False)

        if response.status_code >= 400:
            error_message = f"CKAN returned an error (Status {response.status_code}) during resource creation."
            try:
                error_json = response.json()
                specific_message = error_json.get('error', {}).get('message', 'No specific message in JSON.')
                error_message += f" Details: {specific_message}"
            except json.JSONDecodeError:
                error_text = response.text
                current_app.logger.error(f"CKAN returned non-JSON for resource_create:\n{error_text[:500]}...")
                error_message += " Server returned a non-JSON response (likely an HTML error page). Check application logs for details."
            raise requests.exceptions.HTTPError(error_message, response=response)

        json_response = response.json()
        if json_response.get('success'):
            return json_response.get('result')
        else:
            error_details = json_response.get('error', {})
            error_message = error_details.get('message', 'Unknown CKAN API error during resource creation')
            raise requests.exceptions.HTTPError(f"CKAN API Error: {error_message}")

    except (requests.exceptions.RequestException, ValueError) as e:
        current_app.logger.error(f"CKAN resource_create failed: {e}", exc_info=True)
        raise

def resource_update(api_key, ckan_url, resource_id, file_content, name, description):
    """Updates an existing resource with a new file."""
    api_url = f"{ckan_url.rstrip('/')}/api/3/action/resource_update"
    data = {'id': resource_id, 'name': name, 'description': description}
    files = {'upload': (name, file_content)}
    headers = {'Authorization': api_key, 'Host': urlparse(api_url).hostname}
    try:
        # SECURITY FIX: Validate the URL and resolve IP once to prevent DNS Rebinding
        resolved_ip = validate_external_url(api_url)
        target_url = api_url.replace(urlparse(api_url).hostname, resolved_ip, 1)

        response = requests.post(target_url, data=data, files=files, headers=headers, timeout=300, allow_redirects=False)

        if response.status_code >= 400:
            error_message = f"CKAN returned an error (Status {response.status_code}) during resource update."
            try:
                error_json = response.json()
                specific_message = error_json.get('error', {}).get('message', 'No specific message in JSON.')
                error_message += f" Details: {specific_message}"
            except json.JSONDecodeError:
                error_text = response.text
                current_app.logger.error(f"CKAN returned non-JSON for resource_update:\n{error_text[:500]}...")
                error_message += " The server returned a non-JSON response (likely an HTML error page). Check application logs for details."
            raise requests.exceptions.HTTPError(error_message, response=response)

        json_response = response.json()
        if json_response.get('success'):
            return json_response.get('result')
        else:
            error_details = json_response.get('error', {})
            error_message = error_details.get('message', 'Unknown CKAN API error during resource update')
            raise requests.exceptions.HTTPError(f"CKAN API Error: {error_message}")

    except (requests.exceptions.RequestException, ValueError) as e:
        current_app.logger.error(f"CKAN resource_update failed: {e}", exc_info=True)
        raise