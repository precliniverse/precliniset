# tests/test_notification_service.py
"""
Tests de l'API de notifications in-app.
Vérifie la récupération, le marquage comme lu et la suppression des notifications.
"""
import json

import pytest

from app.models.notifications import Notification, NotificationType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_notification(db_session, user, message, notif_type=NotificationType.INFO, is_read=False, link=None):
    """Crée une notification en base pour un utilisateur donné."""
    notif = Notification(
        user_id=user.id,
        message=message,
        type=notif_type,
        is_read=is_read,
        link=link,
    )
    db_session.add(notif)
    db_session.flush()
    return notif


# ---------------------------------------------------------------------------
# Tests GET /api/notifications
# ---------------------------------------------------------------------------

def test_get_notifications_unauthenticated(test_client):
    """
    GIVEN un client non authentifié
    WHEN GET /api/notifications est appelé
    THEN la réponse doit être 401 ou une redirection vers login.
    """
    response = test_client.get('/api/notifications')
    assert response.status_code in (401, 302)


def test_get_notifications_empty(logged_in_client, db_session, init_database):
    """
    GIVEN un super_admin sans notifications
    WHEN GET /api/notifications est appelé
    THEN la réponse doit retourner une liste vide.
    """
    response = logged_in_client.get('/api/notifications')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'notifications' in data
    assert data['unread_count'] == 0


def test_get_notifications_returns_unread_only(logged_in_client, db_session, init_database):
    """
    GIVEN un super_admin avec 2 notifications (1 lue, 1 non lue)
    WHEN GET /api/notifications?unread_only=true est appelé
    THEN seule la notification non lue doit être retournée.
    """
    user = init_database['super_admin']
    create_notification(db_session, user, 'Unread notification', is_read=False)
    create_notification(db_session, user, 'Read notification', is_read=True)

    response = logged_in_client.get('/api/notifications?unread_only=true')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data['notifications']) == 1
    assert data['notifications'][0]['message'] == 'Unread notification'
    assert data['unread_count'] == 1


def test_get_notifications_returns_all_when_unread_false(logged_in_client, db_session, init_database):
    """
    GIVEN un super_admin avec 2 notifications (1 lue, 1 non lue)
    WHEN GET /api/notifications?unread_only=false est appelé
    THEN les deux notifications doivent être retournées.
    """
    user = init_database['super_admin']
    create_notification(db_session, user, 'Notification 1', is_read=False)
    create_notification(db_session, user, 'Notification 2', is_read=True)

    response = logged_in_client.get('/api/notifications?unread_only=false')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data['notifications']) == 2


def test_get_notifications_limit(logged_in_client, db_session, init_database):
    """
    GIVEN un super_admin avec 5 notifications non lues
    WHEN GET /api/notifications?limit=3 est appelé
    THEN seulement 3 notifications doivent être retournées.
    """
    user = init_database['super_admin']
    for i in range(5):
        create_notification(db_session, user, f'Notification {i}', is_read=False)

    response = logged_in_client.get('/api/notifications?limit=3&unread_only=false')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data['notifications']) == 3


def test_get_notifications_isolation(team1_admin_client, logged_in_client, db_session, init_database):
    """
    GIVEN deux utilisateurs avec des notifications différentes
    WHEN chacun appelle GET /api/notifications
    THEN chacun ne voit que ses propres notifications.
    """
    super_admin = init_database['super_admin']
    team1_admin = init_database['team1_admin']

    create_notification(db_session, super_admin, 'Admin notification')
    create_notification(db_session, team1_admin, 'Team1 admin notification')

    # super_admin voit sa notification
    response_admin = logged_in_client.get('/api/notifications?unread_only=false')
    data_admin = json.loads(response_admin.data)
    messages_admin = [n['message'] for n in data_admin['notifications']]
    assert 'Admin notification' in messages_admin
    assert 'Team1 admin notification' not in messages_admin

    # team1_admin voit sa notification
    response_team = team1_admin_client.get('/api/notifications?unread_only=false')
    data_team = json.loads(response_team.data)
    messages_team = [n['message'] for n in data_team['notifications']]
    assert 'Team1 admin notification' in messages_team
    assert 'Admin notification' not in messages_team


# ---------------------------------------------------------------------------
# Tests POST /api/notifications/<id>/read
# ---------------------------------------------------------------------------

def test_mark_notification_read(logged_in_client, db_session, init_database):
    """
    GIVEN une notification non lue
    WHEN POST /api/notifications/<id>/read est appelé
    THEN la notification doit être marquée comme lue.
    """
    user = init_database['super_admin']
    notif = create_notification(db_session, user, 'Mark me read', is_read=False)

    response = logged_in_client.post(f'/api/notifications/{notif.id}/read')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is True

    db_session.refresh(notif)
    assert notif.is_read is True


def test_mark_notification_read_wrong_user(team1_admin_client, db_session, init_database):
    """
    GIVEN une notification appartenant à super_admin
    WHEN team1_admin essaie de la marquer comme lue
    THEN la réponse doit être 404 (isolation des données).
    """
    super_admin = init_database['super_admin']
    notif = create_notification(db_session, super_admin, 'Admin only notification')

    response = team1_admin_client.post(f'/api/notifications/{notif.id}/read')
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests POST /api/notifications/read_all
# ---------------------------------------------------------------------------

def test_mark_all_notifications_read(logged_in_client, db_session, init_database):
    """
    GIVEN un super_admin avec plusieurs notifications non lues
    WHEN POST /api/notifications/read_all est appelé
    THEN toutes les notifications doivent être marquées comme lues.
    """
    user = init_database['super_admin']
    for i in range(3):
        create_notification(db_session, user, f'Notif {i}', is_read=False)

    response = logged_in_client.post('/api/notifications/read_all')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is True

    # Vérifier que toutes les notifications sont lues
    response2 = logged_in_client.get('/api/notifications?unread_only=true')
    data2 = json.loads(response2.data)
    assert data2['unread_count'] == 0


# ---------------------------------------------------------------------------
# Tests DELETE /api/notifications/<id>
# ---------------------------------------------------------------------------

def test_delete_notification(logged_in_client, db_session, init_database):
    """
    GIVEN une notification existante
    WHEN DELETE /api/notifications/<id> est appelé
    THEN la notification doit être supprimée.
    """
    user = init_database['super_admin']
    notif = create_notification(db_session, user, 'Delete me')
    notif_id = notif.id

    response = logged_in_client.delete(f'/api/notifications/{notif_id}')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is True

    # Vérifier que la notification n'existe plus
    assert Notification.query.get(notif_id) is None


def test_delete_notification_wrong_user(team1_admin_client, db_session, init_database):
    """
    GIVEN une notification appartenant à super_admin
    WHEN team1_admin essaie de la supprimer
    THEN la réponse doit être 404.
    """
    super_admin = init_database['super_admin']
    notif = create_notification(db_session, super_admin, 'Admin only')

    response = team1_admin_client.delete(f'/api/notifications/{notif.id}')
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests du modèle Notification
# ---------------------------------------------------------------------------

def test_notification_to_dict(db_session, init_database):
    """
    GIVEN une notification créée
    WHEN to_dict() est appelé
    THEN le dictionnaire doit contenir tous les champs attendus.
    """
    user = init_database['super_admin']
    notif = create_notification(
        db_session, user, 'Test message',
        notif_type=NotificationType.SUCCESS,
        link='/some/link',
    )

    d = notif.to_dict()
    assert d['id'] == notif.id
    assert d['message'] == 'Test message'
    assert d['type'] == NotificationType.SUCCESS
    assert d['is_read'] is False
    assert d['link'] == '/some/link'
    assert d['created_at'] is not None


def test_notification_types_constants():
    """Vérifie que les constantes NotificationType sont correctement définies."""
    assert NotificationType.INFO == 'info'
    assert NotificationType.SUCCESS == 'success'
    assert NotificationType.WARNING == 'warning'
    assert NotificationType.ERROR == 'error'
    assert NotificationType.ANALYSIS_DONE == 'analysis_done'
    assert NotificationType.WORKPLAN_UPDATE == 'workplan_update'
    assert NotificationType.EMAIL_FALLBACK == 'email_fallback'
