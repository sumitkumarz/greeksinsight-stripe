import requests
from app.config import Config

def cognito_global_logout(access_token: str) -> bool:
    """
    Calls AWS Cognito global signout API to revoke the user's session.
    Returns True if successful, False otherwise.
    """
    url = f"https://cognito-idp.{Config.COGNITO_DOMAIN.split('.')[1]}.amazonaws.com/"
    headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService.GlobalSignOut",
    }
    payload = {
        "AccessToken": access_token
    }
    response = requests.post(url, headers=headers, json=payload)
    return response.status_code == 200
