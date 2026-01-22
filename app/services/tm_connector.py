import requests
from flask import current_app
from requests.exceptions import RequestException

class TrainingManagerConnector:
    def __init__(self):
        self.api_url = current_app.config.get('TM_API_URL')
        self.api_key = current_app.config.get('TM_API_KEY')
        self.verify_ssl = current_app.config.get('TM_VERIFY_SSL', True)

    def _request(self, method, endpoint, payload=None):
        if not self.api_url or not self.api_key:
            return None  # Fail-open if not configured

        url = f"{self.api_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {
            'X-Service-Key': self.api_key,
            'Content-Type': 'application/json'
        }
        try:
            response = requests.request(
                method,
                url,
                json=payload,
                headers=headers,
                verify=self.verify_ssl,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            current_app.logger.error(f"Training Manager API Error [{method} {endpoint}]: {e}")
            if e.response:
                current_app.logger.error(f"Response: {e.response.text}")
            return None  # Fail-open

    def get_skills(self):
        return self._request('GET', 'api/public/skills')

    def check_competency(self, emails, skill_ids):
        payload = {'emails': emails, 'skill_ids': skill_ids}
        return self._request('POST', 'api/public/check_competency', payload)

    def declare_practice(self, email, skill_ids, date, source):
        payload = {'email': email, 'skill_ids': skill_ids, 'date': date, 'source': source}
        return self._request('POST', 'api/public/declare_practice', payload)

    def get_user_calendar(self, email):
        return self._request('GET', f'api/public/user_calendar?email={email}')
