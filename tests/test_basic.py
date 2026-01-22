def test_logged_in_client_redirects_from_index(logged_in_client):
    """
    GIVEN a logged-in user (in this case, the super_admin_client fixture)
    WHEN the '/' page is requested (GET)
    THEN check that the user is redirected to the 'my_page'
    """
    # The super_admin_client fixture handles logging in.
    # A subsequent GET to '/' should redirect to the user's dashboard.
    response = logged_in_client.get('/', follow_redirects=True)
    assert response.status_code == 200
    assert b"My Page" in response.data
    assert b"Welcome to precliniset" not in response.data
