# tests/test_auth.py
from flask import url_for

from app.models import User
from tests.conftest import login, logout


def test_registration(test_client, db_session):
    """
    GIVEN a Flask application
    WHEN the '/register' page is posted to (POST)
    THEN a new user is created in the database
    """
    response = test_client.post('/auth/register', data={
        'email': 'newuser@test.com',
        'password': 'password123',
        'confirm_password': 'password123'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    # Success or SMTP warning (both mean registration worked logic-wise)
    assert b"A confirmation email has been sent" in response.data or b"Account created but SMTP is not configured" in response.data
    
    user = User.query.filter_by(email='newuser@test.com').first()
    assert user is not None
    assert not user.email_confirmed

def test_login_logout(test_client, init_database):
    """
    GIVEN a user created in the init_database fixture
    WHEN the user logs in and then logs out
    THEN check that the session is managed correctly
    """
    # Test successful login
    response = login(test_client, 'team1admin@test.com', 'password')
    assert response.status_code == 200
    assert b'Login Successful!' in response.data
    assert b'My Page' in response.data

    # Test logout
    response = logout(test_client)
    assert response.status_code == 200
    assert b'You have been logged out.' in response.data
    assert b'Welcome to precliniverse' in response.data

def test_login_with_invalid_credentials(test_client, init_database):
    """
    GIVEN a user
    WHEN the user attempts to log in with an incorrect password
    THEN check that an error message is displayed
    """
    response = login(test_client, 'team1admin@test.com', 'wrongpassword')
    assert response.status_code == 200
    assert b'Login Unsuccessful' in response.data