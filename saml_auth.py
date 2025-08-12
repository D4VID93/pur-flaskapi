"""


from flask_saml2.sp import ServiceProvider
from flask_saml2.utils import certificate_from_string, private_key_from_string
import os

class AzureADServiceProvider(ServiceProvider):
    def get_logout_return_url(self):
        return "http://localhost:5000/login"  

    def get_default_login_return_url(self):
        return "http://localhost:5000/"  

    def get_entity_id(self):
        return os.getenv('AZURE_AD_ENTITY_ID')

    def get_acs_url(self):
        return "http://localhost:5000/saml/acs/"  # Endpoint ACS (Assertion Consumer Service)

    def get_slo_url(self):
        return "http://localhost:5000/saml/sls/"  # Endpoint Single Logout

    def get_sp_certificate(self):
        return certificate_from_string(os.getenv('AZURE_AD_CERTIFICATE'))

    def get_sp_private_key(self):
        return private_key_from_string(os.getenv('AZURE_AD_CERTIFICATE'))  # Même clé que le certificat

    def get_idp_config(self):
        return {
            'entity_id': os.getenv('AZURE_AD_ENTITY_ID'),
            'sso_url': os.getenv('AZURE_AD_SSO_URL'),
            'slo_url': os.getenv('AZURE_AD_SSO_URL').replace('/saml2', '/samlp'),
            'x509cert': os.getenv('AZURE_AD_CERTIFICATE'),
        }
"""